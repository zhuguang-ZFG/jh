"""Code quality analyzer — AST-based metrics for Python files.

Runs before/after Claude's changes to measure quality impact.
Python 3.6 compatible.
"""
import ast
import os
import hashlib
import time
from typing import List, Dict, Optional, Tuple


def analyze_file(filepath):
    # type: (str) -> Dict
    """Analyze a single Python file, return quality metrics."""
    metrics = {
        "file": filepath,
        "hash": "",
        "loc": 0,
        "syntax_ok": True,
        "syntax_error": "",
        "functions": 0,
        "classes": 0,
        "methods": 0,
        "imports": 0,
        "max_nesting": 0,
        "avg_func_length": 0,
        "complexity": 0,
        "analyzed_at": time.time(),
    }

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (IOError, OSError):
        metrics["syntax_ok"] = False
        metrics["syntax_error"] = "File not readable"
        return metrics

    metrics["hash"] = hashlib.md5(content.encode()).hexdigest()[:12]
    lines = content.split("\n")
    metrics["loc"] = len([l for l in lines if l.strip() and not l.strip().startswith("#")])

    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as e:
        metrics["syntax_ok"] = False
        metrics["syntax_error"] = str(e)
        return metrics

    func_lengths = []
    total_complexity = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            metrics["functions"] += 1
            # Calculate function length
            if hasattr(node, "end_lineno") and node.end_lineno:
                flen = node.end_lineno - node.lineno + 1
            else:
                flen = _estimate_func_length(lines, node.lineno)
            func_lengths.append(flen)
            # Calculate cyclomatic complexity
            total_complexity += _calc_complexity(node)

        elif isinstance(node, ast.ClassDef):
            metrics["classes"] += 1
            # Count methods in class
            methods = [n for n in ast.iter_child_nodes(node) if isinstance(n, ast.FunctionDef)]
            metrics["methods"] += len(methods)

        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            metrics["imports"] += 1

    # Nesting depth
    metrics["max_nesting"] = _calc_max_nesting(tree)

    # Average function length
    if func_lengths:
        metrics["avg_func_length"] = round(sum(func_lengths) / len(func_lengths), 1)

    metrics["complexity"] = total_complexity

    return metrics


def analyze_snapshot(filepaths):
    # type: (List[str]) -> Dict[str, Dict]
    """Analyze multiple files, return dict keyed by filepath."""
    snapshot = {}
    for fp in filepaths:
        if fp.endswith(".py") and os.path.isfile(fp):
            snapshot[fp] = analyze_file(fp)
    return snapshot


def compare_snapshots(before, after):
    # type: (Dict[str, Dict], Dict[str, Dict]) -> Dict
    """Compare two snapshots, return quality delta."""
    changes = {
        "files_added": [],
        "files_removed": [],
        "files_modified": [],
        "quality_improved": [],
        "quality_degraded": [],
        "syntax_errors_introduced": [],
        "syntax_errors_fixed": [],
        "summary": {},
    }

    before_keys = set(before.keys())
    after_keys = set(after.keys())

    changes["files_added"] = list(after_keys - before_keys)
    changes["files_removed"] = list(before_keys - after_keys)

    for fp in before_keys & after_keys:
        b, a = before[fp], after[fp]
        if b["hash"] == a["hash"]:
            continue

        changes["files_modified"].append(fp)

        # Check syntax errors
        if not b["syntax_ok"] and a["syntax_ok"]:
            changes["syntax_errors_fixed"].append(fp)
        elif b["syntax_ok"] and not a["syntax_ok"]:
            changes["syntax_errors_introduced"].append(fp)

        # Check complexity
        if b["complexity"] > 0:
            delta = (a["complexity"] - b["complexity"]) / b["complexity"]
            if delta < -0.1:
                changes["quality_improved"].append(fp)
            elif delta > 0.2:
                changes["quality_degraded"].append(fp)
        elif a["complexity"] > 10:
            changes["quality_degraded"].append(fp)

    # Summary
    total_complexity_before = sum(m["complexity"] for m in before.values())
    total_complexity_after = sum(m["complexity"] for m in after.values())
    total_loc_before = sum(m["loc"] for m in before.values())
    total_loc_after = sum(m["loc"] for m in after.values())

    changes["summary"] = {
        "files_changed": len(changes["files_modified"]),
        "complexity_delta": total_complexity_after - total_complexity_before,
        "loc_delta": total_loc_after - total_loc_before,
        "syntax_errors_introduced": len(changes["syntax_errors_introduced"]),
        "syntax_errors_fixed": len(changes["syntax_errors_fixed"]),
        "quality_score": _calc_quality_score(changes, total_complexity_after, total_loc_after),
    }

    return changes


def format_report(delta):
    # type: (Dict) -> str
    """Format quality delta as human-readable report."""
    s = delta["summary"]
    lines = [
        "=== Code Quality Report ===",
        "Files changed: {}".format(s["files_changed"]),
        "LOC delta: {:+d}".format(s["loc_delta"]),
        "Complexity delta: {:+d}".format(s["complexity_delta"]),
        "Quality score: {}/100".format(s["quality_score"]),
    ]

    if delta["syntax_errors_introduced"]:
        lines.append("SYNTAX ERRORS INTRODUCED: {}".format(", ".join(delta["syntax_errors_introduced"])))
    if delta["syntax_errors_fixed"]:
        lines.append("Syntax errors fixed: {}".format(", ".join(delta["syntax_errors_fixed"])))
    if delta["quality_improved"]:
        lines.append("Improved: {}".format(", ".join(delta["quality_improved"])))
    if delta["quality_degraded"]:
        lines.append("DEGRADED: {}".format(", ".join(delta["quality_degraded"])))

    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────

def _estimate_func_length(lines, start_lineno):
    # type: (List[str], int) -> int
    """Estimate function length by indentation."""
    if start_lineno <= 0 or start_lineno > len(lines):
        return 1
    base_indent = len(lines[start_lineno - 1]) - len(lines[start_lineno - 1].lstrip())
    length = 0
    for i in range(start_lineno, len(lines)):
        line = lines[i]
        if not line.strip():
            length += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and line.strip():
            break
        length += 1
    return max(length, 1)


def _calc_complexity(node):
    # type: (ast.AST) -> int
    """Calculate cyclomatic complexity for a function node."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            complexity += 1
    return complexity


def _calc_max_nesting(tree):
    # type: (ast.AST) -> int
    """Calculate maximum nesting depth."""
    max_depth = 0

    def _walk(node, depth):
        nonlocal max_depth
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)):
            depth += 1
            max_depth = max(max_depth, depth)
        for child in ast.iter_child_nodes(node):
            _walk(child, depth)

    _walk(tree, 0)
    return max_depth


def _calc_quality_score(delta, total_complexity, total_loc):
    # type: (Dict, int, int) -> int
    """Calculate 0-100 quality score."""
    score = 100

    # Penalize syntax errors
    score -= delta["summary"]["syntax_errors_introduced"] * 20

    # Penalize complexity increase
    if delta["summary"]["complexity_delta"] > 0:
        score -= min(delta["summary"]["complexity_delta"] * 2, 30)

    # Reward complexity decrease
    if delta["summary"]["complexity_delta"] < 0:
        score += min(abs(delta["summary"]["complexity_delta"]), 10)

    # Penalize large LOC increase without complexity decrease
    if delta["summary"]["loc_delta"] > 100 and delta["summary"]["complexity_delta"] >= 0:
        score -= 10

    return max(0, min(100, score))
