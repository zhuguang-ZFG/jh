#!/usr/bin/env python3
"""Claude Code Stop hook — log session to evo-server when agent finishes.

Reads JSON from stdin: {session_id, transcript_path, relevant_output, ...}
Logs to evo-server /session/log endpoint and extracts skills.
"""
import sys
import json
import os
import re
import urllib.request
import tempfile
from datetime import datetime

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


def extract_skills(output, changed_files, outcome):
    """Extract skill entries from session output.

    Captures: file operations, framework usage, tool commands,
    error patterns, and Chinese output patterns.
    """
    skills = []
    domain = infer_domain(changed_files)

    if not output or len(output) < 10:
        return skills

    lower = output.lower()

    # 1. File operation patterns (most reliable)
    file_ops = [
        (r"(?:created?|wrote?|编写|创建)\s+(?:a\s+)?(?:new\s+)?(?:file|脚本|模块|文件)\s*[:\-]?\s*(.+)", "file_creation"),
        (r"(?:edited?|modified?|updated?|修改|更新)\s+(.+)", "file_edit"),
        (r"(?:deleted?|removed?|删除)\s+(.+)", "file_removal"),
    ]
    for pattern, skill_type in file_ops:
        matches = re.findall(pattern, lower)
        for m in matches[:2]:
            text = m.strip()[:100]
            if len(text) > 5:
                skills.append({
                    "name": f"{skill_type}_{text[:30]}",
                    "domain": domain,
                    "pattern": text,
                    "weight": 1.0 if outcome == "success" else 0.5,
                })

    # 2. Framework/library usage
    framework_patterns = [
        (r"(?:used?|using|使用)\s+(fastapi|flask|django|react|vue|express|gin|axum|actix)", "framework_use"),
        (r"(?:installed?|安装)\s+(\w+)", "tool_install"),
        (r"(?:pip|npm|cargo|go)\s+(?:install|add)\s+(\S+)", "package_install"),
    ]
    for pattern, skill_type in framework_patterns:
        matches = re.findall(pattern, lower)
        for m in matches[:2]:
            text = m.strip()[:80]
            if len(text) > 2:
                skills.append({
                    "name": f"{skill_type}_{text[:30]}",
                    "domain": domain,
                    "pattern": text,
                    "weight": 0.9,
                })

    # 3. Task completion (broad patterns)
    task_patterns = [
        (r"(?:完成|done|completed?|finished?|搞定|实现|implement).{0,80}", "task_complete"),
        (r"(?:修复|fix(?:ed|ing)?|解决|resolve).{0,80}", "bug_fix"),
        (r"(?:重构|refactor).{0,80}", "refactoring"),
        (r"(?:部署|deploy).{0,80}", "deployment"),
        (r"(?:测试|test(?:ing|ed)?).{0,80}", "testing"),
        (r"(?:优化|optimiz).{0,80}", "optimization"),
    ]
    for pattern, skill_type in task_patterns:
        matches = re.findall(pattern, lower)
        for m in matches[:1]:
            text = m.strip()[:100]
            if len(text) > 8:
                skills.append({
                    "name": f"{skill_type}_{text[:30]}",
                    "domain": domain,
                    "pattern": text,
                    "weight": 1.0 if outcome == "success" else 0.5,
                })

    # 4. Error recovery (if succeeded despite errors)
    if outcome == "success" and ("error" in lower or "exception" in lower or "错误" in lower):
        error_bits = re.findall(r"(?:error|exception|traceback|错误|异常).{0,80}", lower)
        for eb in error_bits[:1]:
            skills.append({
                "name": f"error_recovery_{domain}",
                "domain": domain,
                "pattern": f"Resolved: {eb[:80]}",
                "weight": 0.8,
            })

    # 5. Changed files as skills (always capture what was worked on)
    if changed_files and outcome == "success":
        for f in changed_files[:3]:
            fname = f.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]  # basename
            if len(fname) > 3:
                skills.append({
                    "name": f"worked_on_{fname[:30]}",
                    "domain": domain,
                    "pattern": f"Modified {fname}",
                    "weight": 0.7,
                })

    # Deduplicate by name prefix
    seen = set()
    unique = []
    for s in skills:
        key = s["name"][:20]
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique[:5]  # Max 5 skills per session


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

    # Read tracked changed files
    changed_files = []
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f:
                changed_files = json.load(f)
            os.remove(TRACKER_FILE)
        except Exception:
            pass

    # Determine outcome from output content
    outcome = "success"
    if relevant_output:
        lower = relevant_output.lower()
        if any(k in lower for k in ("error", "failed", "exception", "traceback")):
            outcome = "failure"
        elif any(k in lower for k in ("partial", "incomplete", "couldn't")):
            outcome = "partial"

    domain = infer_domain(changed_files)
    now = datetime.now()

    # Build lessons summary
    lessons = relevant_output[:500] if relevant_output else ""

    # Log session
    result = api("POST", "/session/log", {
        "session_id": session_id,
        "tool": "claude_code",
        "goal": f"Claude Code {interaction_type} on {domain} ({now.strftime('%Y-%m-%d %H:%M')})",
        "outcome": outcome,
        "lessons": lessons,
        "changed_files": changed_files,
        "duration_sec": 0,
    })

    # Extract and save skills
    skills = extract_skills(relevant_output, changed_files, outcome)
    skills_saved = 0
    for skill in skills:
        skill_result = api("POST", "/memory/add", {
            "name": skill["name"],
            "domain": skill["domain"],
            "pattern": skill["pattern"],
            "description": skill.get("pattern", ""),
            "source": "session",
        })
        if skill_result.get("ok"):
            skills_saved += 1

    if result.get("ok"):
        msg = f"[evo] Session {session_id} logged ({outcome}, {len(changed_files)} files, {skills_saved} skills)"
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    main()
