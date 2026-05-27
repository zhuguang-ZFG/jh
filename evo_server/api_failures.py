"""Failure patterns, conventions, and git patterns API."""
import hashlib
import time
from typing import Optional
from fastapi import APIRouter, Body, BackgroundTasks
from .db import get_conn
from .models import ApiResponse
from .vec_search import vec_search

router = APIRouter(prefix="/learn", tags=["learning"])


def _sync_failure_embedding(conn, row_id, error_type, description, fix_suggestion, domain, fix_code=""):
    try:
        from .vec_sync import sync_row_embedding
        sync_row_embedding(conn, "failure_patterns", row_id, {
            "error_type": error_type, "description": description,
            "fix_suggestion": fix_suggestion, "fix_code": fix_code, "domain": domain,
        })
    except Exception:
        pass


# ── Failure patterns ────────────────────────────────────────────

@router.post("/failure")
def record_failure(
    background_tasks: BackgroundTasks,
    domain: str = Body(...),
    error_type: str = Body(...),
    description: str = Body(...),
    file_context: str = Body(""),
    fix_suggestion: str = Body(""),
):
    """Record a failure pattern (from quality drops, syntax errors, etc.)."""
    conn = get_conn()
    now = time.time()
    key = hashlib.sha256(f"{domain}:{error_type}:{description[:80]}".encode()).hexdigest()[:16]
    try:
        conn.execute(
            """INSERT INTO failure_patterns
               (pattern_key, domain, error_type, description, file_context, fix_suggestion, created_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, domain, error_type, description, file_context, fix_suggestion, now, now),
        )
        row_id = conn.execute("SELECT id FROM failure_patterns WHERE pattern_key=?", (key,)).fetchone()["id"]
        _sync_failure_embedding(conn, row_id, error_type, description, fix_suggestion, domain)
    except conn.IntegrityError:
        conn.execute(
            """UPDATE failure_patterns SET occurrences=occurrences+1, last_seen=?,
               description=CASE WHEN LENGTH(?) > LENGTH(description) THEN ? ELSE description END
               WHERE pattern_key=?""",
            (now, description, description, key),
        )
        row_id = conn.execute("SELECT id FROM failure_patterns WHERE pattern_key=?", (key,)).fetchone()["id"]
        _sync_failure_embedding(conn, row_id, error_type, description, fix_suggestion, domain)
    conn.commit()

    # Async: generate concrete fix code if not already present
    existing = conn.execute(
        "SELECT fix_code FROM failure_patterns WHERE pattern_key=?", (key,)
    ).fetchone()
    if existing and not existing["fix_code"]:
        background_tasks.add_task(
            _generate_and_store_fix, key, error_type, description, file_context, domain
        )

    return ApiResponse(ok=True, data={"pattern_key": key})


async def _generate_and_store_fix(pattern_key, error_type, description, file_context, domain):
    """Background task: generate fix code and store it."""
    import logging
    logger = logging.getLogger("evo.fix_generator")
    try:
        from .fix_generator import generate_fix
        fix_code, fix_type = await generate_fix(error_type, description, file_context, domain)
        if fix_code:
            conn = get_conn()
            conn.execute(
                "UPDATE failure_patterns SET fix_code=?, fix_type=? WHERE pattern_key=?",
                (fix_code, fix_type, pattern_key),
            )
            conn.commit()
            logger.info(f"Auto-generated fix for {pattern_key}: type={fix_type}")
    except Exception as e:
        logger.warning(f"Fix generation failed for {pattern_key}: {e}")


@router.post("/failures/{pattern_key}/regenerate-fix")
async def regenerate_fix(pattern_key: str):
    """Manually trigger fix regeneration for a failure pattern."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM failure_patterns WHERE pattern_key=?", (pattern_key,)
    ).fetchone()
    if not row:
        return ApiResponse(ok=False, error="Pattern not found")

    from .fix_generator import generate_fix
    fix_code, fix_type = await generate_fix(
        row["error_type"], row["description"], row["file_context"], row["domain"]
    )
    if fix_code:
        conn.execute(
            "UPDATE failure_patterns SET fix_code=?, fix_type=? WHERE pattern_key=?",
            (fix_code, fix_type, pattern_key),
        )
        conn.commit()
        return ApiResponse(ok=True, data={
            "pattern_key": pattern_key, "fix_code": fix_code, "fix_type": fix_type
        })
    return ApiResponse(ok=False, error="Fix generation failed")


@router.get("/failures")
def list_failures(domain="", error_type="", limit=20):
    conn = get_conn()
    conditions = ["1=1"]
    params = []
    if domain:
        conditions.append("domain=?")
        params.append(domain)
    if error_type:
        conditions.append("error_type=?")
        params.append(error_type)
    params.append(limit)
    rows = conn.execute(
        "SELECT * FROM failure_patterns WHERE {} ORDER BY occurrences DESC, last_seen DESC LIMIT ?".format(
            " AND ".join(conditions)
        ),
        params,
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.post("/failures/relevant")
def relevant_failures(
    context: str = Body(""),
    limit: int = Body(5),
):
    """Get failure patterns relevant to a context string (vector search)."""
    conn = get_conn()
    if not context:
        rows = conn.execute(
            "SELECT * FROM failure_patterns ORDER BY occurrences DESC LIMIT ?", (limit,)
        ).fetchall()
        return ApiResponse(ok=True, data=[dict(r) for r in rows])

    results = vec_search(conn, "failure_patterns", context, limit=limit)
    # Remove _score from output
    return ApiResponse(ok=True, data=[{k: v for k, v in r.items() if k != "_score"} for r in results])


@router.get("/failures/stats")
def failure_stats():
    """Get failure statistics by type and domain."""
    conn = get_conn()
    by_type = conn.execute(
        "SELECT error_type, COUNT(*) as count, SUM(occurrences) as total_occurrences "
        "FROM failure_patterns GROUP BY error_type ORDER BY total_occurrences DESC"
    ).fetchall()
    by_domain = conn.execute(
        "SELECT domain, COUNT(*) as count, SUM(occurrences) as total_occurrences "
        "FROM failure_patterns GROUP BY domain ORDER BY total_occurrences DESC"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) c FROM failure_patterns").fetchone()["c"]
    return ApiResponse(ok=True, data={
        "total": total,
        "by_type": [dict(r) for r in by_type],
        "by_domain": [dict(r) for r in by_domain],
    })


# ── Conventions ─────────────────────────────────────────────────

@router.post("/convention")
def add_convention(
    category: str = Body(...),
    rule: str = Body(...),
    example: str = Body(""),
    confidence: float = Body(0.5),
):
    conn = get_conn()
    now = time.time()
    key = hashlib.sha256(f"{category}:{rule[:80]}".encode()).hexdigest()[:16]
    try:
        conn.execute(
            """INSERT INTO conventions (convention_key, category, rule, example, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, category, rule, example, confidence, now),
        )
    except conn.IntegrityError:
        conn.execute(
            "UPDATE conventions SET confidence=?, rule=? WHERE convention_key=?",
            (confidence, rule, key),
        )
    conn.commit()
    return ApiResponse(ok=True, data={"convention_key": key})


@router.get("/conventions")
def list_conventions(category="", limit=20):
    conn = get_conn()
    if category:
        rows = conn.execute(
            "SELECT * FROM conventions WHERE category=? ORDER BY confidence DESC LIMIT ?",
            (category, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conventions ORDER BY confidence DESC LIMIT ?", (limit,)
        ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


# ── Git patterns ────────────────────────────────────────────────

@router.post("/git-pattern")
def add_git_pattern(
    pattern_type: str = Body(...),
    description: str = Body(...),
    example: str = Body(""),
    repo: str = Body(""),
    confidence: float = Body(0.5),
):
    conn = get_conn()
    now = time.time()
    key = hashlib.sha256(f"{pattern_type}:{description[:80]}".encode()).hexdigest()[:16]
    try:
        conn.execute(
            """INSERT INTO git_patterns (pattern_key, pattern_type, description, example, repo, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, pattern_type, description, example, repo, confidence, now),
        )
    except conn.IntegrityError:
        pass
    conn.commit()
    return ApiResponse(ok=True, data={"pattern_key": key})


@router.get("/git-patterns")
def list_git_patterns(pattern_type="", limit=20):
    conn = get_conn()
    if pattern_type:
        rows = conn.execute(
            "SELECT * FROM git_patterns WHERE pattern_type=? ORDER BY confidence DESC LIMIT ?",
            (pattern_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM git_patterns ORDER BY confidence DESC LIMIT ?", (limit,)
        ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])
