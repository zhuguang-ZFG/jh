"""Extract real code skills from git diffs.

Parses git diff output, extracts added lines (+), runs pattern_extractor
on the new code, and produces skills with concrete code_examples.
"""
import re
import hashlib
import logging
from typing import List, Dict

logger = logging.getLogger("evo.skill_extractor")


def extract_skills_from_diff(git_diff: str, changed_files: list) -> List[Dict]:
    """Extract skills from git diff output.

    Returns list of skill dicts with: name, domain, pattern, code_example, weight.
    """
    if not git_diff or len(git_diff) < 50:
        return []

    # Parse diff into per-file added code blocks
    file_blocks = _parse_diff_added_lines(git_diff)
    if not file_blocks:
        return []

    skills = []
    for filepath, added_lines in file_blocks.items():
        if len(added_lines) < 3:
            continue  # too few lines to be interesting

        language = _detect_language(filepath)
        if not language:
            continue

        content = "\n".join(added_lines)
        file_skills = _extract_from_content(content, language, filepath)
        skills.extend(file_skills)

    # Deduplicate by name
    seen = set()
    unique = []
    for s in skills:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)

    return unique[:10]  # cap per session


def _parse_diff_added_lines(git_diff: str) -> Dict[str, List[str]]:
    """Parse git diff, extract only added lines (+) per file."""
    files = {}
    current_file = None
    in_hunk = False

    for line in git_diff.split("\n"):
        # File header: +++ b/path/to/file
        if line.startswith("+++ b/"):
            current_file = line[6:]
            files[current_file] = []
            in_hunk = False
            continue

        # Hunk header: @@ -a,b +c,d @@
        if line.startswith("@@"):
            in_hunk = True
            continue

        # Added line
        if in_hunk and line.startswith("+") and not line.startswith("+++"):
            code_line = line[1:]  # strip leading +
            # Skip pure comments, blank lines, import-only lines
            stripped = code_line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
                if current_file:
                    files[current_file].append(code_line)

        # Reset on new file section
        if line.startswith("diff --git"):
            in_hunk = False

    return {f: lines for f, lines in files.items() if lines}


def _detect_language(filepath: str) -> str:
    """Detect language from file extension."""
    if not filepath:
        return ""
    ext = filepath.rsplit(".", 1)[-1] if "." in filepath else ""
    return {
        "py": "python", "js": "javascript", "ts": "typescript",
        "tsx": "typescript", "jsx": "javascript",
        "rs": "rust", "go": "go",
    }.get(ext, "")


def _extract_from_content(content: str, language: str, filepath: str) -> List[Dict]:
    """Extract patterns from code content using AST-lite scanning."""
    try:
        # Import from learning module (same repo, different package)
        import sys
        import os
        # Add parent dir to path for learning module access
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        learning_path = os.path.join(parent, "learning")
        if os.path.isdir(learning_path) and parent not in sys.path:
            sys.path.insert(0, parent)
        from learning.pattern_extractor import extract_patterns
        patterns = extract_patterns(content, language, filepath)
    except ImportError:
        # Fallback: basic extraction
        patterns = _basic_extract(content, language, filepath)

    # Convert patterns to skills with code_example
    skills = []
    for p in patterns:
        code_example = p.get("code_example", "")
        if not code_example:
            # Extract a representative snippet
            code_example = _extract_snippet(content, p.get("name", ""))
        skills.append({
            "name": p["name"],
            "domain": p.get("domain", "general"),
            "pattern": p.get("description", "")[:200],
            "code_example": code_example[:300],
            "weight": p.get("confidence", 0.5),
            "source": "git_diff",
        })

    return skills


def _extract_snippet(content: str, pattern_name: str) -> str:
    """Extract a short code snippet as example."""
    lines = content.split("\n")
    # Take first non-empty, non-import block
    snippet = []
    for line in lines[:15]:
        stripped = line.strip()
        if stripped and not stripped.startswith("import ") and not stripped.startswith("from "):
            snippet.append(line)
        if len(snippet) >= 5:
            break
    return "\n".join(snippet)[:300]


def _basic_extract(content: str, language: str, filepath: str) -> List[Dict]:
    """Fallback pattern extraction when learning module unavailable."""
    patterns = []
    lines = content.split("\n")

    if language == "python":
        # Function definitions
        for i, line in enumerate(lines):
            m = re.match(r"^(?:async\s+)?def\s+(\w+)\s*\(", line)
            if m:
                func_name = m.group(1)
                # Get body (next 3 lines)
                body = "\n".join(lines[i:i+4])
                patterns.append({
                    "name": f"func_{func_name}",
                    "domain": _domain_from_path(filepath),
                    "description": f"Function {func_name}()",
                    "code_example": body[:200],
                    "confidence": 0.5,
                })

        # Class definitions
        for i, line in enumerate(lines):
            m = re.match(r"^class\s+(\w+)", line)
            if m:
                patterns.append({
                    "name": f"class_{m.group(1).lower()}",
                    "domain": _domain_from_path(filepath),
                    "description": f"Class {m.group(1)}",
                    "code_example": "\n".join(lines[i:i+5])[:200],
                    "confidence": 0.5,
                })

        # FastAPI route decorators
        for i, line in enumerate(lines):
            m = re.match(r'^\s*@\w+\.(get|post|put|delete|patch)\s*\(', line)
            if m:
                patterns.append({
                    "name": f"route_{m.group(1)}",
                    "domain": "api",
                    "description": f"API route decorator: {line.strip()[:80]}",
                    "code_example": "\n".join(lines[i:i+4])[:200],
                    "confidence": 0.6,
                })

    elif language in ("javascript", "typescript"):
        for i, line in enumerate(lines):
            # Arrow functions / exports
            if re.search(r"(export\s+)?(const|let|function)\s+\w+", line):
                patterns.append({
                    "name": f"js_func_{i}",
                    "domain": _domain_from_path(filepath),
                    "description": f"JS function: {line.strip()[:80]}",
                    "code_example": line.strip()[:200],
                    "confidence": 0.4,
                })

    return patterns


def _domain_from_path(filepath: str) -> str:
    fp = filepath.lower()
    if any(k in fp for k in ("test", "spec")):
        return "testing"
    if any(k in fp for k in ("api", "route", "handler")):
        return "api"
    if any(k in fp for k in ("model", "schema", "db")):
        return "data"
    if any(k in fp for k in ("config", "deploy", "ci")):
        return "devops"
    if any(k in fp for k in ("hook", "evo")):
        return "python"
    return "general"
