#!/usr/bin/env python3
"""EVO Hook — unified CLI hook for Claude Code and Codex.

Usage:
  evo_hook.py pre  <tool> <scenario>    # Before session: recall relevant skills
  evo_hook.py post <tool> <session_id> <outcome> [lesson]  # After session: log + update
  evo_hook.py status                    # Show server status
"""
import sys
import json
import urllib.request
import urllib.error

SERVER = "http://119.45.204.198"
API_KEY = ""  # Set in .env or leave empty


def api(method: str, path: str, data: dict = None) -> dict:
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
    except urllib.error.URLError as e:
        return {"ok": False, "message": str(e)}


def cmd_pre(tool: str, scenario: str):
    """Recall relevant skills before coding session."""
    result = api("POST", "/skills/recall", {"scenario": scenario, "limit": 5})
    if result.get("ok") and result.get("data"):
        print(f"[evo] Relevant skills for '{scenario}':")
        for s in result["data"]:
            print(f"  - {s['name']} [{s['domain']}] w={s['weight']:.2f}")
            if s.get("pattern"):
                print(f"    {s['pattern'][:120]}")
    else:
        print(f"[evo] No relevant skills found for '{scenario}'")

    # Also query memory
    if scenario:
        mem = api("POST", "/memory/query", {"keyword": scenario, "limit": 5})
        if mem.get("ok") and mem.get("data"):
            print(f"\n[evo] Related memories:")
            for m in mem["data"][:3]:
                name = m.get("name", m.get("rule_key", ""))
                print(f"  - {name}")


def cmd_post(tool: str, session_id: str, outcome: str, lesson: str = ""):
    """Log session result and update skill weights."""
    # Log session
    result = api("POST", "/session/log", {
        "session_id": session_id,
        "tool": tool,
        "goal": lesson or f"{tool} session",
        "outcome": outcome,
        "lessons": lesson,
    })
    if result.get("ok"):
        print(f"[evo] Session {session_id} logged ({outcome})")
    else:
        print(f"[evo] Failed to log session: {result.get('message')}")

    # Update skills with success/failure
    skills = api("GET", "/skills/", None)
    if skills.get("ok") and skills.get("data"):
        success = outcome == "success"
        for s in skills["data"][:3]:
            api("POST", "/skills/update", {
                "skill_key": s["skill_key"],
                "success": success,
            })


def cmd_status():
    """Show server status."""
    result = api("GET", "/health", None)
    if result.get("ok"):
        stats = result.get("stats", {})
        print(f"[evo] Server status:")
        print(f"  Skills: {stats.get('skills', 0)}")
        print(f"  Patterns: {stats.get('patterns', 0)}")
        print(f"  Sessions: {stats.get('sessions', 0)}")
        print(f"  Pending evolutions: {stats.get('evolutions', 0)}")
    else:
        print(f"[evo] Server unavailable: {result.get('message')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "pre":
        cmd_pre(sys.argv[2] if len(sys.argv) > 2 else "general",
                sys.argv[3] if len(sys.argv) > 3 else "")
    elif cmd == "post":
        cmd_post(sys.argv[2] if len(sys.argv) > 2 else "unknown",
                 sys.argv[3] if len(sys.argv) > 3 else "session-001",
                 sys.argv[4] if len(sys.argv) > 4 else "success",
                 sys.argv[5] if len(sys.argv) > 5 else "")
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
