"""LiMa cross-server knowledge bridge.

Bidirectional knowledge sync between evo-server (119.45.204.198)
and LiMa server (api.donglicao.com).

LiMa API: OpenAI-compatible chat completions + MCP tools.
"""
import hashlib
import time
import json
import logging
from typing import List, Dict
import httpx
from .db import get_conn
from . import config

logger = logging.getLogger("evo.lima_bridge")

# LiMa API (OpenAI-compatible)
LIMA_API_BASE = "https://api.donglicao.com/v1"
LIMA_API_KEY = "aAN61guXCiv859KM0c7424927f7448BbA48a3725E50f22Bd"
LIMA_MODEL = "lima-1.3"

# Knowledge type mapping: LiMa memory_type → evo-server target table
# code_fact → skills (actionable knowledge)
# routing_lesson → skills (operational lessons)
# reference_pattern → patterns (design patterns)
# exchange/test_result → events (raw logs, skip import)
LIMA_TYPE_MAP = {
    "code_fact": "skill",
    "routing_lesson": "skill",
    "reference_pattern": "pattern",
    "security_lesson": "skill",
}


async def chat_with_lima(message: str, system: str = "") -> str:
    """Send a message to LiMa and get a response."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": message})

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{LIMA_API_BASE}/chat/completions",
                json={"model": LIMA_MODEL, "messages": messages, "temperature": 0.3},
                headers={
                    "Authorization": f"Bearer {LIMA_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LiMa chat failed: {e}")
        return f"Error: {e}"


# ── Stats fetch ──────────────────────────────────────────────

async def fetch_lima_stats() -> dict:
    """Fetch LiMa stats via chat API."""
    response = await chat_with_lima(
        "Return your current memory statistics as JSON. Include: total_memories, by_type (list of {type, count}), recent_count (last 24h).",
        system="You are a knowledge management system. Return only valid JSON, no explanation."
    )
    try:
        stats = json.loads(response)
    except json.JSONDecodeError:
        stats = {"raw": response, "total": 0}
    return {
        "memory": stats,
        "outcome": {"total": 0, "note": "outcome tracking via chat API"},
        "fetched_at": time.time(),
    }


# ── Knowledge search ────────────────────────────────────────

async def search_lima_knowledge(query, limit=10):
    # type: (str, int) -> List[Dict]
    """Search LiMa knowledge by querying the LLM."""
    response = await chat_with_lima(
        f"Search your knowledge for: {query}\nReturn up to {limit} relevant items as a JSON array. Each item: {{id, summary, timestamp, source_type}}.",
        system="You are a knowledge search engine. Return only valid JSON array, no explanation."
    )
    try:
        results = json.loads(response)
        if isinstance(results, list):
            return results[:limit]
    except json.JSONDecodeError:
        pass
    return [{"summary": response[:200], "source_type": "code_fact"}]


async def search_lima_docs(query, limit=5):
    # type: (str, int) -> List[Dict]
    """Search documentation knowledge."""
    response = await chat_with_lima(
        f"Find documentation about: {query}\nReturn up to {limit} items as JSON array. Each: {{title, snippet, url}}.",
        system="Return only valid JSON array, no explanation."
    )
    try:
        results = json.loads(response)
        if isinstance(results, list):
            return results[:limit]
    except json.JSONDecodeError:
        pass
    return []


# ── Knowledge import ────────────────────────────────────────

def _skill_key(name: str, domain: str) -> str:
    return hashlib.sha256(f"{domain}:{name}".encode()).hexdigest()[:16]


def _pattern_key(name: str, domain: str) -> str:
    return hashlib.sha256(f"pat:{domain}:{name}".encode()).hexdigest()[:16]


def _infer_domain(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("python", "fastapi", "uvicorn", "django", "flask")):
        return "python"
    if any(k in t for k in ("rust", "cargo", "tokio")):
        return "rust"
    if any(k in t for k in ("typescript", "react", "next.js", "vue")):
        return "frontend"
    if any(k in t for k in ("docker", "nginx", "deploy", "ci/cd")):
        return "devops"
    if any(k in t for k in ("sql", "database", "sqlite", "postgres")):
        return "data"
    if any(k in t for k in ("test", "pytest", "jest")):
        return "testing"
    if any(k in t for k in ("api", "rest", "graphql", "webhook")):
        return "api"
    return "general"


def import_stats(stats: dict) -> dict:
    """Import LiMa stats as evo-server meta_rules (L0)."""
    conn = get_conn()
    now = time.time()
    imported = 0

    # Store memory stats
    mem = stats.get("memory", {})
    if mem and "total" in mem:
        key = "lima_memory_stats"
        value = json.dumps(mem, ensure_ascii=False)
        try:
            conn.execute(
                """INSERT INTO meta_rules (rule_key, rule_value, category, created_at)
                   VALUES (?, ?, 'lima_sync', ?)""",
                (key, value, now),
            )
            imported += 1
        except Exception:
            conn.execute(
                "UPDATE meta_rules SET rule_value=?, created_at=? WHERE rule_key=?",
                (value, now, key),
            )
            imported += 1

    # Store outcome stats
    outcome = stats.get("outcome", {})
    if outcome and "total" in outcome:
        key = "lima_outcome_stats"
        value = json.dumps(outcome, ensure_ascii=False)
        try:
            conn.execute(
                """INSERT INTO meta_rules (rule_key, rule_value, category, created_at)
                   VALUES (?, ?, 'lima_sync', ?)""",
                (key, value, now),
            )
            imported += 1
        except Exception:
            conn.execute(
                "UPDATE meta_rules SET rule_value=?, created_at=? WHERE rule_key=?",
                (value, now, key),
            )
            imported += 1

    # Log sync event
    import uuid
    conn.execute(
        """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
           VALUES (?, 'liMa', 'stats_sync', 'success', ?, ?)""",
        (str(uuid.uuid4())[:8], json.dumps({"mem_total": mem.get("total", 0), "outcome_total": outcome.get("total", 0)}), now),
    )
    conn.commit()
    return {"imported": imported, "stats": stats}


def import_knowledge_items(items):
    # type: (List[Dict]) -> dict
    """Import knowledge items from LiMa into evo-server skills/patterns.

    Each item: {id, summary, timestamp, source_type?}
    """
    conn = get_conn()
    now = time.time()
    imported_skills = 0
    imported_patterns = 0
    skipped = 0

    for item in items:
        summary = item.get("summary", "").strip()
        if not summary or len(summary) < 10:
            skipped += 1
            continue

        source_type = item.get("source_type", "")
        target = LIMA_TYPE_MAP.get(source_type, "skill")
        domain = _infer_domain(summary)

        if target == "skill":
            key = _skill_key(summary[:80], domain)
            try:
                conn.execute(
                    """INSERT INTO skills (skill_key, name, domain, pattern, weight, created_at, source)
                       VALUES (?, ?, ?, ?, 0.8, ?, 'lima')""",
                    (key, summary[:80], domain, summary, now),
                )
                imported_skills += 1
            except Exception:
                # Update if exists
                conn.execute(
                    "UPDATE skills SET pattern=?, last_used=? WHERE skill_key=?",
                    (summary, now, key),
                )
                imported_skills += 1

        elif target == "pattern":
            key = _pattern_key(summary[:80], domain)
            try:
                conn.execute(
                    """INSERT INTO patterns (pattern_key, name, domain, description, source_repo, confidence, created_at)
                       VALUES (?, ?, ?, ?, 'liMa', 0.7, ?)""",
                    (key, summary[:80], domain, summary, now),
                )
                imported_patterns += 1
            except Exception:
                conn.execute(
                    "UPDATE patterns SET description=?, last_used=? WHERE pattern_key=?",
                    (summary, now, key),
                )
                imported_patterns += 1

    # Log import event
    import uuid
    conn.execute(
        """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
           VALUES (?, 'liMa', 'knowledge_import', 'success', ?, ?)""",
        (
            str(uuid.uuid4())[:8],
            json.dumps({"skills": imported_skills, "patterns": imported_patterns, "skipped": skipped}),
            now,
        ),
    )
    conn.commit()
    return {
        "imported_skills": imported_skills,
        "imported_patterns": imported_patterns,
        "skipped": skipped,
    }


# ── Knowledge export (evo → LiMa) ──────────────────────────

def export_evo_knowledge() -> dict:
    """Export evo-server's high-value knowledge as a summary for LiMa."""
    conn = get_conn()

    # Top skills by weight
    skills = conn.execute(
        "SELECT name, domain, weight, pattern FROM skills WHERE weight > 0.5 ORDER BY weight DESC LIMIT 20"
    ).fetchall()

    # High-confidence patterns
    patterns = conn.execute(
        "SELECT name, domain, description, confidence FROM patterns WHERE confidence > 0.5 ORDER BY confidence DESC LIMIT 20"
    ).fetchall()

    # Recent evolution insights
    evolutions = conn.execute(
        "SELECT category, summary, status FROM evolutions WHERE status IN ('approved', 'applied') ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    summary = {
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
        "recent_evolutions": [
            {"category": e["category"], "summary": e["summary"][:200], "status": e["status"]}
            for e in evolutions
        ],
    }
    return summary


# ── Full sync cycle ─────────────────────────────────────────

async def run_lima_sync() -> dict:
    """Full bidirectional sync cycle.

    1. Fetch LiMa stats → import as meta_rules
    2. Search LiMa for knowledge → import as skills/patterns
    3. Export evo-server summary → store for LiMa consumption
    """
    logger.info("Starting LiMa sync cycle")

    # 1. Stats sync
    stats = await fetch_lima_stats()
    stats_result = import_stats(stats)
    logger.info(f"Stats imported: {stats_result['imported']}")

    # 2. Knowledge import — search for different types
    all_items = []

    # Search for code facts
    code_facts = await search_lima_knowledge("code", limit=10)
    for item in code_facts:
        item["source_type"] = "code_fact"
    all_items.extend(code_facts)

    # Search for lessons
    lessons = await search_lima_knowledge("lesson", limit=10)
    for item in lessons:
        item["source_type"] = "routing_lesson"
    all_items.extend(lessons)

    # Search for patterns
    patterns = await search_lima_knowledge("pattern", limit=10)
    for item in patterns:
        item["source_type"] = "reference_pattern"
    all_items.extend(patterns)

    # Search for security
    security = await search_lima_knowledge("security", limit=10)
    for item in security:
        item["source_type"] = "security_lesson"
    all_items.extend(security)

    # Import all collected items
    if all_items:
        import_result = import_knowledge_items(all_items)
    else:
        import_result = {"imported_skills": 0, "imported_patterns": 0, "skipped": 0}

    # 3. Export evo-server knowledge
    export = export_evo_knowledge()

    result = {
        "stats": stats_result,
        "knowledge": import_result,
        "export": {
            "skills": export["skills_count"],
            "patterns": export["patterns_count"],
            "evolutions": export["evolutions_count"],
        },
        "synced_at": time.time(),
    }
    logger.info(f"LiMa sync complete: {result}")
    return result


# ── On-demand query (for CLI hooks) ────────────────────────

async def query_lima_for_context(scenario: str, domain: str = "") -> str:
    """Query LiMa knowledge relevant to a coding scenario.

    Returns a formatted context string for injection into CLI hooks.
    """
    # Search LiMa for relevant knowledge
    items = await search_lima_knowledge(scenario, limit=5)
    docs = await search_lima_docs(scenario, limit=3)

    lines = []
    if items:
        lines.append(f"[LiMa Knowledge — {len(items)} results]")
        for item in items:
            lines.append(f"  - {item.get('summary', '')[:120]}")

    if docs:
        lines.append(f"[LiMa Docs — {len(docs)} results]")
        for doc in docs:
            lines.append(f"  - {doc.get('title', '')}: {doc.get('snippet', '')[:100]}")

    if not lines:
        return ""

    # Also check local evo-server for relevant skills
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

    return "\n".join(lines)
