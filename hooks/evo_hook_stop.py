#!/usr/bin/env python3
"""Claude Code Stop hook — log session to evo-server when agent finishes.

Reads JSON from stdin: {session_id, transcript_path, relevant_output, ...}
Parses transcript JSONL to extract: tool usage, file edits, bash commands,
errors, and generates real skills.
"""
import sys
import json
import os
import re
import urllib.request
import tempfile
from datetime import datetime
from collections import Counter

SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")
API_KEY = os.getenv("EVO_API_KEY", "")
TRACKER_FILE = os.path.join(tempfile.gettempdir(), "evo_changed_files.json")


def api(method, path, data=None):
    url = f"{SERVER}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"},
    )
    if API_KEY:
        req.add_header("Authorization", f"Bearer {API_KEY}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False}


def parse_transcript(transcript_path):
    """Parse Claude Code JSONL transcript to extract session intelligence.

    Digs into tool call `input` fields to extract real knowledge:
    - Bash commands: deployment patterns, test commands, git workflows
    - Edit calls: what files changed and what kind of changes
    - Write calls: what new modules/files were created
    - Read calls: what files were examined (domain context)
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return None

    result = {
        "tool_counts": {},
        "files_edited": [],
        "files_written": [],
        "bash_commands": [],
        "bash_patterns": [],      # normalized command roots with context
        "edit_details": [],       # (file, old_preview, new_preview)
        "write_details": [],      # (file, content_preview)
        "read_files": [],         # files that were read
        "errors_encountered": [],
        "user_messages": [],
        "total_tool_calls": 0,
    }

    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = d.get("type", "")

                # User messages — extract intent
                if msg_type == "user":
                    msg = d.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > 5:
                        result["user_messages"].append(content[:200])

                # Assistant messages — extract tool calls
                if msg_type == "assistant":
                    msg = d.get("message", {})
                    content = msg.get("content", [])
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_use":
                            continue

                        name = block.get("name", "")
                        inp = block.get("input", {})
                        result["tool_counts"][name] = result["tool_counts"].get(name, 0) + 1
                        result["total_tool_calls"] += 1

                        # ── Bash: extract command + normalize root ──
                        if name == "Bash":
                            cmd = inp.get("command", "")
                            if cmd and len(cmd) > 3:
                                result["bash_commands"].append(cmd[:200])
                                # Extract root command and meaningful subcommands
                                root = cmd.split()[0] if cmd.split() else ""
                                # Skip noise commands
                                if root not in ("cd", "echo", "ls", "cat", "pwd", "mkdir", ""):
                                    result["bash_patterns"].append({
                                        "root": root,
                                        "full": cmd[:150],
                                    })

                        # ── Write: extract new file content preview ──
                        elif name == "Write":
                            fp = inp.get("file_path", "")
                            if fp:
                                result["files_edited"].append(fp)
                                result["files_written"].append(fp)
                                content_preview = inp.get("content", "")[:300]
                                result["write_details"].append({
                                    "file": fp,
                                    "preview": content_preview,
                                })

                        # ── Edit: extract what changed ──
                        elif name == "Edit":
                            fp = inp.get("file_path", "")
                            if fp:
                                result["files_edited"].append(fp)
                                old_str = inp.get("old_string", "")[:150]
                                new_str = inp.get("new_string", "")[:150]
                                result["edit_details"].append({
                                    "file": fp,
                                    "old": old_str,
                                    "new": new_str,
                                })

                        # ── Read: track examined files ──
                        elif name == "Read":
                            fp = inp.get("file_path", "")
                            if fp:
                                result["read_files"].append(fp)
                            # Errors from read attempts
                            if "error" in str(inp).lower():
                                result["errors_encountered"].append(str(inp)[:100])

    except (IOError, OSError):
        return None

    return result


def infer_domain(changed_files):
    """Infer domain from changed file extensions/paths."""
    exts = {}
    for f in changed_files:
        ext = f.rsplit(".", 1)[-1] if "." in f else ""
        exts[ext] = exts.get(ext, 0) + 1

    if not exts:
        return "general"

    top_ext = max(exts, key=exts.get)
    ext_map = {
        "py": "python", "rs": "rust", "go": "go",
        "ts": "typescript", "tsx": "react", "jsx": "react",
        "js": "javascript", "vue": "frontend",
        "sql": "data", "yml": "devops", "yaml": "devops",
        "json": "config", "toml": "config",
    }
    return ext_map.get(top_ext, "general")


def extract_skills(transcript_data, changed_files, outcome):
    """Extract meaningful skills from parsed transcript data.

    Produces REAL knowledge from tool input fields:
    - Deployment patterns from Bash commands
    - What new modules were created (from Write content)
    - What changes were made (from Edit old/new)
    - Framework-specific patterns
    - File organization patterns
    """
    skills = []
    if not transcript_data:
        return skills

    domain = infer_domain(changed_files)
    tool_counts = transcript_data.get("tool_counts", {})
    bash_patterns = transcript_data.get("bash_patterns", [])
    files_edited = transcript_data.get("files_edited", [])
    files_written = transcript_data.get("files_written", [])
    edit_details = transcript_data.get("edit_details", [])
    write_details = transcript_data.get("write_details", [])
    user_msgs = transcript_data.get("user_messages", [])

    # ── 1. Deployment / DevOps patterns from Bash ──
    deploy_keywords = {
        "scp": "file transfer",
        "ssh": "remote execution",
        "systemctl": "service management",
        "docker": "containerization",
        "nginx": "web server config",
        "git push": "code push",
        "git commit": "version control",
        "pip install": "python dependency",
        "npm install": "js dependency",
        "pytest": "python testing",
        "jest": "js testing",
        "curl": "api testing",
        "python -m uvicorn": "server startup",
        "python -m fastapi": "fastapi usage",
    }
    found_deploy = {}
    for bp in bash_patterns:
        full = bp["full"].lower()
        for kw, label in deploy_keywords.items():
            if kw in full:
                if label not in found_deploy:
                    found_deploy[label] = bp["full"]
    for label, example in list(found_deploy.items())[:3]:
        skills.append({
            "name": f"deploy_{label.replace(' ', '_')[:30]}",
            "domain": domain,
            "pattern": f"Deployment: {label} -- used: {example[:120]}",
            "weight": 0.9,
        })

    # ── 2. New modules created (from Write content) ──
    for wd in write_details[:3]:
        fp = wd["file"]
        preview = wd["preview"]
        basename = os.path.basename(fp)
        # Detect what was created
        if "class " in preview:
            cls_match = re.search(r"class\s+(\w+)", preview)
            cls_name = cls_match.group(1) if cls_match else basename
            skills.append({
                "name": f"created_class_{cls_name[:25]}",
                "domain": domain,
                "pattern": f"Created class {cls_name} in {basename}",
                "weight": 1.0,
            })
        elif "def " in preview:
            func_match = re.search(r"def\s+(\w+)", preview)
            func_name = func_match.group(1) if func_match else basename
            skills.append({
                "name": f"created_func_{func_name[:25]}",
                "domain": domain,
                "pattern": f"Created function {func_name} in {basename}",
                "weight": 0.9,
            })
        elif "router" in preview.lower() or "app." in preview.lower():
            skills.append({
                "name": f"created_router_{basename[:25]}",
                "domain": domain,
                "pattern": f"Created API router in {basename}",
                "weight": 0.9,
            })
        elif "import" in preview:
            skills.append({
                "name": f"created_module_{basename[:25]}",
                "domain": domain,
                "pattern": f"Created new module {basename}",
                "weight": 0.8,
            })

    # ── 3. Edit patterns — what kind of changes were made ──
    edit_categories = Counter()
    edit_examples = {}
    for ed in edit_details[:20]:
        new_text = ed["new"]
        old_text = ed["old"]
        basename = os.path.basename(ed["file"])

        if "import" in new_text and "import" not in old_text:
            edit_categories["added_import"] += 1
            edit_examples["added_import"] = f"Added import in {basename}"
        elif "def " in new_text and "def " not in old_text:
            edit_categories["added_function"] += 1
            edit_examples["added_function"] = f"Added function in {basename}"
        elif "class " in new_text and "class " not in old_text:
            edit_categories["added_class"] += 1
            edit_examples["added_class"] = f"Added class in {basename}"
        elif "Body(" in new_text:
            edit_categories["fixed_body_annotation"] += 1
            edit_examples["fixed_body_annotation"] = f"Fixed Body() annotation in {basename}"
        elif "@router" in new_text:
            edit_categories["added_route"] += 1
            edit_examples["added_route"] = f"Added route in {basename}"
        elif "return" in new_text and "return" not in old_text:
            edit_categories["added_return"] += 1
            edit_examples["added_return"] = f"Added return statement in {basename}"

    for cat, count in edit_categories.most_common(3):
        if count >= 2:
            skills.append({
                "name": f"edit_pattern_{cat[:30]}",
                "domain": domain,
                "pattern": f"Repeated edit pattern: {cat} ({count}x) -- {edit_examples.get(cat, '')}",
                "weight": 0.8,
            })

    # ── 4. Bash command clusters (not just roots, but meaningful combos) ──
    cmd_roots = [bp["root"] for bp in bash_patterns]
    cmd_counts = Counter(cmd_roots)
    for cmd, count in cmd_counts.most_common(3):
        if count >= 2 and cmd not in ("cd", "echo", "ls", "cat", "pwd", "mkdir"):
            # Get a sample full command for context
            sample = next((bp["full"] for bp in bash_patterns if bp["root"] == cmd), cmd)
            skills.append({
                "name": f"bash_{cmd.replace('/', '_').replace('-', '_')[:30]}",
                "domain": domain,
                "pattern": f"Repeated: {cmd} ({count}x) -- e.g. {sample[:100]}",
                "weight": 0.7,
            })

    # ── 5. Framework detection from all sources ──
    frameworks = set()
    all_text = " ".join([
        bp["full"] for bp in bash_patterns
    ] + [wd.get("preview", "") for wd in write_details]).lower()

    for fw in ("fastapi", "flask", "django", "react", "vue", "express",
                "gin", "axum", "actix", "uvicorn", "pytest", "jest",
                "apscheduler", "httpx", "pydantic", "sqlalchemy"):
        if fw in all_text:
            frameworks.add(fw)

    for fw in list(frameworks)[:3]:
        skills.append({
            "name": f"framework_{fw}",
            "domain": domain,
            "pattern": f"Framework used: {fw}",
            "weight": 0.9,
        })

    # ── 6. Session summary (always create) ──
    file_count = len(set(files_edited))
    write_count = len(files_written)
    edit_count = len(edit_details)
    bash_count = len(bash_patterns)

    if file_count > 0:
        basenames = list(set(os.path.basename(f) for f in files_edited))[:5]
        skills.append({
            "name": f"session_{domain}_{file_count}files",
            "domain": domain,
            "pattern": f"Session: {file_count} files ({', '.join(basenames)}), {write_count} new, {edit_count} edits, {bash_count} commands",
            "weight": 1.0 if outcome == "success" else 0.5,
        })

    # ── 7. Error recovery ──
    if outcome == "success" and transcript_data.get("errors_encountered"):
        skills.append({
            "name": f"error_recovery_{domain}",
            "domain": domain,
            "pattern": f"Recovered from {len(transcript_data['errors_encountered'])} errors",
            "weight": 0.8,
        })

    # Deduplicate by name prefix
    seen = set()
    unique = []
    for s in skills:
        key = s["name"][:25]
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique[:10]  # Max 10 skills per session (was 8)


def main():
    # Read stdin — Claude Code passes JSON
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    session_id = data.get("session_id", "unknown")
    interaction_type = data.get("interaction_type", "chat")
    relevant_output = data.get("relevant_output", "")
    transcript_path = data.get("transcript_path", "")

    # Read tracked changed files
    changed_files = []
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f:
                changed_files = json.load(f)
            os.remove(TRACKER_FILE)
        except Exception:
            pass

    # Parse transcript for rich data
    transcript_data = parse_transcript(transcript_path)

    # If no transcript, fall back to relevant_output
    if not transcript_data and relevant_output:
        transcript_data = {
            "tool_counts": {},
            "files_edited": changed_files,
            "files_written": [],
            "bash_commands": [],
            "bash_patterns": [],
            "edit_details": [],
            "write_details": [],
            "read_files": [],
            "errors_encountered": [],
            "user_messages": [relevant_output[:200]],
            "total_tool_calls": 0,
        }

    # Determine outcome
    outcome = "success"
    all_text = (relevant_output + " ".join(
        transcript_data.get("user_messages", []) if transcript_data else []
    )).lower() if relevant_output or transcript_data else ""
    if any(k in all_text for k in ("error", "failed", "exception", "traceback")):
        outcome = "failure"
    elif any(k in all_text for k in ("partial", "incomplete")):
        outcome = "partial"

    domain = infer_domain(changed_files)
    now = datetime.now()

    # Build rich goal summary from transcript
    if transcript_data and transcript_data.get("user_messages"):
        # Use first user message as goal
        first_msg = transcript_data["user_messages"][0][:100]
        goal = first_msg
    else:
        goal = f"Claude Code {interaction_type} on {domain}"

    # Build lessons from transcript summary
    lessons_parts = []
    if transcript_data:
        fe = len(set(transcript_data.get("files_edited", [])))
        fw = len(transcript_data.get("files_written", []))
        bc = len(transcript_data.get("bash_patterns", []))
        ed = len(transcript_data.get("edit_details", []))
        lessons_parts.append(f"{fe} files touched, {fw} new, {ed} edits, {bc} commands")
        # Mention frameworks if detected
        frameworks = set()
        for bp in transcript_data.get("bash_patterns", []):
            for fw_name in ("fastapi", "pytest", "uvicorn", "docker", "nginx"):
                if fw_name in bp.get("full", "").lower():
                    frameworks.add(fw_name)
        if frameworks:
            lessons_parts.append(f"Frameworks: {', '.join(sorted(frameworks))}")
    if changed_files:
        basenames = [os.path.basename(f) for f in changed_files[:5]]
        lessons_parts.append(f"Modified: {', '.join(basenames)}")
    lessons = "; ".join(lessons_parts)

    # Log session
    result = api("POST", "/session/log", {
        "session_id": session_id,
        "tool": "claude_code",
        "goal": goal,
        "outcome": outcome,
        "lessons": lessons,
        "changed_files": changed_files,
        "duration_sec": 0,
    })

    # Extract and save skills to /skills/ endpoint
    skills = extract_skills(transcript_data, changed_files, outcome)
    skills_saved = 0
    for skill in skills:
        skill_result = api("POST", "/skills/", {
            "name": skill["name"],
            "domain": skill["domain"],
            "pattern": skill["pattern"],
            "weight": skill["weight"],
            "source": "session",
        })
        if skill_result.get("ok"):
            skills_saved += 1

    if result.get("ok"):
        msg = (
            f"[evo] Session {session_id[:12]} logged "
            f"({outcome}, {len(changed_files)} files, "
            f"{skills_saved} skills extracted)"
        )
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    main()
