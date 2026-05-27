#!/usr/bin/env python3
"""GitHub Learning Engine — search trending repos, extract patterns."""
import json
import os
import re
import subprocess
import tempfile
import urllib.request
import urllib.parse
import base64
from pathlib import Path
from typing import List, Dict, Optional

from pattern_extractor import extract_patterns

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


def search_trending(language: str, since: str = "daily") -> List[Dict]:
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


def get_repo_files(repo_name: str, language: str) -> List[Dict]:
    """Get file list from GitHub API without cloning."""
    extensions = {
        "python": ".py", "rust": ".rs", "go": ".go",
        "typescript": ".ts", "javascript": ".js", "tsx": ".tsx",
    }
    ext = extensions.get(language, ".py")
    try:
        # Search for files in the repo
        result = github_api(f"/search/code?q=repo:{repo_name}+extension:{ext}&per_page=5")
        return result.get("items", [])[:5]
    except Exception as e:
        print(f"[learner] File search failed for {repo_name}: {e}")
        return []


def get_file_content(repo_name: str, file_path: str) -> Optional[str]:
    """Get file content from GitHub API."""
    try:
        result = github_api(f"/repos/{repo_name}/contents/{file_path}")
        import base64
        if "content" in result:
            return base64.b64decode(result["content"]).decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[learner] File fetch failed {repo_name}/{file_path}: {e}")
    return None


def scan_repo(repo_path: Path, language: str) -> List[Dict]:
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


def post_patterns(patterns: List[Dict], source_repo: str):
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
            print(f"[learner] Scanning {name}...")

            # Get files via API instead of cloning
            files = get_repo_files(name, lang)
            if not files:
                print(f"[learner] No {lang} files found in {name}")
                continue

            patterns = []
            for file_info in files[:3]:  # Limit to 3 files per repo
                file_path = file_info.get("path", "")
                content = get_file_content(name, file_path)
                if content:
                    file_patterns = extract_patterns(content, lang, file_path)
                    patterns.extend(file_patterns)

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
