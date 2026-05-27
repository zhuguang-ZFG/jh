"""Skills management with EMA weight updates."""
import time
from fastapi import APIRouter
from .db import get_conn
from .models import SkillRecall, SkillUpdate, ApiResponse
from . import config

router = APIRouter(prefix="/skills", tags=["skills"])


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
