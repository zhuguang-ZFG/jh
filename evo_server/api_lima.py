"""LLM integration endpoint (LongCat API, formerly LiMa)."""
import json
import time
from fastapi import APIRouter, Body
from .db import get_conn
from .models import ApiResponse

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
        suggestions = json.loads(response)
    except json.JSONDecodeError:
        pass

    # Store suggestions as meta_rules
    conn = get_conn()
    now = time.time()
    if suggestions:
        key = "llm_suggestions"
        value = json.dumps(suggestions, ensure_ascii=False)
        try:
            conn.execute(
                """INSERT INTO meta_rules (rule_key, rule_value, category, created_at)
                   VALUES (?, ?, 'llm_sync', ?)""",
                (key, value, now),
            )
        except Exception:
            conn.execute(
                "UPDATE meta_rules SET rule_value=?, created_at=? WHERE rule_key=?",
                (value, now, key),
            )

        # Log event
        import uuid
        conn.execute(
            """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
               VALUES (?, 'llm', 'knowledge_sync', 'success', ?, ?)""",
            (str(uuid.uuid4())[:8], json.dumps({"suggestions": len(suggestions)}), now),
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
