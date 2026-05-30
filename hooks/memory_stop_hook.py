#!/usr/bin/env python3
"""Stop hook: write session summary to file-based memory for cross-session continuity."""

import sys
import json
import os
from datetime import datetime

MEMORY_DIR = "C:/Users/zhugu/.claude/projects/D--jh/memory"


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    relevant_output = data.get("relevant_output", "")
    if not relevant_output or len(relevant_output) < 50:
        return

    # Extract first user message as topic
    lines = relevant_output.strip().split("\n")
    topic = lines[0][:80] if lines else "session"

    # Build summary
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = f"[{ts}] {topic}\n"

    # Count tool calls if available
    if len(lines) > 1:
        summary += relevant_output[:500]

    # Write to memory
    os.makedirs(MEMORY_DIR, exist_ok=True)
    slug = topic[:30].replace(" ", "-").replace("/", "-").replace("\\", "-")
    slug = "".join(c for c in slug if c.isalnum() or c in "-_")[:30]
    if not slug:
        slug = "session"

    filepath = os.path.join(MEMORY_DIR, f"session_{slug}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(
            f"---\nname: session_{slug}\ndescription: {topic[:100]}\nmetadata:\n  type: project\n---\n\n{summary}\n"
        )

    print(f"[memory] session summary written: {filepath}", file=sys.stderr)


if __name__ == "__main__":
    main()
