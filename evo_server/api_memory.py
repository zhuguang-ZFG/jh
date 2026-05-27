"""Memory CRUD endpoints (L0 meta_rules + L1 skills FTS)."""
import hashlib
import time
from fastapi import APIRouter, Depends
from .db import get_conn
from .models import MemoryQuery, MemoryAdd, ApiResponse

router = APIRouter(prefix="/memory", tags=["memory"])


def _skill_key(name: str, domain: str) -> str:
    return hashlib.sha256(f"{domain}:{name}".encode()).hexdigest()[:16]


@router.post("/query")
def query_memory(q: MemoryQuery):
    conn = get_conn()
    results = []

    # FTS search on skills
    if q.keyword:
        rows = conn.execute(
            """SELECT id, skill_key, name, domain, pattern, weight, use_count,
                      source, created_at, last_used
               FROM skills
               WHERE name LIKE ? OR pattern LIKE ? OR domain LIKE ?
               ORDER BY weight DESC
               LIMIT ?""",
            (f"%{q.keyword}%", f"%{q.keyword}%", f"%{q.domain}%" if q.domain else f"%{q.keyword}%", q.limit),
        ).fetchall()
    elif q.domain:
        rows = conn.execute(
            """SELECT id, skill_key, name, domain, pattern, weight, use_count,
                      source, created_at, last_used
               FROM skills WHERE domain = ?
               ORDER BY weight DESC LIMIT ?""",
            (q.domain, q.limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, skill_key, name, domain, pattern, weight, use_count,
                      source, created_at, last_used
               FROM skills ORDER BY weight DESC LIMIT ?""",
            (q.limit,),
        ).fetchall()

    for r in rows:
        results.append(dict(r))

    # Also search meta_rules
    if q.keyword:
        rules = conn.execute(
            "SELECT rule_key, rule_value, category FROM meta_rules WHERE rule_key LIKE ? OR rule_value LIKE ?",
            (f"%{q.keyword}%", f"%{q.keyword}%"),
        ).fetchall()
        for r in rules:
            results.append({"type": "meta_rule", **dict(r)})

    return ApiResponse(ok=True, data=results)


@router.post("/add")
def add_memory(m: MemoryAdd):
    conn = get_conn()
    key = _skill_key(m.name, m.domain)
    now = time.time()
    try:
        conn.execute(
            """INSERT INTO skills (skill_key, name, domain, pattern, created_at, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, m.name, m.domain, m.pattern, now, m.source),
        )
        conn.commit()
        return ApiResponse(ok=True, message=f"Added skill: {m.name}", data={"skill_key": key})
    except conn.IntegrityError:
        # Update existing
        conn.execute(
            "UPDATE skills SET pattern=?, last_used=? WHERE skill_key=?",
            (m.pattern, now, key),
        )
        conn.commit()
        return ApiResponse(ok=True, message=f"Updated skill: {m.name}", data={"skill_key": key})
