#!/usr/bin/env python3
"""SessionStart hook — loads cross-session memory on first tool call.

Uses a sentinel file to ensure it only runs once per session.
Fires as PreToolUse on any tool, but exits immediately after first run.
"""
import sys
import os
import json
import time
import tempfile
import urllib.request

SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")
SENTINEL = os.path.join(tempfile.gettempdir(), "evo_session_start_done")


def api_post(path, data):
    url = f"{SERVER}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def format_context(data):
    lines = []

    failures = data.get("failures", [])
    if failures:
        lines.append("## Known Failures (Avoid)")
        for f in failures[:3]:
            fix = f.get("fix_suggestion", "")
            lines.append(f"- {f['error_type']}: {f['description'][:100]}")
            if fix:
                lines.append(f"  Fix: {fix[:80]}")

    skills = data.get("skills", [])
    if skills:
        lines.append("## Relevant Skills")
        for s in skills[:5]:
            lines.append(f"- {s['name']} [{s['domain']}]: {s.get('pattern', '')[:80]}")

    memories = data.get("memories", [])
    if memories:
        lines.append("## Past Memories")
        for m in memories[:5]:
            content = m.get("content", "")[:100]
            cat = m.get("category", "")
            lines.append(f"- [{cat}] {content}")

    best = data.get("best_practices", [])
    if best:
        lines.append("## Best Practices")
        for bp in best[:3]:
            pct = int(bp.get("ema_rate", 0) * 100)
            lines.append(f"- [{bp.get('prompt_type', '')}] {bp.get('strategy', '')[:60]} ({pct}% success)")

    if not lines:
        return None
    return "\n".join(lines)


def main():
    # Only run once per session
    if os.path.exists(SENTINEL):
        try:
            with open(SENTINEL) as f:
                ts = float(f.read().strip())
            # Reset if older than 4 hours (new session)
            if time.time() - ts < 14400:
                return
        except Exception:
            pass

    # Mark as done immediately to prevent re-entry
    try:
        with open(SENTINEL, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    # Get task hint from recent git log
    task_hint = ""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline", "-3", "--no-decorate"],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if result.returncode == 0 and result.stdout.strip():
            task_hint = result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    if not task_hint:
        task_hint = "general development"

    batch = api_post("/context/batch", {
        "task": task_hint,
        "limit": 5,
        "include": ["skills", "patterns", "failures", "memories", "briefing", "best_practices"],
    })

    if not batch or not batch.get("ok"):
        return

    data = batch.get("data", {})
    context = format_context(data)
    if context:
        print(context)
        # Phase 3: accumulate injection for effect tracking
        _accumulate_injection(data)


def _accumulate_injection(data):
    """Accumulate injection data for later flush with real session_id."""
    sections = []
    if data.get("failures"):
        sections.append("failures")
    if data.get("skills"):
        sections.append("skills")
    if data.get("patterns"):
        sections.append("patterns")
    if data.get("memories"):
        sections.append("memories")
    if data.get("best_practices"):
        sections.append("best_practices")

    if not sections:
        return

    try:
        import sys as _sys
        parent = os.path.dirname(os.path.abspath(__file__))
        if parent not in _sys.path:
            _sys.path.insert(0, parent)
        from evo_hook_common import record_injection
        record_injection(
            sections=sections,
            failure_count=len(data.get("failures", [])),
            skill_count=len(data.get("skills", [])),
            pattern_count=len(data.get("patterns", [])),
            has_fix_code=any(f.get("fix_code") for f in data.get("failures", [])),
        )
    except ImportError:
        pass


if __name__ == "__main__":
    main()
