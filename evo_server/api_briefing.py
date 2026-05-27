"""Pre-session briefing API — inject relevant knowledge before coding."""
import json
import time
from fastapi import APIRouter, Body
from .db import get_conn
from .models import ApiResponse
from .vec_search import vec_search

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.post("")
def create_briefing(
    task_summary: str = Body(...),
    domain: str = Body(""),
    limit: int = Body(3),
):
    """Generate a knowledge briefing for a coding task."""
    conn = get_conn()
    now = time.time()

    # Vector search for relevant skills
    skills = vec_search(conn, "skills", task_summary, limit=limit,
                        min_weight=0.3, domain=domain)

    # Vector search for relevant patterns
    patterns = vec_search(conn, "patterns", task_summary, limit=limit,
                          min_weight=0.3, domain=domain)

    # Vector search for relevant failures
    failures = vec_search(conn, "failure_patterns", task_summary, limit=limit)

    # Generate warnings from failures
    warnings = []
    for f in failures:
        fix = f.get("fix_suggestion", "")
        if fix:
            warnings.append(f"⚠️ {f.get('error_type', '?')}: {fix[:100]}")

    # Clean up _score from output (internal field)
    def clean(d):
        return {k: v for k, v in d.items() if k != "_score"}

    briefing = {
        "task_summary": task_summary,
        "relevant_skills": [clean(s) for s in skills],
        "relevant_patterns": [clean(p) for p in patterns],
        "relevant_failures": [clean(f) for f in failures],
        "warnings": warnings,
    }

    # Save to DB
    conn.execute(
        "INSERT INTO briefings (task_summary, relevant_skills, relevant_patterns, "
        "relevant_failures, warnings, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            task_summary,
            json.dumps(briefing["relevant_skills"], ensure_ascii=False),
            json.dumps(briefing["relevant_patterns"], ensure_ascii=False),
            json.dumps(briefing["relevant_failures"], ensure_ascii=False),
            json.dumps(warnings, ensure_ascii=False),
            now,
        ),
    )
    conn.commit()

    return ApiResponse(ok=True, data=briefing)


@router.get("/recent")
def recent_briefings(limit: int = 10):
    """Get recent briefings."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM briefings ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])
