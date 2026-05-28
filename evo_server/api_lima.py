"""LLM integration endpoint (LongCat API, formerly LiMa)."""
import json as _json
import time
import re
import logging
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from .db import get_conn
from .models import ApiResponse

logger = logging.getLogger("evo.lima")
router = APIRouter(prefix="/lima", tags=["llm"])


@router.post("/sync")
async def trigger_sync():
    """Query LLM for knowledge and store insights."""
    from .llm_bridge import chat, export_evo_knowledge

    # Export current knowledge to give LLM context
    knowledge = export_evo_knowledge()
    skills_summary = ", ".join(
        f"{s['name']}[{s['domain']}] w={s['weight']}"
        for s in knowledge["top_skills"][:5]
    )

    # Ask LLM for improvement suggestions
    response = await chat(
        f"Given these programming skills: {skills_summary}\n"
        f"Suggest 3 concrete improvements or new skills to learn. "
        f"Return JSON array: [{{category, summary, confidence}}]",
        system="Return only valid JSON array, no explanation.",
    )

    suggestions = []
    try:
        suggestions = _json.loads(response)
    except _json.JSONDecodeError:
        pass

    # Store suggestions as meta_rules
    conn = get_conn()
    now = time.time()
    if suggestions:
        key = "llm_suggestions"
        value = _json.dumps(suggestions, ensure_ascii=False)
        try:
            conn.execute(
                """INSERT INTO meta_rules (rule_key, rule_value, category, created_at)
                   VALUES (?, ?, 'llm_sync', ?)""",
                (key, value, now),
            )
        except conn.IntegrityError:
            conn.execute(
                "UPDATE meta_rules SET rule_value=?, created_at=? WHERE rule_key=?",
                (value, now, key),
            )

        # Log event
        import uuid
        conn.execute(
            """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
               VALUES (?, 'llm', 'knowledge_sync', 'success', ?, ?)""",
            (str(uuid.uuid4())[:8], _json.dumps({"suggestions": len(suggestions)}), now),
        )
        conn.commit()

    return ApiResponse(ok=True, data={
        "suggestions": suggestions,
        "knowledge_exported": knowledge["skills_count"],
    })


@router.get("/stats")
async def get_llm_stats():
    """Get LLM integration status."""
    from .llm_bridge import fetch_llm_stats
    stats = await fetch_llm_stats()

    conn = get_conn()
    last_sync = conn.execute(
        "SELECT recorded_at FROM events WHERE source='llm' AND event_type='knowledge_sync' ORDER BY recorded_at DESC LIMIT 1"
    ).fetchone()

    return ApiResponse(ok=True, data={
        **stats,
        "last_sync": last_sync["recorded_at"] if last_sync else None,
    })


@router.get("/export")
def export_knowledge():
    """Export evo-server knowledge for LLM context."""
    from .llm_bridge import export_evo_knowledge
    return ApiResponse(ok=True, data=export_evo_knowledge())


@router.post("/discover")
async def trigger_discovery():
    """Manually trigger cross-session pattern discovery."""
    from .evolution_engine import run_cross_session_discovery
    result = await run_cross_session_discovery()
    return ApiResponse(ok=True, data=result)


@router.post("/digest")
async def trigger_digest():
    """Manually trigger nightly digest."""
    import importlib
    main_mod = importlib.import_module("evo_server.main")
    await main_mod._async_digest()
    return ApiResponse(ok=True, message="Digest sent")


class CorrectionIngest(BaseModel):
    corrections: list = Field(..., min_length=1, max_length=10)
    session_id: str = "unknown"


@router.post("/corrections")
async def ingest_corrections(req: CorrectionIngest):
    """Ingest user corrections from a session — extract structured rules via LLM.

    User corrections are the highest-quality signal in the entire system.
    Each correction ("don't do X, do Y") becomes a high-weight skill.
    """
    if not req.corrections:
        return ApiResponse(ok=True, data={"saved": 0, "reason": "empty"})

    from .llm_bridge import chat
    import hashlib as _hashlib

    # Build LLM prompt
    corrections_text = ""
    for i, c in enumerate(req.corrections):
        corrections_text += f"{i+1}. {c.get('raw_text', '')[:250]}\n"

    system = (
        "You are a software engineering knowledge extractor. The user has corrected "
        "Claude's behavior during a coding session. Extract structured rules from "
        "these corrections.\n\n"
        "For each correction, identify:\n"
        "- trigger: what was Claude doing or about to do wrong\n"
        "- correct_behavior: what the user wants Claude to do instead\n"
        "- domain: python|devops|general|api|testing etc.\n"
        "- name: short descriptive name for this rule\n\n"
        "Return JSON array only:\n"
        '[{"name": "...", "domain": "...", "trigger": "...", '
        '"correct_behavior": "...", "confidence": 0.0-1.0}]'
    )

    user_msg = (
        f"User corrections from coding session:\n{corrections_text}\n"
        "Extract structured rules from these corrections."
    )

    # Call LLM
    rules = []
    try:
        response = await chat(user_msg, system=system, temperature=0.2, max_backends=3)
        if response and not response.startswith("Error:"):
            try:
                data = _json.loads(response.strip())
                if isinstance(data, list):
                    rules = data
            except _json.JSONDecodeError:
                import re as _re2
                match = _re2.search(r"\[.*\]", response, re.DOTALL)
                if match:
                    try:
                        data = _json.loads(match.group())
                        if isinstance(data, list):
                            rules = data
                    except _json.JSONDecodeError:
                        pass
    except Exception as e:
        logger.warning("Correction LLM failed: %s", e)

    # Store as high-weight skills
    conn = get_conn()
    now = time.time()
    saved = 0
    for rule in rules[:5]:
        name = rule.get("name", "user_correction")[:100]
        domain = rule.get("domain", "general")
        trigger = rule.get("trigger", "")[:200]
        correct = rule.get("correct_behavior", "")[:300]
        confidence = rule.get("confidence", 0.8)

        sk = _hashlib.sha256(
            f"{name}:{domain}:{trigger[:80]}".encode()
        ).hexdigest()[:16]

        try:
            conn.execute(
                """INSERT INTO skills
                   (skill_key, name, domain, pattern, anti_patterns, weight,
                    use_count, success_count, created_at, last_used, source)
                   VALUES (?, ?, ?, ?, ?, 2.5, 0, 0, ?, 0, 'correction')""",
                (sk, name, domain, correct, trigger, now),
            )
            saved += 1
        except conn.IntegrityError:
            conn.execute(
                "UPDATE skills SET pattern=?, anti_patterns=?, weight=MAX(weight, 2.5),"
                "last_used=? WHERE skill_key=?",
                (correct, trigger, now, sk),
            )
            saved += 1

    if saved:
        conn.commit()

    logger.info(f"Corrections ingested: {saved} rules from {len(req.corrections)} raw")
    return ApiResponse(ok=True, data={"saved": saved})
