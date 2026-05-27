"""LLM bridge — multi-backend with free-first fallback chain.

Priority order:
1. Free no-key backends (scnet, unclose, pollinations, llm7, chat_ubi)
2. API key backends with free tier (Zhipu, Alibaba, CF Workers AI)
3. OpenRouter free tier (:free suffix)
4. LongCat API (paid fallback)
"""
import time
import json
import logging
import random
from typing import Optional, List, Dict
import httpx
from .db import get_conn
from . import config

logger = logging.getLogger("evo.llm_bridge")


# ── Backend registry (free-first) ────────────────────────────────
BACKENDS = [
    # Tier 1: Free, no key, verified working from CN
    # SCNet 国家超算互联网 (scnet.cn, 免费5模型, 通过 CF Worker 代理)
    {"name": "scnet_qwen30b", "url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "key": "none", "model": "qwen3-30b", "fmt": "openai", "timeout": 30},
    {"name": "scnet_ds_flash", "url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "key": "none", "model": "deepseek-v4-flash", "fmt": "openai", "timeout": 30},
    {"name": "scnet_minimax", "url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "key": "none", "model": "minimax-m2.5", "fmt": "openai", "timeout": 30},
    {"name": "scnet_qwen235b", "url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "key": "none", "model": "qwen3-235b", "fmt": "openai", "timeout": 45},
    {"name": "scnet_ds_pro", "url": "https://scnet.zhuguang.ccwu.cc/v1/chat/completions", "key": "none", "model": "deepseek-v4-pro", "fmt": "openai", "timeout": 90},
    # 其他免费后端
    {"name": "unclose_hermes", "url": "https://hermes.ai.unturf.com/v1/chat/completions", "key": "none", "model": "adamo1139/Hermes-3-Llama-3.1-8B-FP8-Dynamic", "fmt": "openai", "timeout": 15},
    {"name": "pollinations", "url": "https://text.pollinations.ai/openai/chat/completions", "key": "none", "model": "openai", "fmt": "openai", "timeout": 30},
    {"name": "llm7", "url": "https://api.llm7.io/v1/chat/completions", "key": "none", "model": "auto", "fmt": "openai", "timeout": 20},
    {"name": "chat_ubi", "url": "https://ch.at/v1/chat/completions", "key": "none", "model": "gpt-3", "fmt": "openai", "timeout": 20},

    # Tier 1.5: API key backends (free tier, verified working from CN)
    {"name": "zhipu_glm4flash", "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "key": config.ZHIPU_API_KEY, "model": "glm-4-flash", "fmt": "openai", "timeout": 30},
    {"name": "alibaba_qwen_turbo", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "key": config.ALIBABA_API_KEY, "model": "qwen-turbo", "fmt": "openai", "timeout": 30},
    {"name": "cf_llama31_8b", "url": f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}/ai/v1/chat/completions", "key": config.CF_API_KEY, "model": "@cf/meta/llama-3.1-8b-instruct", "fmt": "openai", "timeout": 30},

    # Tier 2: OpenRouter free tier (:free suffix)
    {"name": "or_qwen3_coder", "url": "https://openrouter.ai/api/v1/chat/completions", "key": config.OPENROUTER_API_KEY, "model": "qwen/qwen3-coder:free", "fmt": "openai", "timeout": 60},
    {"name": "or_deepseek", "url": "https://openrouter.ai/api/v1/chat/completions", "key": config.OPENROUTER_API_KEY, "model": "deepseek/deepseek-v4-flash:free", "fmt": "openai", "timeout": 60},
    {"name": "or_gptoss", "url": "https://openrouter.ai/api/v1/chat/completions", "key": config.OPENROUTER_API_KEY, "model": "openai/gpt-oss-120b:free", "fmt": "openai", "timeout": 60},
    {"name": "or_llama70b", "url": "https://openrouter.ai/api/v1/chat/completions", "key": config.OPENROUTER_API_KEY, "model": "meta-llama/llama-3.3-70b-instruct:free", "fmt": "openai", "timeout": 45},

    # Tier 3: Paid fallback (LongCat)
    {"name": "longcat_chat", "url": "https://api.longcat.chat/anthropic/v1/messages", "key": "ak_2Ra7Py0fN6PT3Ul5Dj8OZ0D88iY2Q", "model": "LongCat-Flash-Chat", "fmt": "anthropic", "timeout": 60},
    {"name": "longcat_thinking", "url": "https://api.longcat.chat/anthropic/v1/messages", "key": "ak_2Ra7Py0fN6PT3Ul5Dj8OZ0D88iY2Q", "model": "LongCat-Flash-Thinking-2601", "fmt": "anthropic", "timeout": 60},
]


def _build_headers(backend):
    """Build request headers based on backend format."""
    if backend["fmt"] == "anthropic":
        return {
            "Authorization": f"Bearer {backend['key']}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
    return {
        "Authorization": f"Bearer {backend['key']}",
        "Content-Type": "application/json",
    }


def _build_payload(backend, message, system="", temperature=0.3):
    """Build request payload based on backend format."""
    if backend["fmt"] == "anthropic":
        payload = {
            "model": backend["model"],
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": message}],
        }
        if system:
            payload["system"] = system
        payload["temperature"] = temperature
        return payload

    # OpenAI format
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": message})
    payload = {
        "model": backend["model"],
        "messages": messages,
        "max_tokens": 2048,
        "temperature": temperature,
    }
    return payload


def _parse_response(backend, data):
    """Parse response based on backend format."""
    if backend["fmt"] == "anthropic":
        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "")
        return str(data)

    # OpenAI format
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return str(data)


async def chat(message: str, system: str = "", temperature: float = 0.3, max_backends: int = 5) -> str:
    """Send a message to LLM with free-first fallback chain.

    Tries up to max_backends backends in priority order.
    Returns first successful response, or error from last attempt.
    """
    last_error = None

    for backend in BACKENDS[:max_backends]:
        try:
            headers = _build_headers(backend)
            payload = _build_payload(backend, message, system, temperature)

            async with httpx.AsyncClient(timeout=backend.get("timeout", 30)) as client:
                r = await client.post(backend["url"], json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                response = _parse_response(backend, data)
                if response and len(response) > 10:
                    logger.debug(f"LLM OK via {backend['name']}")
                    return response
        except Exception as e:
            last_error = e
            logger.debug(f"LLM {backend['name']} failed: {e}")
            continue

    return f"Error: all backends failed. Last: {last_error}"


# ── Knowledge query (for CLI hooks) ────────────────────────

async def query_knowledge(scenario: str, domain: str = "") -> str:
    """Query LLM for knowledge relevant to a coding scenario."""
    system = (
        "You are a programming knowledge assistant. "
        "Given a coding scenario, provide concise, actionable tips and patterns. "
        "Return 3-5 bullet points, each under 120 chars. No preamble."
    )
    llm_response = await chat(
        f"Coding scenario: {scenario}\nDomain: {domain or 'general'}\n"
        f"Provide relevant patterns, pitfalls, and best practices.",
        system=system,
    )

    lines = []
    if llm_response and not llm_response.startswith("Error:"):
        lines.append(f"[LLM Knowledge]")
        for line in llm_response.strip().split("\n"):
            line = line.strip()
            if line and len(line) > 5:
                lines.append(f"  {line}")

    conn = get_conn()
    local_skills = conn.execute(
        """SELECT name, domain, pattern, weight FROM skills
           WHERE (name LIKE ? OR pattern LIKE ? OR domain LIKE ?)
           AND weight > 0.3
           ORDER BY weight DESC LIMIT 5""",
        (f"%{scenario}%", f"%{scenario}%", f"%{domain}%" if domain else f"%{scenario}%",),
    ).fetchall()

    if local_skills:
        lines.append(f"[Local Skills — {len(local_skills)} results]")
        for s in local_skills:
            lines.append(f"  - [{s['domain']}] {s['name']} (w={s['weight']:.2f}): {s['pattern'][:100]}")

    return "\n".join(lines) if lines else ""


# ── Session analysis (for evolution engine) ────────────────

async def analyze_sessions(sessions_text: str) -> dict:
    """Use LLM to analyze session data and suggest improvements."""
    system = (
        "You are a programming evolution engine. Analyze coding session data "
        "and propose concrete improvements. Return JSON with keys: "
        "lessons (array of strings), proposals (array of {category, summary, confidence})."
    )
    response = await chat(
        f"Analyze these coding sessions and propose improvements:\n{sessions_text[:3000]}",
        system=system,
        temperature=0.2,
    )
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"lessons": [], "proposals": [], "raw": response[:500]}


# ── Context generation (for CLAUDE.md) ──────────────────────

async def generate_claude_md(skills: list, patterns: list, sessions: list) -> str:
    """Use LLM to generate a CLAUDE.md file from accumulated knowledge."""
    system = (
        "Generate a concise CLAUDE.md file for a coding project. "
        "Include: active domains, proven techniques, key skills, learned patterns. "
        "Format as Markdown. Under 2000 chars. No preamble."
    )
    knowledge = json.dumps({
        "skills": skills[:10],
        "patterns": patterns[:10],
        "recent_sessions": sessions[:5],
    }, ensure_ascii=False, default=str)

    response = await chat(
        f"Generate CLAUDE.md from this knowledge base:\n{knowledge[:3000]}",
        system=system,
    )
    return response if not response.startswith("Error:") else ""


# ── Stats (for Telegram /lima command) ──────────────────────

async def fetch_llm_stats() -> dict:
    """Return LLM integration status with backend info."""
    free_count = sum(1 for b in BACKENDS if b["key"] in ("none", "1"))
    return {
        "provider": "Multi-backend (free-first)",
        "total_backends": len(BACKENDS),
        "free_backends": free_count,
        "paid_backends": len(BACKENDS) - free_count,
        "status": "active",
        "fetched_at": time.time(),
    }


# ── Knowledge export summary ────────────────────────────────

def export_evo_knowledge() -> dict:
    """Export evo-server's high-value knowledge as a summary."""
    conn = get_conn()

    skills = conn.execute(
        "SELECT name, domain, weight, pattern FROM skills WHERE weight > 0.5 ORDER BY weight DESC LIMIT 20"
    ).fetchall()

    patterns = conn.execute(
        "SELECT name, domain, description, confidence FROM patterns WHERE confidence > 0.5 ORDER BY confidence DESC LIMIT 20"
    ).fetchall()

    evolutions = conn.execute(
        "SELECT category, summary, status FROM evolutions WHERE status IN ('approved', 'applied') ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    return {
        "source": "evo-server",
        "exported_at": time.time(),
        "skills_count": len(skills),
        "patterns_count": len(patterns),
        "evolutions_count": len(evolutions),
        "top_skills": [
            {"name": s["name"], "domain": s["domain"], "weight": round(s["weight"], 2)}
            for s in skills
        ],
        "top_patterns": [
            {"name": p["name"], "domain": p["domain"], "confidence": round(p["confidence"], 2)}
            for p in patterns
        ],
    }
