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
    """Parse Claude Code JSONL transcript to extract session intelligence."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None

    result = {
        "tool_counts": {},
        "files_edited": [],
        "bash_commands": [],
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

                        # File edits
                        if name in ("Write", "Edit"):
                            fp = inp.get("file_path", "")
                            if fp:
                                result["files_edited"].append(fp)

                        # Bash commands — extract what was actually run
                        if name == "Bash":
                            cmd = inp.get("command", "")
                            if cmd and len(cmd) > 3:
                                # Strip long args, keep first 120 chars
                                result["bash_commands"].append(cmd[:120])

                        # Errors from tool results
                        if name == "Read" and "error" in str(inp).lower():
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
    """Extract meaningful skills from parsed transcript data."""
    skills = []
    if not transcript_data:
        return skills

    domain = infer_domain(changed_files)
    tool_counts = transcript_data.get("tool_counts", {})
    bash_cmds = transcript_data.get("bash_commands", [])
    files_edited = transcript_data.get("files_edited", [])
    user_msgs = transcript_data.get("user_messages", [])
    total = transcript_data.get("total_tool_calls", 0)

    # 1. High-level session summary skill (always create)
    file_count = len(set(files_edited))
    bash_count = len(bash_cmds)
    edit_count = tool_counts.get("Edit", 0) + tool_counts.get("Write", 0)

    if file_count > 0:
        # Extract what files were worked on
        basenames = list(set(
            os.path.basename(f) for f in files_edited
        ))[:5]
        skills.append({
            "name": f"session_{domain}_{file_count}files",
            "domain": domain,
            "pattern": f"Worked on {file_count} files ({', '.join(basenames)}): {edit_count} edits, {bash_count} commands",
            "weight": 1.0 if outcome == "success" else 0.5,
        })

    # 2. Tool usage patterns — what tools were heavily used
    for tool, count in tool_counts.items():
        if count >= 5 and tool not in ("Read", "TaskUpdate", "TaskCreate"):
            skills.append({
                "name": f"tool_pattern_{tool.lower()}",
                "domain": domain,
                "pattern": f"Used {tool} {count} times in session",
                "weight": 0.8,
            })

    # 3. Bash command patterns — extract repeated commands
    if bash_cmds:
        # Normalize commands (strip args)
        cmd_roots = []
        for cmd in bash_cmds:
            # Get first word (the actual command)
            root = cmd.split()[0] if cmd.split() else ""
            # Skip common noise
            if root in ("cd", "echo", "ls", "cat", "pwd", ""):
                continue
            cmd_roots.append(root)

        cmd_counts = Counter(cmd_roots)
        for cmd, count in cmd_counts.most_common(3):
            if count >= 2:
                skills.append({
                    "name": f"bash_pattern_{cmd.replace('/', '_').replace('-', '_')[:30]}",
                    "domain": domain,
                    "pattern": f"Repeated command: {cmd} ({count}x)",
                    "weight": 0.7,
                })

    # 4. Framework/library detection from bash commands
    frameworks = set()
    for cmd in bash_cmds:
        cmd_lower = cmd.lower()
        for fw in ("fastapi", "flask", "django", "react", "vue", "express",
                    "gin", "axum", "actix", "uvicorn", "pytest", "jest"):
            if fw in cmd_lower:
                frameworks.add(fw)
        # pip/npm install detection
        if "pip install" in cmd_lower:
            pkgs = re.findall(r"pip install\s+(\S+)", cmd_lower)
            frameworks.update(pkgs[:3])
        if "npm install" in cmd_lower or "npm i " in cmd_lower:
            frameworks.add("npm")

    for fw in list(frameworks)[:3]:
        skills.append({
            "name": f"framework_{fw}",
            "domain": domain,
            "pattern": f"Used {fw} in this session",
            "weight": 0.9,
        })

    # 5. File clustering — which files are often edited together
    if len(files_edited) >= 3:
        # Group by directory
        dirs = Counter()
        for f in files_edited:
            d = os.path.dirname(f).replace("\\", "/").split("/")[-1]
            if d:
                dirs[d] += 1
        for d, count in dirs.most_common(2):
            if count >= 2:
                skills.append({
                    "name": f"cluster_{d.replace('-', '_').replace('.', '_')[:30]}",
                    "domain": domain,
                    "pattern": f"Active cluster: {d}/ ({count} edits)",
                    "weight": 0.6,
                })

    # 6. Error recovery patterns
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

    return unique[:8]  # Max 8 skills per session


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
            "bash_commands": [],
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
        tc = transcript_data.get("tool_counts", {})
        fe = len(set(transcript_data.get("files_edited", [])))
        bc = len(transcript_data.get("bash_commands", []))
        lessons_parts.append(f"{fe} files, {bc} commands, {transcript_data.get('total_tool_calls', 0)} tool calls")
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
