"""Session logging endpoint."""
import json
import time
from fastapi import APIRouter
from .db import get_conn
from .models import SessionLog, ApiResponse

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/log")
def log_session(s: SessionLog):
    conn = get_conn()
    now = time.time()
    try:
        conn.execute(
            """INSERT INTO sessions (session_id, tool, goal, outcome, changed_files,
                                     lessons, duration_sec, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.session_id,
                s.tool,
                s.goal,
                s.outcome,
                json.dumps(s.changed_files),
                s.lessons,
                s.duration_sec,
                now,
            ),
        )
        # Also log to events
        import uuid
        conn.execute(
            """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4())[:8],
                s.tool,
                "session_end",
                s.outcome,
                json.dumps({"session_id": s.session_id, "goal": s.goal}),
                now,
            ),
        )
        conn.commit()
        return ApiResponse(ok=True, message="Session logged")
    except conn.IntegrityError:
        return ApiResponse(ok=False, message="Duplicate session_id")


@router.get("/recent")
def recent_sessions(limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])
