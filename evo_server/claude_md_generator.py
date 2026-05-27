"""Auto-generate CLAUDE.md from accumulated session experience.

Analyzes sessions, skills, patterns, and quality data to produce
project-specific instructions that improve Claude Code's output.
"""
import json
import time
import hashlib
from collections import Counter, defaultdict
from .db import get_conn


def generate_claude_md(project_path=""):
    # type: (str) -> dict
    """Generate CLAUDE.md content from accumulated experience."""
    conn = get_conn()
    now = time.time()
    cutoff = now - 30 * 86400  # Last 30 days

    # Gather data
    sessions = _get_sessions(conn, cutoff)
    skills = _get_skills(conn)
    patterns = _get_patterns(conn)
    quality = _get_quality_trends(conn, cutoff)

    if not sessions and not skills:
        return {"content": _default_claude_md(), "stats": {"sessions": 0, "skills": 0}}

    # Analyze success/failure patterns
    success_domains = Counter()
    failure_domains = Counter()
    failure_reasons = []
    success_techniques = []

    for s in sessions:
        domain = _infer_domain(s.get("changed_files", ""))
        if s["outcome"] == "success":
            success_domains[domain] += 1
            if s.get("lessons"):
                success_techniques.append(s["lessons"][:200])
        elif s["outcome"] == "failure":
            failure_domains[domain] += 1
            if s.get("lessons"):
                failure_reasons.append(s["lessons"][:200])

    # Build sections
    sections = []

    # Header
    sections.append("# Project Coding Guidelines (Auto-generated)\n")
    sections.append("> Generated from {} sessions, {} skills, {} patterns".format(
        len(sessions), len(skills), len(patterns)))
    sections.append("> Last updated: {}\n".format(time.strftime("%Y-%m-%d %H:%M")))

    # Domain expertise
    if success_domains:
        sections.append("## Active Domains\n")
        for domain, count in success_domains.most_common(5):
            sections.append("- **{}**: {} successful sessions".format(domain, count))
        sections.append("")

    # Failure patterns to avoid
    if failure_reasons:
        sections.append("## Known Failure Patterns (Avoid These)\n")
        seen = set()
        for reason in failure_reasons[:5]:
            key = reason[:50]
            if key not in seen:
                seen.add(key)
                sections.append("- {}".format(reason[:150]))
        sections.append("")

    # Success techniques to repeat
    if success_techniques:
        sections.append("## Proven Techniques (Use These)\n")
        seen = set()
        for tech in success_techniques[:5]:
            key = tech[:50]
            if key not in seen:
                seen.add(key)
                sections.append("- {}".format(tech[:150]))
        sections.append("")

    # High-value skills
    top_skills = sorted(skills, key=lambda s: s.get("weight", 0), reverse=True)[:10]
    if top_skills:
        sections.append("## Key Skills (by confidence)\n")
        for sk in top_skills:
            sections.append("- **{}** [{}]: weight={:.2f}".format(
                sk["name"], sk["domain"], sk.get("weight", 1.0)))
        sections.append("")

    # Learned patterns
    top_patterns = sorted(patterns, key=lambda p: p.get("confidence", 0), reverse=True)[:8]
    if top_patterns:
        sections.append("## Learned Code Patterns\n")
        for p in top_patterns:
            sections.append("- **{}** [{}]: {}".format(
                p["name"], p["domain"], p.get("description", "")[:100]))
        sections.append("")

    # Quality trends
    if quality:
        avg_score = sum(q.get("quality_score", 0) for q in quality) / len(quality)
        sections.append("## Code Quality Trends\n")
        sections.append("- Average quality score: {:.0f}/100".format(avg_score))
        total_syntax = sum(q.get("syntax_errors", 0) for q in quality)
        if total_syntax:
            sections.append("- **WARNING**: {} syntax errors introduced recently".format(total_syntax))
        sections.append("")

    # Language-specific rules
    lang_counts = Counter()
    for s in sessions:
        try:
            files = json.loads(s.get("changed_files", "[]"))
            for f in files:
                ext = f.rsplit(".", 1)[-1] if "." in f else ""
                lang_counts[ext] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    if lang_counts:
        sections.append("## Language-Specific Notes\n")
        for ext, count in lang_counts.most_common(3):
            lang = {"py": "Python", "js": "JavaScript", "ts": "TypeScript",
                    "rs": "Rust", "go": "Go"}.get(ext, ext)
            sections.append("### {}\n".format(lang))
            if ext == "py":
                sections.append("- Use `typing.List`, `typing.Dict` for Python 3.6 compat")
                sections.append("- Prefer `Optional[X]` over `X | None`")
            elif ext in ("js", "ts"):
                sections.append("- Use explicit imports, avoid barrel exports")
            elif ext == "rs":
                sections.append("- Prefer `Result<T, E>` over `.unwrap()`")
            sections.append("")

    # Rules from meta_rules
    rules = conn.execute(
        "SELECT rule_value, category FROM meta_rules ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    if rules:
        sections.append("## Project Rules\n")
        for r in rules:
            sections.append("- [{}] {}".format(r["category"], r["rule_value"][:150]))
        sections.append("")

    content = "\n".join(sections)

    stats = {
        "sessions": len(sessions),
        "skills": len(skills),
        "patterns": len(patterns),
        "quality_entries": len(quality),
        "top_domain": success_domains.most_common(1)[0][0] if success_domains else "none",
    }

    return {"content": content, "stats": stats}


def save_claude_md(content, filepath="CLAUDE.md"):
    # type: (str, str) -> bool
    """Save generated CLAUDE.md to file."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except (IOError, OSError):
        return False


# ── Helpers ───────────────────────────────────────────────────

def _get_sessions(conn, cutoff):
    rows = conn.execute(
        "SELECT * FROM sessions WHERE created_at > ? ORDER BY created_at",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_skills(conn):
    rows = conn.execute(
        "SELECT * FROM skills WHERE weight > 0.1 ORDER BY weight DESC LIMIT 50"
    ).fetchall()
    return [dict(r) for r in rows]


def _get_patterns(conn):
    rows = conn.execute(
        "SELECT * FROM patterns WHERE confidence > 0.3 ORDER BY confidence DESC LIMIT 30"
    ).fetchall()
    return [dict(r) for r in rows]


def _get_quality_trends(conn, cutoff):
    rows = conn.execute(
        """SELECT delta FROM quality_snapshots
           WHERE phase='after' AND created_at > ?""",
        (cutoff,),
    ).fetchall()
    trends = []
    for r in rows:
        try:
            delta = json.loads(r["delta"])
            summary = delta.get("summary", {})
            if summary:
                trends.append(summary)
        except (json.JSONDecodeError, TypeError):
            pass
    return trends


def _infer_domain(changed_files_str):
    try:
        files = json.loads(changed_files_str) if changed_files_str else []
    except (json.JSONDecodeError, TypeError):
        return "general"

    exts = {}
    for f in files:
        ext = f.rsplit(".", 1)[-1] if "." in f else ""
        exts[ext] = exts.get(ext, 0) + 1

    if not exts:
        return "general"

    top_ext = max(exts, key=exts.get)
    ext_map = {
        "py": "python", "rs": "rust", "go": "go",
        "ts": "typescript", "tsx": "react", "jsx": "react",
        "js": "javascript", "vue": "frontend",
        "sql": "data", "yml": "devops", "yaml": "devops",
    }
    return ext_map.get(top_ext, "general")


def _default_claude_md():
    return """# Project Coding Guidelines

No session data yet. This file will be auto-generated as sessions accumulate.

## Getting Started
- Use the evo-server hooks to track your coding sessions
- Skills and patterns will be learned automatically
- This CLAUDE.md will be updated with project-specific guidelines
"""
