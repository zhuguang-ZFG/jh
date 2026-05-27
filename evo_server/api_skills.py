"""Skills management with EMA weight updates."""
import time
from fastapi import APIRouter, Body
from .db import get_conn
from .models import SkillRecall, SkillUpdate, ApiResponse
from . import config
from .vec_search import vec_search

router = APIRouter(prefix="/skills", tags=["skills"])


def _sync_skill_embedding(conn, row_id, name, domain, pattern):
    try:
        from .vec_sync import sync_row_embedding
        sync_row_embedding(conn, "skills", row_id, {
            "name": name, "domain": domain, "pattern": pattern,
        })
    except Exception:
        pass  # non-critical


@router.post("/")
def create_skill(
    name: str = Body(...),
    domain: str = Body("general"),
    pattern: str = Body(""),
    weight: float = Body(1.0),
    source: str = Body("manual"),
):
    """Create or update a skill."""
    import hashlib
    conn = get_conn()
    now = time.time()
    key = hashlib.sha256(f"{name}:{domain}:{pattern[:80]}".encode()).hexdigest()[:16]
    try:
        conn.execute(
            """INSERT INTO skills (skill_key, name, domain, pattern, weight, use_count, success_count, created_at, last_used, source)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?, 0, ?)""",
            (key, name, domain, pattern, weight, now, source),
        )
        row_id = conn.execute("SELECT id FROM skills WHERE skill_key=?", (key,)).fetchone()["id"]
        _sync_skill_embedding(conn, row_id, name, domain, pattern)
    except conn.IntegrityError:
        conn.execute(
            "UPDATE skills SET pattern=?, weight=MAX(weight,?), last_used=? WHERE skill_key=?",
            (pattern, weight, now, key),
        )
        row_id = conn.execute("SELECT id FROM skills WHERE skill_key=?", (key,)).fetchone()["id"]
        _sync_skill_embedding(conn, row_id, name, domain, pattern)
    conn.commit()
    return ApiResponse(ok=True, data={"skill_key": key})


@router.get("/")
def list_skills(domain: str = "", limit: int = 50):
    conn = get_conn()
    if domain:
        rows = conn.execute(
            "SELECT * FROM skills WHERE domain=? ORDER BY weight DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM skills ORDER BY weight DESC LIMIT ?", (limit,)
        ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.post("/recall")
def recall_skills(q: SkillRecall):
    conn = get_conn()
    # If scenario has text, use vector search
    if q.scenario:
        results = vec_search(conn, "skills", q.scenario, limit=q.limit,
                             min_weight=0.1, domain=q.domain or "")
        return ApiResponse(ok=True, data=[{k: v for k, v in r.items() if k != "_score"} for r in results])

    # Fallback: top by weight
    if q.domain:
        rows = conn.execute(
            """SELECT * FROM skills
               WHERE domain=? AND weight > 0.1
               ORDER BY weight DESC LIMIT ?""",
            (q.domain, q.limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM skills
               WHERE weight > 0.1
               ORDER BY weight DESC LIMIT ?""",
            (q.limit,),
        ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.post("/update")
def update_skill(u: SkillUpdate):
    """EMA weight update: success *= 1.05, failure *= 0.9. Evict if weight < 0.1."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, weight, use_count, success_count FROM skills WHERE skill_key=?",
        (u.skill_key,),
    ).fetchone()
    if not row:
        return ApiResponse(ok=False, message="Skill not found")

    weight = row["weight"]
    use_count = row["use_count"] + 1
    success_count = row["success_count"]

    if u.success:
        weight = min(weight * config.EMA_SUCCESS_FACTOR, 10.0)
        success_count += 1
    else:
        weight *= config.EMA_FAILURE_FACTOR

    now = time.time()

    if weight < 0.1:
        conn.execute("DELETE FROM skills WHERE skill_key=?", (u.skill_key,))
        conn.commit()
        return ApiResponse(ok=True, message="Skill evicted (weight < 0.1)")

    conn.execute(
        """UPDATE skills SET weight=?, use_count=?, success_count=?, last_used=?
           WHERE skill_key=?""",
        (weight, use_count, success_count, now, u.skill_key),
    )
    conn.commit()
    return ApiResponse(
        ok=True,
        data={"skill_key": u.skill_key, "weight": round(weight, 4), "use_count": use_count},
    )
