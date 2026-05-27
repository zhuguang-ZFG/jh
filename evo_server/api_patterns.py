"""Patterns learned from open-source projects."""
import hashlib
import time
from fastapi import APIRouter
from .db import get_conn
from .models import PatternLearn, ApiResponse

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.get("/")
def list_patterns(domain: str = "", limit: int = 50):
    conn = get_conn()
    if domain:
        rows = conn.execute(
            "SELECT * FROM patterns WHERE domain=? ORDER BY confidence DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM patterns ORDER BY confidence DESC LIMIT ?", (limit,)
        ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.post("/learn")
def learn_pattern(p: PatternLearn):
    conn = get_conn()
    now = time.time()
    pattern_key = hashlib.sha256(f"{p.domain}:{p.name}".encode()).hexdigest()[:16]
    try:
        conn.execute(
            """INSERT INTO patterns (pattern_key, name, domain, description,
                                     code_example, source_repo, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pattern_key, p.name, p.domain, p.description,
             p.code_example, p.source_repo, p.confidence, now),
        )
        conn.commit()
        return ApiResponse(ok=True, message=f"Learned pattern: {p.name}", data={"pattern_key": pattern_key})
    except conn.IntegrityError:
        conn.execute(
            "UPDATE patterns SET description=?, confidence=MAX(confidence, ?), last_used=? WHERE pattern_key=?",
            (p.description, p.confidence, now, pattern_key),
        )
        conn.commit()
        return ApiResponse(ok=True, message=f"Updated pattern: {p.name}", data={"pattern_key": pattern_key})
