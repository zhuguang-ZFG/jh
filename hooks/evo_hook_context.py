#!/usr/bin/env python3
"""Claude Code context injection hook — queries VPS for relevant skills/patterns.

PreToolUse (Write|Edit): reads the file being modified, queries VPS /context/query
with inferred keywords, outputs relevant context as hook metadata for Claude.

This closes the loop: accumulated knowledge flows BACK into Claude's context.
"""
import sys
import os
import json
import re
import urllib.request
import tempfile

SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")
CACHE_DIR = os.path.join(tempfile.gettempdir(), "evo_context")
CACHE_TTL = 300  # 5 min cache per keyword set


def api_get(path):
    url = f"{SERVER}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def api_post(path, data):
    url = f"{SERVER}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def extract_context_from_file(file_path):
    """Extract keywords from file path and nearby code for context query."""
    keywords = []

    # 1. File path components
    if file_path:
        parts = re.split(r"[\\/._-]", file_path.lower())
        for p in parts:
            if len(p) >= 3 and p not in ("py", "js", "ts", "tsx", "jsx", "rs", "go",
                                           "src", "lib", "bin", "tmp", "opt", "etc",
                                           "hooks", "server", "data"):
                keywords.append(p)

    # 2. Read first 50 lines of target file for domain hints
    if file_path and os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2000)
            # Extract import names and class/function defs
            imports = re.findall(r"(?:from|import)\s+(\w+)", head)
            keywords.extend([i.lower() for i in imports if len(i) >= 3])
            # Extract class/function names
            defs = re.findall(r"(?:class|def|function|const|let|var)\s+(\w+)", head)
            keywords.extend([d.lower() for d in defs if len(d) >= 3])
        except (IOError, OSError):
            pass

    # Deduplicate, keep top 8
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen and len(k) >= 3:
            seen.add(k)
            unique.append(k)
    return unique[:8]


def get_cache(keywords):
    """Check cache for recent query with same keywords."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = "_".join(sorted(keywords))[:50]
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    if os.path.isfile(cache_file):
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            if time.time() - cached.get("ts", 0) < CACHE_TTL:
                return cached.get("data")
        except Exception:
            pass
    return None


def save_cache(keywords, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = "_".join(sorted(keywords))[:50]
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    try:
        with open(cache_file, "w") as f:
            json.dump({"ts": time.time(), "data": data}, f)
    except Exception:
        pass


def format_context(context_data):
    """Format context data into a concise injection string."""
    if not context_data or not context_data.get("data"):
        return None

    d = context_data["data"]
    lines = []

    skills = d.get("skills", [])
    if skills:
        lines.append("## Relevant Skills")
        for s in skills[:3]:
            lines.append(f"- **{s['name']}** [{s['domain']}]: {s.get('pattern', '')[:120]}")

    patterns = d.get("patterns", [])
    if patterns:
        lines.append("## Relevant Patterns")
        for p in patterns[:3]:
            lines.append(f"- **{p['name']}** [{p['domain']}]: {p.get('description', '')[:120]}")

    rules = d.get("rules", [])
    if rules:
        lines.append("## Rules")
        for r in rules[:2]:
            lines.append(f"- {r[:120]}")

    tips = d.get("quality_tips", [])
    if tips:
        lines.append("## Quality Tips")
        for t in tips[:2]:
            lines.append(f"- {t}")

    insights = d.get("session_insights", [])
    if insights:
        lines.append("## Session Insights")
        for i in insights[:2]:
            lines.append(f"- {i[:150]}")

    if not lines:
        return None

    return "\n".join(lines)


import time

def main():
    # Read stdin — Claude Code passes tool input JSON
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    file_path = (
        data.get("file_path")
        or data.get("input", {}).get("file_path")
    )

    if not file_path:
        return

    # Extract keywords from file context
    keywords = extract_context_from_file(file_path)
    if not keywords:
        return

    # Check cache
    cached = get_cache(keywords)
    if cached:
        context_text = format_context({"data": cached})
    else:
        # Query VPS
        result = api_post("/context/query", {
            "task": " ".join(keywords),
            "limit": 5,
        })
        if result and result.get("ok"):
            save_cache(keywords, result.get("data", {}))
            context_text = format_context(result)
        else:
            return

    if context_text:
        # Output as hook context — Claude Code will see this
        print(context_text)


if __name__ == "__main__":
    main()
