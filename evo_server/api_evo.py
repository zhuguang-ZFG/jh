"""Evolution proposals endpoint."""
import json
import time
from typing import List
from fastapi import APIRouter
from .db import get_conn
from .models import EvoApprove, ApiResponse
from .claude_md_generator import generate_claude_md

router = APIRouter(prefix="/evolutions", tags=["evolutions"])


@router.get("/")
def list_evolutions(status: str = "proposed", limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM evolutions WHERE status=? ORDER BY created_at DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.post("/{evo_id}/approve")
def approve_evolution(evo_id: int, a: EvoApprove):
    conn = get_conn()
    row = conn.execute("SELECT id, status FROM evolutions WHERE id=?", (evo_id,)).fetchone()
    if not row:
        return ApiResponse(ok=False, message="Evolution not found")
    if row["status"] != "proposed":
        return ApiResponse(ok=False, message=f"Already {row['status']}")

    new_status = "approved" if a.approved else "rejected"
    now = time.time()
    conn.execute(
        "UPDATE evolutions SET status=?, resolved_at=? WHERE id=?",
        (new_status, now, evo_id),
    )
    # Log event
    import uuid
    conn.execute(
        """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4())[:8],
            "telegram",
            "evolution_review",
            new_status,
            json.dumps({"evo_id": evo_id, "note": a.note}),
            now,
        ),
    )
    conn.commit()
    return ApiResponse(ok=True, message=f"Evolution {new_status}")


@router.post("/{evo_id}/apply")
def apply_evolution_endpoint(evo_id: int):
    """Apply an approved evolution — creates skills/patterns/rules."""
    from .evolution_engine import apply_evolution
    result = apply_evolution(evo_id)
    return ApiResponse(ok=True, message=result)


@router.post("/create")
def create_evolution(category: str, summary: str, evidence_ids: List[str] = [], confidence: float = 0.0):
    """Create a new evolution proposal (called by evolution engine)."""
    conn = get_conn()
    import uuid
    import hashlib
    now = time.time()
    evo_key = hashlib.sha256(f"{category}:{summary}:{now}".encode()).hexdigest()[:16]
    try:
        conn.execute(
            """INSERT INTO evolutions (evo_key, category, summary, evidence_ids, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (evo_key, category, summary, json.dumps(evidence_ids), confidence, now),
        )
        conn.commit()
        return ApiResponse(ok=True, data={"evo_key": evo_key})
    except conn.IntegrityError:
        return ApiResponse(ok=False, message="Duplicate proposal")


@router.get("/claude-md")
def get_claude_md():
    """Generate CLAUDE.md from accumulated session experience."""
    result = generate_claude_md()
    return ApiResponse(ok=True, data={"content": result["content"], "stats": result["stats"]})
