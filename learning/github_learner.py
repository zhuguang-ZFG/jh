#!/usr/bin/env python3
"""GitHub Learning Engine — search trending repos, extract patterns."""
import json
import os
import re
import subprocess
import tempfile
import urllib.request
import urllib.parse
from pathlib import Path

# Config
EVO_SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
LANGUAGES = os.getenv("EVO_LEARN_LANGUAGES", "python,rust,go,typescript").split(",")
MAX_REPOS = 3
MAX_FILE_SIZE = 50_000  # skip large files


def github_api(path: str) -> dict:
    url = f"https://api.github.com{path}"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "evo-learner"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def search_trending(language: str, since: str = "daily") -> list[dict]:
    """Search GitHub for trending repos by language and recent activity."""
    # Use GitHub search API: repos created/updated recently with high stars
    query = f"language:{language} created:>{_days_ago(7)} stars:>50"
    encoded_query = urllib.parse.quote(query)
    try:
        result = github_api(f"/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page=5")
        return result.get("items", [])[:MAX_REPOS]
    except Exception as e:
        print(f"[learner] Search failed for {language}: {e}")
        return []


def _days_ago(n: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def clone_repo(repo_url: str, target_dir: str) -> Path | None:
    """Shallow clone a repo."""
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "--single-branch", repo_url, target_dir],
            capture_output=True, timeout=30, check=True,
        )
        return Path(target_dir)
    except Exception as e:
        print(f"[learner] Clone failed {repo_url}: {e}")
        return None


def scan_repo(repo_path: Path, language: str) -> list[dict]:
    """Scan repo for code patterns."""
    from pattern_extractor import extract_patterns
    extensions = {
        "python": ".py", "rust": ".rs", "go": ".go",
        "typescript": ".ts", "javascript": ".js", "tsx": ".tsx",
    }
    ext = extensions.get(language, ".py")
    patterns = []

    for file in repo_path.rglob(f"*{ext}"):
        if file.stat().st_size > MAX_FILE_SIZE:
            continue
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
            file_patterns = extract_patterns(content, language, str(file.relative_to(repo_path)))
            patterns.extend(file_patterns)
        except Exception:
            continue

    return patterns


def post_patterns(patterns: list[dict], source_repo: str):
    """Post patterns to evo-server API."""
    for p in patterns:
        try:
            data = json.dumps({
                "name": p["name"],
                "domain": p.get("domain", "general"),
                "description": p["description"],
                "code_example": p.get("code_example", ""),
                "source_repo": source_repo,
                "confidence": p.get("confidence", 0.5),
            }).encode()
            req = urllib.request.Request(
                f"{EVO_SERVER}/patterns/learn",
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"[learner] Failed to post pattern: {e}")


def main():
    print(f"[learner] Starting GitHub learning for: {', '.join(LANGUAGES)}")
    total_patterns = 0

    for lang in LANGUAGES:
        print(f"\n[learner] Searching trending {lang} repos...")
        repos = search_trending(lang)
        if not repos:
            print(f"[learner] No trending repos found for {lang}")
            continue

        for repo in repos:
            name = repo["full_name"]
            url = repo["clone_url"]
            print(f"[learner] Scanning {name}...")

            with tempfile.TemporaryDirectory() as tmpdir:
                path = clone_repo(url, tmpdir)
                if not path:
                    continue
                patterns = scan_repo(path, lang)
                if patterns:
                    post_patterns(patterns, f"https://github.com/{name}")
                    total_patterns += len(patterns)
                    print(f"[learner] Extracted {len(patterns)} patterns from {name}")

    print(f"\n[learner] Done. Total patterns learned: {total_patterns}")

    # Post summary to Telegram
    try:
        data = json.dumps({
            "text": f"[evo-learning] Completed. Learned {total_patterns} patterns from {len(LANGUAGES)} languages."
        }).encode()
        req = urllib.request.Request(
            f"{EVO_SERVER}/telegram/webhook",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


if __name__ == "__main__":
    main()
