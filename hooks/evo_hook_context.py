#!/usr/bin/env python3
"""Claude Code context injection hook — queries VPS for ALL relevant knowledge.

PreToolUse (Write|Edit): reads the file being modified, queries VPS for:
- Skills & patterns (existing)
- Failure patterns (NEW: "don't make this mistake again")
- Code conventions (NEW: "follow this project's style")
- Git patterns (NEW: "this repo does it this way")
- CLAUDE.md refresh (NEW: auto-update from VPS)

This is the MAIN knowledge injection point — accumulated learning flows
BACK into Claude's context on every edit.
"""
import sys
import os
import json
import re
import time
import urllib.request
import tempfile

SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")
CACHE_DIR = os.path.join(tempfile.gettempdir(), "evo_context")
CACHE_TTL = 300  # 5 min cache
CLAUDE_MD_INTERVAL = 3600  # refresh CLAUDE.md every hour


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
            imports = re.findall(r"(?:from|import)\s+(\w+)", head)
            keywords.extend([i.lower() for i in imports if len(i) >= 3])
            defs = re.findall(r"(?:class|def|function|const|let|var)\s+(\w+)", head)
            keywords.extend([d.lower() for d in defs if len(d) >= 3])
        except (IOError, OSError):
            pass

    seen = set()
    unique = []
    for k in keywords:
        if k not in seen and len(k) >= 3:
            seen.add(k)
            unique.append(k)
    return unique[:8]


def extract_dependencies(file_path):
    """Extract import dependencies and find related local modules."""
    deps = {"local": [], "external": []}
    if not file_path or not os.path.isfile(file_path):
        return deps

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(8000)
    except (IOError, OSError):
        return deps

    # Find all imports
    imports = re.findall(r"(?:from\s+(\S+)\s+)?import\s+(\S+)", content)
    for mod, name in imports:
        module = mod or name
        # Skip stdlib and common
        if module in ("os", "sys", "json", "re", "time", "hashlib", "logging",
                       "typing", "collections", "subprocess", "pathlib", "io",
                       "tempfile", "urllib", "functools", "abc", "enum",
                       "dataclasses", "contextlib", "asyncio", "copy", "math",
                       "datetime", "textwrap", "shutil", "glob", "ast"):
            continue
        # Local module (has dot or matches project structure)
        if "." in module or os.path.isdir(os.path.join(os.path.dirname(file_path), module.replace(".", "/"))):
            deps["local"].append(module)
        else:
            deps["external"].append(module)

    return deps


def find_test_files(file_path):
    """Find test files related to the current file."""
    if not file_path:
        return []

    tests = []
    basename = os.path.basename(file_path)
    name_no_ext = os.path.splitext(basename)[0]
    dir_name = os.path.dirname(file_path)

    # Common test naming patterns
    candidates = [
        f"test_{name_no_ext}.py",
        f"{name_no_ext}_test.py",
        f"test_{name_no_ext}.js",
        f"{name_no_ext}.test.js",
        f"{name_no_ext}.test.ts",
        f"test_{name_no_ext}.ts",
    ]

    # Search in common test locations
    project_root = dir_name
    for _ in range(5):  # walk up max 5 levels
        for sub in ("tests", "test", "__tests__", "spec"):
            test_dir = os.path.join(project_root, sub)
            if os.path.isdir(test_dir):
                for c in candidates:
                    tp = os.path.join(test_dir, c)
                    if os.path.isfile(tp):
                        tests.append(tp)
        # Also check same directory
        for c in candidates:
            tp = os.path.join(project_root, c)
            if os.path.isfile(tp):
                tests.append(tp)
        project_root = os.path.dirname(project_root)
        if project_root == os.path.dirname(project_root):
            break

    return tests[:3]  # limit


def get_file_language(file_path):
    """Detect file language from extension."""
    if not file_path:
        return ""
    ext = file_path.rsplit(".", 1)[-1] if "." in file_path else ""
    return {"py": "python", "js": "javascript", "ts": "typescript",
            "rs": "rust", "go": "go", "jsx": "react", "tsx": "react"}.get(ext, ext)


def get_cache(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.isfile(cache_file):
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            if time.time() - cached.get("ts", 0) < CACHE_TTL:
                return cached.get("data")
        except Exception:
            pass
    return None


def save_cache(key, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(cache_file, "w") as f:
            json.dump({"ts": time.time(), "data": data}, f)
    except Exception:
        pass


def format_context(all_data):
    """Format all context data into a concise injection string."""
    lines = []

    # 1. Failure warnings (HIGHEST PRIORITY — prevent repeated mistakes)
    failures = all_data.get("failures", [])
    if failures:
        lines.append("## [!] Avoid These Mistakes")
        for f in failures[:3]:
            lines.append(f"- **{f['error_type']}**: {f['description'][:120]}")
            # Prefer concrete fix_code over generic fix_suggestion
            fix = f.get("fix_code") or f.get("fix_suggestion", "")
            if fix:
                fix_type = f.get("fix_type", "")
                label = f"Fix ({fix_type})" if fix_type else "Fix"
                lines.append(f"  {label}: {fix[:120]}")

    # 2. Code conventions (follow project style)
    conventions = all_data.get("conventions", [])
    if conventions:
        lines.append("## Project Conventions")
        for c in conventions[:4]:
            lines.append(f"- [{c['category']}] {c['rule']}")
            if c.get("example"):
                lines.append(f"  Example: {c['example'][:80]}")

    # 3. Git patterns (this repo's patterns)
    git_patterns = all_data.get("git_patterns", [])
    if git_patterns:
        lines.append("## Repository Patterns")
        for g in git_patterns[:3]:
            lines.append(f"- [{g['pattern_type']}] {g['description'][:120]}")

    # 4. Skills & patterns (from learning)
    skills = all_data.get("skills", [])
    if skills:
        lines.append("## Relevant Skills")
        for s in skills[:3]:
            lines.append(f"- **{s['name']}** [{s['domain']}]: {s.get('pattern', '')[:100]}")
            if s.get("when_to_use"):
                lines.append(f"  When: {s['when_to_use'][:100]}")
            if s.get("anti_patterns"):
                lines.append(f"  Avoid: {s['anti_patterns'][:100]}")
            if s.get("code_example"):
                lines.append(f"  Example: {s['code_example'][:120]}")

    patterns = all_data.get("patterns", [])
    if patterns:
        lines.append("## Learned Patterns")
        for p in patterns[:3]:
            lines.append(f"- **{p['name']}** [{p['domain']}]: {p.get('description', '')[:100]}")

    # 5. Rules & tips
    rules = all_data.get("rules", [])
    if rules:
        lines.append("## Rules")
        for r in rules[:2]:
            lines.append(f"- {r[:120]}")

    tips = all_data.get("quality_tips", [])
    if tips:
        lines.append("## Quality Tips")
        for t in tips[:2]:
            lines.append(f"- {t}")

    insights = all_data.get("session_insights", [])
    if insights:
        lines.append("## Session Insights")
        for i in insights[:2]:
            lines.append(f"- {i[:120]}")

    # 6. Best practices (EMA-ranked strategies)
    best_pracs = all_data.get("best_practices", [])
    if best_pracs:
        lines.append("## Best Practices")
        for bp in best_pracs[:3]:
            pct = int(bp.get("ema_rate", 0) * 100)
            lines.append("- [%s] %s (%d%% success, %d uses)" % (
                bp.get("prompt_type", ""), bp.get("strategy", "")[:80],
                pct, bp.get("uses", 0)))

    # 7. Past memories (cross-session vectorized knowledge)
    memories = all_data.get("memories", [])
    if memories:
        lines.append("## Past Memories")
        for m in memories[:5]:
            cat = m.get("category", "")
            content = m.get("content", "")[:120]
            conf = m.get("confidence", 0.5)
            lines.append(f"- [{cat}] {content} (conf={conf:.1f})")

    # 8. Dependency-aware context
    deps = all_data.get("dependencies", {})
    local_deps = deps.get("local", [])
    if local_deps:
        lines.append("## Local Dependencies")
        lines.append(f"- Imports: {', '.join(local_deps[:5])}")

    # 9. Test-aware context
    test_files = all_data.get("test_files", [])
    if test_files:
        lines.append("## Related Tests")
        for tf in test_files[:2]:
            lines.append(f"- {os.path.basename(tf)}")

    if not lines:
        return None

    return "\n".join(lines)


def refresh_claude_md(project_root):
    """Auto-refresh CLAUDE.md from VPS if stale."""
    claude_md_path = os.path.join(project_root, "CLAUDE.md")
    # Check if stale or missing
    if os.path.isfile(claude_md_path):
        age = time.time() - os.path.getmtime(claude_md_path)
        if age < CLAUDE_MD_INTERVAL:
            return  # still fresh

    result = api_get("/evolutions/claude-md")
    if result and result.get("ok"):
        content = result["data"].get("content", "")
        if content and len(content) > 50:
            try:
                with open(claude_md_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except (IOError, OSError):
                pass


def _accumulate_injection(all_data, domain):
    """Accumulate injection data for later flush with real session_id."""
    sections = []
    failure_count = len(all_data.get("failures", []))
    skill_count = len(all_data.get("skills", []))
    pattern_count = len(all_data.get("patterns", []))
    has_fix_code = any(
        f.get("fix_code") for f in all_data.get("failures", [])
    )

    if failure_count:
        sections.append("failures")
    if skill_count:
        sections.append("skills")
    if pattern_count:
        sections.append("patterns")
    if all_data.get("conventions"):
        sections.append("conventions")
    if all_data.get("memories"):
        sections.append("memories")
    if all_data.get("best_practices"):
        sections.append("best_practices")

    if not sections:
        return

    try:
        # Add parent dir to path for evo_hook_common import
        parent = os.path.dirname(os.path.abspath(__file__))
        if parent not in sys.path:
            sys.path.insert(0, parent)
        from evo_hook_common import record_injection
        record_injection(
            sections=sections,
            failure_count=failure_count,
            skill_count=skill_count,
            pattern_count=pattern_count,
            has_fix_code=has_fix_code,
            domain=domain or "",
        )
    except ImportError:
        pass  # evo_hook_common not available


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
    lang = get_file_language(file_path)
    cache_key = "_".join(sorted(keywords))[:50]

    # Check cache
    cached = get_cache(cache_key)
    if cached:
        all_data = cached
    else:
        all_data = {}

        # Single batch request — replaces 6+ serial API calls
        task_text = " ".join(keywords) if keywords else ""
        if task_text:
            batch = api_post("/context/batch", {
                "task": task_text,
                "domain": lang or "",
                "limit": 5,
                "include": ["skills", "patterns", "failures", "conventions",
                           "git_patterns", "briefing", "best_practices", "memories"],
            })
            if batch and batch.get("ok"):
                all_data = batch.get("data", {})

                # Merge briefing warnings into failures (compat with old format)
                briefing = all_data.get("briefing", {})
                if briefing.get("warnings"):
                    existing_failures = all_data.get("failures", [])
                    for w in briefing["warnings"]:
                        existing_failures.append({"error_type": "warning", "description": w, "fix_suggestion": ""})
                    all_data["failures"] = existing_failures[:5]

        save_cache(cache_key, all_data)

    # Dependency-aware + test-aware (always fresh, not cached)
    all_data["dependencies"] = extract_dependencies(file_path)
    all_data["test_files"] = find_test_files(file_path)

    # Format and output
    context_text = format_context(all_data)
    if context_text:
        print(context_text)
        # Phase 3: accumulate injection data for effect tracking
        _accumulate_injection(all_data, lang)

    # Auto-refresh CLAUDE.md (non-blocking, runs occasionally)
    project_root = os.path.dirname(os.path.dirname(file_path))
    if project_root and os.path.isdir(project_root):
        try:
            refresh_claude_md(project_root)
        except Exception:
            pass


if __name__ == "__main__":
    main()
