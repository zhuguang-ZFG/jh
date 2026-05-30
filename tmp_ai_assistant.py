#!/usr/bin/env python3
"""AI Daily Assistant — uses free LLM backends to:
1. Scan embedded/tech news
2. Review your recent GitHub commits
3. Summarize and push to Telegram in Chinese

Run: python3.11 /opt/ai-assistant/daily.py
Cron: 0 9 * * * (every day at 9am UTC / 5pm Beijing)
"""
import os
import json
import time
import sqlite3
import subprocess
from pathlib import Path

# ── Config ──────────────────────────────────────────────────

TELEGRAM_BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER = os.getenv("TELEGRAM_OWNER_ID", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "zhuguang-ZFG/esp32S_XYZ"

LLM_BACKENDS = [
    # Free backends via scnet proxy (China)
    {"url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "model": "qwen3-235b", "key": "none"},
    {"url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "model": "deepseek-v4-flash", "key": "none"},
    {"url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "model": "qwen3-30b", "key": "none"},
    # Alibaba DashScope (free tier)
    {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "model": "qwen-turbo", "key": os.getenv("ALIBABA_API_KEY", "")},
    # Zhipu (free tier)
    {"url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4-flash", "key": os.getenv("ZHIPU_API_KEY", "")},
]

import urllib.request, urllib.error


def llm_chat(prompt, system="", temperature=0.3):
    """Call LLM backends in order until one succeeds."""
    for b in LLM_BACKENDS:
        if not b["key"] and b["key"] != "none":
            continue
        try:
            body = json.dumps({
                "model": b["model"],
                "messages": [
                    {"role": "system", "content": system or "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1024,
                "temperature": temperature,
            }).encode()
            req = urllib.request.Request(
                b["url"], data=body, method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {b['key']}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            continue
    return ""


def telegram_send(text):
    """Send message to Telegram."""
    if not TELEGRAM_BOT or not TELEGRAM_USER:
        print("[WARN] No Telegram config")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage"
    body = json.dumps({
        "chat_id": TELEGRAM_USER,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[WARN] Telegram send failed: {e}")


# ── Task 1: Tech News Digest ──────────────────────────────────

TECH_FEEDS = [
    # Embedded / IoT / ESP32 news
    "https://www.cnx-software.com/feed/",
    # Hacker News top stories
    "https://hnrss.org/best?count=5",
]


def fetch_rss(url, limit=5):
    """Fetch RSS feed titles and links."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
        # Simple XML parse (no lxml dependency)
        items = []
        for item_xml in xml.split("<item>")[1:limit+1]:
            title = ""
            link = ""
            if "<title>" in item_xml:
                title = item_xml.split("<title>")[1].split("</title>")[0].strip()
            if "<link>" in item_xml:
                link = item_xml.split("<link>")[1].split("</link>")[0].strip()
            if title:
                items.append({"title": title, "link": link})
        return items
    except Exception:
        return []


def task_news_digest():
    """Fetch tech news, summarize in Chinese."""
    print("[1/3] Scanning tech news...")
    all_items = []
    for feed in TECH_FEEDS:
        all_items.extend(fetch_rss(feed, limit=5))

    if not all_items:
        return ""

    titles_text = "\n".join(f"- {i['title']}" for i in all_items[:10])
    result = llm_chat(
        f"以下是今天的技术新闻标题，请用中文简要总结最重要的3-5条，每条1-2句话，"
        f"重点关注嵌入式/IoT/ESP32/AI相关：\n\n{titles_text}",
        temperature=0.3,
    )
    return result


# ── Task 2: GitHub Commit Review ──────────────────────────────

def fetch_recent_commits():
    """Fetch recent GitHub commits via API."""
    if not GITHUB_TOKEN:
        return []
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/commits?per_page=5"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "User-Agent": "ai-assistant",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            commits = json.loads(resp.read())
        results = []
        for c in commits:
            msg = c["commit"]["message"].split("\n")[0][:100]
            date = c["commit"]["author"]["date"][:10]
            results.append(f"[{date}] {msg}")
        return results
    except Exception:
        return []


def task_commit_review():
    """Review recent commits with LLM."""
    print("[2/3] Reviewing recent commits...")
    commits = fetch_recent_commits()
    if not commits:
        return ""

    commits_text = "\n".join(commits)
    result = llm_chat(
        f"以下是 {GITHUB_REPO} 最近的代码提交，请用中文简要分析：\n"
        f"1. 主要改动方向\n"
        f"2. 有没有潜在问题或遗漏\n"
        f"3. 下一步建议\n\n{commits_text}",
        temperature=0.3,
    )
    return result


# ── Task 3: ESP32 Ecosystem Scan ──────────────────────────────

def task_esp32_scan():
    """Scan ESP32 ecosystem news from GitHub."""
    print("[3/3] Scanning ESP32 ecosystem...")
    try:
        url = "https://api.github.com/search/repositories?q=esp32+language:c+pushed:>2025-01-01&sort=updated&per_page=5"
        req = urllib.request.Request(url, headers={"User-Agent": "ai-assistant"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        repos = []
        for r in data.get("items", []):
            repos.append(f"- {r['full_name']} (★{r['stargazers_count']}): {r['description'] or 'no desc'}")
        if not repos:
            return ""
        repos_text = "\n".join(repos)
        result = llm_chat(
            f"以下是最近活跃的 ESP32 开源项目，请用中文简要介绍最有价值的2-3个，"
            f"说明为什么值得关注：\n\n{repos_text}",
            temperature=0.3,
        )
        return result
    except Exception:
        return ""


# ── Main ──────────────────────────────────────────────────────

def main():
    print("=" * 40)
    print(f"AI Daily Assistant — {time.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 40)

    news = task_news_digest()
    commits = task_commit_review()
    esp32 = task_esp32_scan()

    # Build message
    parts = ["*AI 日报*\n"]

    if news:
        parts.append("*技术动态*\n" + news + "\n")

    if commits:
        parts.append("*代码提交回顾*\n" + commits + "\n")

    if esp32:
        parts.append("*ESP32 生态*\n" + esp32 + "\n")

    if len(parts) == 1:
        parts.append("今日暂无新动态")

    message = "\n".join(parts)

    # Truncate for Telegram limit (4096 chars)
    if len(message) > 4000:
        message = message[:4000] + "\n...(已截断)"

    print("\n" + message)
    telegram_send(message)
    print("\n[OK] Sent to Telegram")


if __name__ == "__main__":
    main()
