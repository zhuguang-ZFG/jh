"""Git history learner — extracts patterns from commit messages and diffs.

Run locally or via cron. Posts learned patterns to VPS.
"""
import subprocess
import re
import json
import hashlib
import urllib.request
import os
import sys

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


def git_log(repo_path, n=50):
    """Get recent commit messages."""
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--format=%s|||%h"],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split("\n")
        commits = []
        for line in lines:
            if "|||" in line:
                msg, sha = line.split("|||", 1)
                commits.append({"message": msg.strip(), "sha": sha.strip()})
        return commits
    except Exception:
        return []


def git_diff_stat(repo_path, n=10):
    """Get diff stats for recent commits."""
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--stat", "--format="],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        return result.stdout
    except Exception:
        return ""


def extract_commit_patterns(commits):
    """Extract patterns from commit messages."""
    patterns = []

    # 1. Commit message style patterns
    prefixes = []
    for c in commits:
        msg = c["message"]
        # Conventional commits: feat:, fix:, refactor:, etc.
        m = re.match(r"^(\w+)[:(]", msg)
        if m:
            prefixes.append(m.group(1).lower())

    if prefixes:
        from collections import Counter
        prefix_counts = Counter(prefixes)
        for prefix, count in prefix_counts.most_common(5):
            if count >= 2:
                patterns.append({
                    "pattern_type": "commit_style",
                    "description": f"Uses '{prefix}:' commit prefix ({count} times)",
                    "example": prefix,
                    "confidence": min(0.5 + count * 0.05, 0.9),
                })

    # 2. Common commit topics
    topics = []
    for c in commits:
        msg = c["message"].lower()
        # Extract topic keywords
        words = re.findall(r"[a-z_]{3,}", msg)
        topics.extend(words)

    if topics:
        from collections import Counter
        stop = {"the", "and", "for", "with", "from", "this", "that", "was", "are", "has", "have", "not", "but"}
        topic_counts = Counter(t for t in topics if t not in stop)
        for topic, count in topic_counts.most_common(5):
            if count >= 3:
                patterns.append({
                    "pattern_type": "code_pattern",
                    "description": f"Frequent topic: '{topic}' ({count} commits)",
                    "example": topic,
                    "confidence": min(0.4 + count * 0.03, 0.8),
                })

    # 3. Refactor patterns
    refactor_commits = [c for c in commits if any(k in c["message"].lower() for k in ("refactor", "restructure", "reorganize", "clean"))]
    if refactor_commits:
        patterns.append({
            "pattern_type": "refactor",
            "description": f"Active refactoring culture ({len(refactor_commits)} refactor commits)",
            "example": "; ".join(c["message"][:60] for c in refactor_commits[:3]),
            "confidence": 0.6,
        })

    return patterns


def extract_diff_patterns(diff_stat):
    """Extract patterns from diff stats."""
    patterns = []

    # File type distribution
    ext_changes = {}
    for line in diff_stat.split("\n"):
        m = re.search(r"(\.\w+)\s+\|", line)
        if m:
            ext = m.group(1)
            ext_changes[ext] = ext_changes.get(ext, 0) + 1

    if ext_changes:
        top_exts = sorted(ext_changes.items(), key=lambda x: x[1], reverse=True)[:5]
        patterns.append({
            "pattern_type": "code_pattern",
            "description": f"Active file types: {', '.join(f'{e}({c})' for e, c in top_exts)}",
            "example": str(dict(top_exts)),
            "confidence": 0.5,
        })

    # Large changes pattern
    large_files = re.findall(r"(\S+\.\w+)\s+\|\s+(\d+ [+-])", diff_stat)
    if large_files:
        patterns.append({
            "pattern_type": "code_pattern",
            "description": f"Large change files: {', '.join(f[0] for f in large_files[:3])}",
            "example": "; ".join(f"{f[0]}: {f[1]}" for f in large_files[:3]),
            "confidence": 0.4,
        })

    return patterns


def learn_from_repo(repo_path):
    """Analyze a git repo and return learned patterns."""
    commits = git_log(repo_path, 50)
    diff = git_diff_stat(repo_path, 20)

    commit_patterns = extract_commit_patterns(commits)
    diff_patterns = extract_diff_patterns(diff)

    all_patterns = commit_patterns + diff_patterns
    for p in all_patterns:
        p["repo"] = repo_path

    return all_patterns


def learn_from_current_dir():
    """Learn from the current working directory's git repo."""
    cwd = os.getcwd()
    patterns = learn_from_repo(cwd)

    saved = 0
    for p in patterns:
        result = api_post("/learn/git-pattern", p)
        if result and result.get("ok"):
            saved += 1

    return {"repo": cwd, "patterns_found": len(patterns), "saved": saved}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    result = learn_from_repo(path)
    print(f"Found {len(result)} patterns in {path}")
    for p in result:
        print(f"  [{p['pattern_type']}] {p['description']}")

    # Save to VPS
    saved = 0
    for p in result:
        r = api_post("/learn/git-pattern", p)
        if r and r.get("ok"):
            saved += 1
    print(f"Saved {saved} patterns to VPS")
