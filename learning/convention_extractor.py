"""Codebase convention extractor — analyzes project code style.

Extracts naming conventions, error handling patterns, directory structure,
and coding style from the project. Posts to VPS for context injection.
"""
import os
import re
import json
import hashlib
import urllib.request
import sys
from collections import Counter

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
    except Exception:
        return None


def extract_python_conventions(project_path):
    """Analyze Python files for conventions."""
    conventions = []

    py_files = []
    for root, dirs, files in os.walk(project_path):
        # Skip hidden dirs, venvs, node_modules
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", "node_modules", "__pycache__", ".git")]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    if not py_files:
        return conventions

    # Sample up to 20 files
    sampled = py_files[:20]

    # 1. Naming conventions
    snake_count = 0
    camel_count = 0
    class_names = []
    function_names = []
    import_patterns = []

    for fp in sampled:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(5000)
        except (IOError, OSError):
            continue

        # Function names
        funcs = re.findall(r"def\s+(\w+)\s*\(", content)
        function_names.extend(funcs)
        for fn in funcs:
            if "_" in fn:
                snake_count += 1
            elif fn[0].isupper():
                camel_count += 1

        # Class names
        classes = re.findall(r"class\s+(\w+)", content)
        class_names.extend(classes)

        # Import patterns
        imports = re.findall(r"^(?:from\s+\S+\s+)?import\s+(.+)", content, re.MULTILINE)
        import_patterns.extend(imports)

    # Naming convention
    total = snake_count + camel_count
    if total > 0:
        style = "snake_case" if snake_count > camel_count else "camelCase"
        confidence = snake_count / total if style == "snake_case" else camel_count / total
        conventions.append({
            "category": "naming",
            "rule": f"Use {style} for function/method names",
            "example": f"snake_case: {snake_count}, camelCase: {camel_count}",
            "confidence": round(confidence, 2),
        })

    # 2. Import style
    if import_patterns:
        from_count = sum(1 for i in import_patterns if "from" in i or "import" in i)
        # Check for typing imports
        typing_imports = [i for i in import_patterns if "typing" in i]
        if typing_imports:
            conventions.append({
                "category": "style",
                "rule": "Uses typing module for type hints",
                "example": "; ".join(typing_imports[:3]),
                "confidence": 0.7,
            })

    # 3. Error handling patterns
    error_patterns = []
    for fp in sampled:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(5000)
        except (IOError, OSError):
            continue

        if "try:" in content:
            error_patterns.append("try/except")
        if "logging" in content:
            error_patterns.append("logging")
        if "raise " in content:
            error_patterns.append("raise")
        if "assert " in content:
            error_patterns.append("assert")

    if error_patterns:
        from collections import Counter
        error_counts = Counter(error_patterns)
        top_error = error_counts.most_common(1)[0]
        conventions.append({
            "category": "error_handling",
            "rule": f"Primary error handling: {top_error[0]} ({top_error[1]}/{len(sampled)} files)",
            "example": ", ".join(f"{k}({v})" for k, v in error_counts.most_common(3)),
            "confidence": round(top_error[1] / len(sampled), 2),
        })

    # 4. Docstring style
    docstring_patterns = []
    for fp in sampled:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(5000)
        except (IOError, OSError):
            continue

        if '"""' in content:
            docstring_patterns.append("double_quote")
        if "'''" in content:
            docstring_patterns.append("single_quote")
        if "Args:" in content or "Returns:" in content:
            docstring_patterns.append("google_style")
        if ":param" in content:
            docstring_patterns.append("sphinx_style")

    if docstring_patterns:
        doc_counts = Counter(docstring_patterns)
        if doc_counts.get("google_style", 0) > 0:
            conventions.append({
                "category": "style",
                "rule": "Uses Google-style docstrings (Args:/Returns:)",
                "example": "Google-style docstrings found",
                "confidence": 0.6,
            })
        quote_style = "double" if doc_counts.get("double_quote", 0) >= doc_counts.get("single_quote", 0) else "single"
        conventions.append({
            "category": "style",
            "rule": f"Docstrings use {quote_style} quotes",
            "example": f'{quote_style}_quote: {doc_counts.get(quote_style + "_quote", 0)}',
            "confidence": 0.5,
        })

    # 5. Directory structure
    dirs = set()
    for fp in py_files:
        rel = os.path.relpath(os.path.dirname(fp), project_path)
        if rel != ".":
            top = rel.split(os.sep)[0]
            dirs.add(top)

    if dirs:
        conventions.append({
            "category": "structure",
            "rule": f"Project structure: {', '.join(sorted(dirs)[:8])}",
            "example": str(sorted(dirs)[:8]),
            "confidence": 0.4,
        })

    return conventions


def extract_js_conventions(project_path):
    """Analyze JS/TS files for conventions."""
    conventions = []
    # Similar analysis for JS/TS files
    return conventions


def extract_conventions(project_path):
    """Extract all conventions from a project."""
    conventions = extract_python_conventions(project_path)
    conventions.extend(extract_js_conventions(project_path))
    return conventions


def save_conventions(conventions):
    """Save conventions to VPS."""
    saved = 0
    for c in conventions:
        result = api_post("/learn/convention", c)
        if result and result.get("ok"):
            saved += 1
    return saved


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    conventions = extract_conventions(path)
    print(f"Found {len(conventions)} conventions in {path}")
    for c in conventions:
        print(f"  [{c['category']}] {c['rule']}")

    saved = save_conventions(conventions)
    print(f"Saved {saved} conventions to VPS")
