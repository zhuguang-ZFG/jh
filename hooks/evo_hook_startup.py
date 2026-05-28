#!/usr/bin/env python3
"""Session startup hook — loads cross-session memory from evo-server.

Called at the start of each Claude Code session to inject accumulated
knowledge (skills, patterns, failures, memories) into context.

Usage: python evo_hook_startup.py [task_hint]
  task_hint: optional text about what the session will work on
"""
import sys
import os
import json
import urllib.request

SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")


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
    except Exception as e:
        return {"ok": False, "error": str(e)}


def format_startup_context(data):
    """Format batch context into a concise startup briefing."""
    lines = []

    # Effect-based section guidance (same as evo_hook_context.py)
    effect_recs = data.get("effect_recommendations", {})
    deprioritize = {
        s["section"] for s in effect_recs.get("deprioritize", [])
        if s.get("lift", 0) < -0.1
    }
    skip_sections = {
        s["section"] for s in effect_recs.get("deprioritize", [])
        if s.get("lift", 0) < -0.3
    }

    # Failures — highest priority
    if "failures" not in skip_sections:
        failures = data.get("failures", [])
        if failures:
            lines.append("## Known Failures (Avoid)")
            for f in failures[:3]:
                fix = f.get("fix_suggestion", "")
                lines.append(f"- {f['error_type']}: {f['description'][:100]}")
                if fix:
                    lines.append(f"  Fix: {fix[:80]}")

    # Skills — only if NOT strongly deprioritized
    if "skills" not in skip_sections:
        skills = data.get("skills", [])
        skill_limit = 1 if "skills" in deprioritize else 5
        if skills:
            lines.append("## Relevant Skills")
            for s in skills[:skill_limit]:
                lines.append(f"- {s['name']} [{s['domain']}]: {s.get('pattern', '')[:80]}")

    # Memories
    if "memories" not in skip_sections:
        memories = data.get("memories", [])
        if memories:
            lines.append("## Past Memories")
            for m in memories[:5]:
                content = m.get("content", "")[:100]
                cat = m.get("category", "")
                lines.append(f"- [{cat}] {content}")

    # Briefing
    briefing = data.get("briefing", {})
    if briefing.get("warnings"):
        lines.append("## Briefing Warnings")
        for w in briefing["warnings"][:3]:
            lines.append(f"- {w[:100]}")

    # Best practices
    if "best_practices" not in skip_sections:
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
    task_hint = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""

    # If no task hint, try to infer from recent git activity
    if not task_hint:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "log", "--oneline", "-3", "--no-decorate"],
                capture_output=True, text=True, encoding="utf-8",
                timeout=5,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            )
            if result.returncode == 0 and result.stdout.strip():
                task_hint = result.stdout.strip().split("\n")[0]
        except Exception:
            pass

    if not task_hint:
        task_hint = "general development"

    # Query evo-server
    batch = api_post("/context/batch", {
        "task": task_hint,
        "limit": 5,
        "include": ["skills", "patterns", "failures", "memories", "briefing", "best_practices", "predicted_risks"],
    })

    if not batch or not batch.get("ok"):
        error = batch.get("error", "unknown") if batch else "no response"
        print(f"[evo] Failed to load context: {error}", file=sys.stderr)
        sys.exit(0)

    data = batch.get("data", {})
    context = format_startup_context(data)

    if context:
        print(context)
    else:
        print("[evo] No relevant context found for this session.", file=sys.stderr)


if __name__ == "__main__":
    main()
