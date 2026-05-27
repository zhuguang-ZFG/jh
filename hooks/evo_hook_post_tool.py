#!/usr/bin/env python3
"""Claude Code PostToolUse hook — track file changes + periodic session flush.

Reads JSON from stdin with tool_name, tool_input, tool_result.
Tracks changed files across the session via a temp file.
Periodically flushes accumulated skills/memories to evo-server (every 5 min).
"""
import sys
import json
import os
import time
import glob
import tempfile

from evo_hook_common import (
    api, parse_transcript, infer_domain, extract_skills, extract_memories,
    read_changed_files, get_session_id, TRACKER_FILE,
)

FLUSH_INTERVAL = 300  # seconds (5 minutes)
FLUSH_STATE_FILE = os.path.join(tempfile.gettempdir(), "evo_flush_state.json")


def _find_transcript():
    """Find the most recent Claude Code transcript JSONL file."""
    candidates = []

    # Common transcript locations
    home = os.path.expanduser("~")
    for pattern in [
        os.path.join(home, ".claude", "projects", "*", "sessions", "*", "transcript.jsonl"),
        os.path.join(home, ".claude", "sessions", "*", "transcript.jsonl"),
        os.path.join(tempfile.gettempdir(), "claude*", "transcript.jsonl"),
    ]:
        candidates.extend(glob.glob(pattern))

    if not candidates:
        return None

    # Return most recently modified
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def _should_flush():
    """Check if enough time has passed since last flush."""
    if not os.path.exists(FLUSH_STATE_FILE):
        return True
    try:
        with open(FLUSH_STATE_FILE) as f:
            state = json.load(f)
        last_flush = state.get("last_flush", 0)
        return (time.time() - last_flush) >= FLUSH_INTERVAL
    except Exception:
        return True


def _record_flush():
    """Record that a flush just happened."""
    try:
        with open(FLUSH_STATE_FILE, "w") as f:
            json.dump({"last_flush": time.time()}, f)
    except Exception:
        pass


def _do_flush():
    """Extract session data and upload to evo-server."""
    session_id = get_session_id()
    changed_files = read_changed_files()
    domain = infer_domain(changed_files) if changed_files else "general"

    # Try to find and parse transcript
    transcript_path = _find_transcript()
    transcript_data = parse_transcript(transcript_path) if transcript_path else None

    if not transcript_data and not changed_files:
        return  # Nothing to flush

    # Determine outcome (optimistic during session)
    outcome = "success"

    # Extract skills
    skills = extract_skills(transcript_data, changed_files, outcome)

    # Extract memories (local only during periodic flush — no LLM call for speed)
    memories = extract_memories(transcript_data, changed_files, outcome, domain)

    # Build goal from transcript
    goal = ""
    if transcript_data and transcript_data.get("user_messages"):
        goal = transcript_data["user_messages"][0][:100]
    else:
        goal = f"Claude Code session on {domain}"

    # Call flush endpoint
    result = api("POST", "/session/flush", {
        "session_id": session_id,
        "goal": goal,
        "skills": [{
            "name": s["name"],
            "domain": s["domain"],
            "pattern": s["pattern"],
            "weight": s["weight"],
            "source": "session",
        } for s in skills],
        "memories": [{
            "category": m["category"],
            "content": m["content"],
            "domain": m["domain"],
            "confidence": m["confidence"],
        } for m in memories],
        "changed_files": changed_files,
        "domain": domain,
    })

    if result and result.get("ok"):
        print(f"[evo] Periodic flush: {len(skills)} skills, {len(memories)} memories",
              file=sys.stderr)


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
        if any(k in cmd for k in ("git add", "git commit", "mkdir", "rm ", "mv ")):
            changed_files.append(f"bash:{cmd[:80]}")

    # Save tracker (keep last 50 entries)
    try:
        with open(TRACKER_FILE, "w") as f:
            json.dump(changed_files[-50:], f)
    except Exception:
        pass

    # Periodic flush check
    if _should_flush() and changed_files:
        try:
            _do_flush()
            _record_flush()
        except Exception:
            pass  # non-critical, never block the hook


if __name__ == "__main__":
    main()
