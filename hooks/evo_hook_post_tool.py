#!/usr/bin/env python3
"""Claude Code PostToolUse hook — track file changes for session logging.

Reads JSON from stdin with tool_name, tool_input, tool_result.
Tracks changed files across the session via a temp file.
"""
import sys
import json
import os
import tempfile

TRACKER_FILE = os.path.join(tempfile.gettempdir(), "evo_changed_files.json")


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Track file-changing tools
    changed_files = []
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f:
                changed_files = json.load(f)
        except Exception:
            changed_files = []

    if tool_name in ("Write", "Edit"):
        fp = tool_input.get("file_path", "")
        if fp and fp not in changed_files:
            changed_files.append(fp)
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Track git commits, file operations
        if any(k in cmd for k in ("git add", "git commit", "mkdir", "rm ", "mv ")):
            changed_files.append(f"bash:{cmd[:80]}")

    # Save tracker (keep last 50 entries)
    try:
        with open(TRACKER_FILE, "w") as f:
            json.dump(changed_files[-50:], f)
    except Exception:
        pass


if __name__ == "__main__":
    main()
