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
    """Extract skill entries from session output."""
    skills = []
    domain = infer_domain(changed_files)

    if not output or len(output) < 20:
        return skills

    lower = output.lower()

    # Pattern: successful task completion
    success_patterns = [
        (r"(?:created?|added?|implemented?|fixed?|updated?)\s+(.+)", "task_execution"),
        (r"(?:test|tests?)\s+(?:passed|passing|run|running)", "testing"),
        (r"(?:deploy|deployed?|pushed?|shipped?)", "deployment"),
        (r"(?:refactor|refactored?)", "refactoring"),
        (r"(?:bug\s+fix|fixed\s+bug|resolved?\s+issue)", "debugging"),
    ]

    for pattern, skill_type in success_patterns:
        matches = re.findall(pattern, lower)
        for match in matches[:2]:
            skill_text = match.strip()[:100]
            if len(skill_text) > 10:
                skills.append({
                    "name": f"{skill_type}_{skill_text[:30]}",
                    "domain": domain,
                    "pattern": skill_text,
                    "weight": 1.0 if outcome == "success" else 0.5,
                })

    # Pattern: error encountered and resolved
    if outcome == "success" and "error" in lower:
        error_patterns = re.findall(r"(?:error|exception|traceback).{0,100}", lower)
        for ep in error_patterns[:1]:
            skills.append({
                "name": f"error_recovery_{domain}",
                "domain": domain,
                "pattern": f"Resolved: {ep[:80]}",
                "weight": 0.8,
            })

    return skills[:5]  # Max 5 skills per session


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
