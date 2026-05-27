"""Failure patterns, conventions, and git patterns API."""
import hashlib
import time
from typing import Optional
from fastapi import APIRouter, Body
from .db import get_conn
from .models import ApiResponse

router = APIRouter(prefix="/learn", tags=["learning"])


# ── Failure patterns ────────────────────────────────────────────

@router.post("/failure")
def record_failure(
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
    except conn.IntegrityError:
        conn.execute(
            """UPDATE failure_patterns SET occurrences=occurrences+1, last_seen=?,
               description=CASE WHEN LENGTH(?) > LENGTH(description) THEN ? ELSE description END
               WHERE pattern_key=?""",
            (now, description, description, key),
        )
    conn.commit()
    return ApiResponse(ok=True, data={"pattern_key": key})


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
    """Get failure patterns relevant to a context string (keyword match)."""
    conn = get_conn()
    if not context:
        rows = conn.execute(
            "SELECT * FROM failure_patterns ORDER BY occurrences DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        keywords = [w for w in context.lower().split() if len(w) >= 3][:5]
        if not keywords:
            rows = conn.execute(
                "SELECT * FROM failure_patterns ORDER BY occurrences DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            like_clauses = " OR ".join(["description LIKE ?" for _ in keywords])
            like_params = ["%{}%".format(k) for k in keywords]
            rows = conn.execute(
                "SELECT * FROM failure_patterns WHERE ({}) ORDER BY occurrences DESC LIMIT ?".format(like_clauses),
                like_params + [limit],
            ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


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
