#!/usr/bin/env python3
"""PostToolUse hook: auto-format Python files with ruff after Write/Edit."""
import json, sys, subprocess, os

def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit"):
        return

    # Get file path from tool input
    inp = data.get("tool_input", {})
    path = inp.get("file_path") or inp.get("path") or ""
    if not path or not path.endswith(".py"):
        return
    if not os.path.exists(path):
        return

    try:
        r = subprocess.run(["ruff", "format", path], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            print(f"ruff: {path}", file=sys.stderr)
    except Exception:
        pass

if __name__ == "__main__":
    main()
