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


def _is_noise_message(msg):
    """Filter out system output, console dumps, and non-user-intent messages."""
    text = msg.lower().strip()
    # System / wrapper messages
    noise_prefixes = [
        "<local-command-caveat>",
        "<system-reminder>",
        "<command-name>",
        "note:",
        "warning:",
        "error:",
    ]
    for p in noise_prefixes:
        if text.startswith(p):
            return True
    # Cloud console output (instance info, UUIDs, etc.)
    if any(k in text for k in ("实例id", "实例规格", "uuid", "instance id", "instance type")):
        return True
    # Dashboard / cloud platform content (Workers, settings pages)
    if any(k in text for k in ("workers 日志", "workers 跟踪", "workers 日",
                                 "可观察性", "仪表板", "定义环境变量", "runtime variables",
                                 "observability", "configure api tokens")):
        return True
    # Very short or just numbers/symbols (Chinese chars are denser, use 8)
    if len(text) < 8:
        return True
    # Looks like raw output: no spaces AND no CJK characters (pure ASCII/technical)
    has_cjk = bool(re.search(r"[一-鿿]", text))
    if " " not in text and not has_cjk:
        return True
    # Dashboard / web page content: long + structured labels + no conversational markers
    # Real user decisions are short, conversational, contain action verbs
    if len(text) > 120:
        # Count conversational signals (I want, let's, do, should, prefer, etc.)
        convo_words = ["i ", "let's", "we ", "you ", "do ", "should", "can ",
                       "want", "need", "help", "用", "我", "你", "帮", "做"]
        has_convo = any(w in text for w in convo_words)
        # Count structural indicators (labels, colons, bullets)
        struct_lines = text.count("\n")
        has_structure = struct_lines >= 3 and ("：" in text or ":" in text)
        if has_structure and not has_convo:
            return True
    return False


def _is_credential_content(text):
    """Block API keys, tokens, passwords, secrets from being stored as memories."""
    lower = text.lower()
    # Keyword-based detection
    secret_keywords = [
        "api_key", "api-key", "apikey", "api key",
        "token", "secret", "password", "passwd", "pwd",
        "credential", "auth_token", "access_key",
        "private_key", "ssh_key", "ssh key",
    ]
    for kw in secret_keywords:
        if kw in lower:
            # Double-check: only block if there's also a long alphanumeric string nearby
            if re.search(r"[A-Za-z0-9_\-]{20,}", text):
                return True
    # Pattern: long hex/base64-looking strings (≥32 chars) that look like keys
    if re.search(r"\b[A-Fa-f0-9]{32,}\b", text):
        return True
    # Pattern: strings starting with common key prefixes
    if re.search(r"\b(AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36})", text):
        return True
    return False


def extract_memories(transcript_data, changed_files, outcome, domain):
    """Extract key memories from a session for cross-session recall.

    Returns list of {category, content, domain, confidence}.
    Max 5 memories per session.
    """
    if not transcript_data:
        return []

    memories = []

    # 1. Decisions — from user messages mentioning choices/preferences
    #    Only keep real user intent, filter out system/console noise and credentials
    user_msgs = transcript_data.get("user_messages", [])
    decision_keywords = ["用", "选择", "决定", "偏好", "不要", "别用",
                         "prefer", "use", "choose", "don't", "avoid"]
    for msg in user_msgs:
        if _is_noise_message(msg):
            continue
        if _is_credential_content(msg):
            continue
        text = msg.lower()
        for kw in decision_keywords:
            if kw in text and len(msg) > 15:
                memories.append({
                    "category": "decision",
                    "content": msg[:200],
                    "domain": domain,
                    "confidence": 0.7,
                })
                break
        if len(memories) >= 2:
            break

    # 2. Lessons — from errors that were fixed
    errors = transcript_data.get("errors_encountered", [])
    if errors and outcome == "success":
        for err in errors[:2]:
            err_text = err if isinstance(err, str) else str(err)
            # Skip noise errors and credential content
            if len(err_text) > 30 and not _is_noise_message(err_text) and not _is_credential_content(err_text):
                memories.append({
                    "category": "lesson",
                    "content": f"Error encountered and resolved: {err_text[:200]}",
                    "domain": domain,
                    "confidence": 0.8,
                })
        if len(memories) >= 4:
            pass  # already have enough

    # 3. Context — session summary as context memory
    file_count = len(changed_files)
    if file_count >= 3:
        basenames = [os.path.basename(f) for f in changed_files[:5]]
        memories.append({
            "category": "context",
            "content": f"Session modified {file_count} files: {', '.join(basenames)}",
            "domain": domain,
            "confidence": 0.6,
        })

    # Deduplicate by content prefix
    seen = set()
    unique = []
    for m in memories:
        key = m["content"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return unique[:5]


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

    # ── Extract memories for cross-session recall ──
    memories = extract_memories(transcript_data, changed_files, outcome, domain)
    memories_saved = 0
    for mem in memories:
        mem_result = api("POST", "/memories/", {
            "session_id": session_id,
            "category": mem["category"],
            "content": mem["content"],
            "domain": mem["domain"],
            "confidence": mem["confidence"],
        })
        if mem_result.get("ok"):
            memories_saved += 1

    if memories_saved:
        print(f"[evo] {memories_saved} memories saved", file=sys.stderr)

    # Log prompt outcome for auto-tuning
    prompt_type = domain  # use domain as prompt_type
    strategy = ""
    if transcript_data:
        # Infer strategy from tool usage
        tool_counts = transcript_data.get("tool_counts", {})
        if tool_counts.get("Bash", 0) > 5:
            strategy = "bash_heavy"
        elif tool_counts.get("Edit", 0) > 3:
            strategy = "iterative_edit"
        elif tool_counts.get("Write", 0) > 2:
            strategy = "new_files"
        else:
            strategy = "mixed"

    api("POST", "/prompts/log", {
        "session_id": session_id,
        "prompt_type": prompt_type,
        "prompt_text": goal[:200] if goal else "",
        "strategy": strategy,
        "outcome": outcome,
        "duration_sec": 0,
    })


if __name__ == "__main__":
    main()
