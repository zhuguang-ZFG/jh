"""Code quality metrics endpoint — track pre/post change analysis."""
import json
import time
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict
from .db import get_conn
from .models import ApiResponse

router = APIRouter(prefix="/quality", tags=["quality"])


class QualitySnapshot(BaseModel):
    session_id: str
    phase: str  # "before" or "after"
    snapshot: Dict[str, Any]  # filepath -> metrics
    delta: Optional[Dict[str, Any]] = None  # only in "after" phase


class QualityReport(BaseModel):
    session_id: str
    delta: Dict[str, Any]
    report: str


@router.post("/snapshot")
def save_snapshot(q: QualitySnapshot):
    conn = get_conn()
    now = time.time()
    try:
        conn.execute(
            """INSERT INTO quality_snapshots (session_id, phase, snapshot, delta, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                q.session_id,
                q.phase,
                json.dumps(q.snapshot),
                json.dumps(q.delta) if q.delta else "{}",
                now,
            ),
        )
        conn.commit()
        return ApiResponse(ok=True, message="Quality snapshot saved")
    except Exception as e:
        return ApiResponse(ok=False, message=str(e))


@router.get("/history")
def quality_history(session_id: str = "", limit: int = 20):
    conn = get_conn()
    if session_id:
        rows = conn.execute(
            """SELECT * FROM quality_snapshots
               WHERE session_id=? ORDER BY created_at DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM quality_snapshots
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.get("/trends")
def quality_trends(days: int = 7):
    conn = get_conn()
    cutoff = time.time() - days * 86400
    rows = conn.execute(
        """SELECT session_id, delta, created_at
           FROM quality_snapshots
           WHERE phase='after' AND created_at > ?
           ORDER BY created_at""",
        (cutoff,),
    ).fetchall()

    trends = []
    for r in rows:
        try:
            delta = json.loads(r["delta"])
            summary = delta.get("summary", {})
            trends.append({
                "session_id": r["session_id"],
                "quality_score": summary.get("quality_score", 0),
                "complexity_delta": summary.get("complexity_delta", 0),
                "loc_delta": summary.get("loc_delta", 0),
                "syntax_errors": summary.get("syntax_errors_introduced", 0),
                "created_at": r["created_at"],
            })
        except (json.JSONDecodeError, TypeError):
            pass

    # Calculate overall stats
    if trends:
        avg_score = sum(t["quality_score"] for t in trends) / len(trends)
        total_complexity_delta = sum(t["complexity_delta"] for t in trends)
        total_syntax_errors = sum(t["syntax_errors"] for t in trends)
    else:
        avg_score = 0
        total_complexity_delta = 0
        total_syntax_errors = 0

    return ApiResponse(ok=True, data={
        "trends": trends,
        "stats": {
            "sessions_analyzed": len(trends),
            "avg_quality_score": round(avg_score, 1),
            "total_complexity_delta": total_complexity_delta,
            "total_syntax_errors": total_syntax_errors,
        },
    })


@router.post("/report")
def save_report(r: QualityReport):
    conn = get_conn()
    now = time.time()
    try:
        conn.execute(
            """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "qr_" + r.session_id[:8],
                "quality_analyzer",
                "quality_report",
                "ok",
                json.dumps({"session_id": r.session_id, "report": r.report, "delta_summary": r.delta.get("summary", {})}),
                now,
            ),
        )
        conn.commit()
        return ApiResponse(ok=True, message="Quality report saved")
    except Exception as e:
        return ApiResponse(ok=False, message=str(e))
