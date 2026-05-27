"""LiMa cross-server sync endpoint."""
import json
import time
from fastapi import APIRouter
from .db import get_conn
from .models import ApiResponse

router = APIRouter(prefix="/lima", tags=["lima"])


@router.post("/sync")
async def trigger_sync():
    """Manually trigger LiMa knowledge sync."""
    from .lima_bridge import run_lima_sync
    result = await run_lima_sync()
    return ApiResponse(ok=True, data=result)


@router.get("/stats")
async def get_lima_stats():
    """Get current LiMa sync status from local DB."""
    conn = get_conn()
    stats_rule = conn.execute(
        "SELECT rule_value, created_at FROM meta_rules WHERE rule_key='lima_memory_stats'"
    ).fetchone()
    outcome_rule = conn.execute(
        "SELECT rule_value, created_at FROM meta_rules WHERE rule_key='lima_outcome_stats'"
    ).fetchone()

    last_sync = conn.execute(
        "SELECT recorded_at FROM events WHERE source='liMa' AND event_type='stats_sync' ORDER BY recorded_at DESC LIMIT 1"
    ).fetchone()

    return ApiResponse(ok=True, data={
        "memory_stats": json.loads(stats_rule["rule_value"]) if stats_rule else None,
        "outcome_stats": json.loads(outcome_rule["rule_value"]) if outcome_rule else None,
        "last_sync": last_sync["recorded_at"] if last_sync else None,
    })


@router.get("/export")
def export_knowledge():
    """Export evo-server knowledge for LiMa consumption."""
    from .lima_bridge import export_evo_knowledge
    return ApiResponse(ok=True, data=export_evo_knowledge())
