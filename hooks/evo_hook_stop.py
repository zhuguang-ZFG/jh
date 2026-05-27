#!/usr/bin/env python3
"""Claude Code Stop hook — log session to evo-server when agent finishes.

Reads JSON from stdin: {session_id, transcript_path, relevant_output, ...}
Logs to evo-server /session/log endpoint.
"""
import sys
import json
import os
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
            # Clear tracker for next session
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

    now = datetime.now()

    # Log session
    result = api("POST", "/session/log", {
        "session_id": session_id,
        "tool": "claude_code",
        "goal": f"Claude Code {interaction_type} ({now.strftime('%Y-%m-%d %H:%M')})",
        "outcome": outcome,
        "lessons": relevant_output[:500] if relevant_output else "",
        "changed_files": changed_files,
        "duration_sec": 0,
    })

    if result.get("ok"):
        print(f"[evo] Session {session_id} logged ({outcome}, {len(changed_files)} files)", file=sys.stderr)


if __name__ == "__main__":
    main()
