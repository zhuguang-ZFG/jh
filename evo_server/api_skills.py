"""Skills management with EMA weight updates."""
import hashlib
import time
import json as _json
import logging
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from typing import List, Optional
from .db import get_conn
from .models import SkillRecall, SkillUpdate, ApiResponse
from . import config
from .vec_search import vec_search

logger = logging.getLogger("evo.skills")
router = APIRouter(prefix="/skills", tags=["skills"])


def _sync_skill_embedding(conn, row_id, name, domain, pattern, code_example=""):
    try:
        from .vec_sync import sync_row_embedding
        sync_row_embedding(conn, "skills", row_id, {
            "name": name, "domain": domain, "pattern": pattern, "code_example": code_example,
        })
    except Exception:
        pass  # non-critical


@router.post("/")
def create_skill(
    name: str = Body(...),
    domain: str = Body("general"),
    pattern: str = Body(""),
    code_example: str = Body(""),
    when_to_use: str = Body(""),
    anti_patterns: str = Body(""),
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
            """INSERT INTO skills (skill_key, name, domain, pattern, code_example, when_to_use, anti_patterns, weight, use_count, success_count, created_at, last_used, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?)""",
            (key, name, domain, pattern, code_example, when_to_use, anti_patterns, weight, now, source),
        )
        row_id = conn.execute("SELECT id FROM skills WHERE skill_key=?", (key,)).fetchone()["id"]
        _sync_skill_embedding(conn, row_id, name, domain, pattern, code_example)
    except conn.IntegrityError:
        conn.execute(
            "UPDATE skills SET pattern=?, code_example=?, when_to_use=?, anti_patterns=?, weight=MAX(weight,?), last_used=? WHERE skill_key=?",
            (pattern, code_example, when_to_use, anti_patterns, weight, now, key),
        )
        row_id = conn.execute("SELECT id FROM skills WHERE skill_key=?", (key,)).fetchone()["id"]
        _sync_skill_embedding(conn, row_id, name, domain, pattern, code_example)
    conn.commit()
    return ApiResponse(ok=True, data={"skill_key": key})


class SkillItem(BaseModel):
    name: str
    domain: str = "general"
    pattern: str = ""
    code_example: str = ""
    when_to_use: str = ""
    anti_patterns: str = ""
    weight: float = 1.0
    source: str = "session"


class BatchSkillRequest(BaseModel):
    skills: List[SkillItem] = Field(..., min_length=1, max_length=20)


@router.post("/batch")
def batch_create_skills(req: BatchSkillRequest):
    """Batch create or update multiple skills in one request."""
    conn = get_conn()
    now = time.time()
    created = 0
    updated = 0

    for s in req.skills:
        key = hashlib.sha256(f"{s.name}:{s.domain}:{s.pattern[:80]}".encode()).hexdigest()[:16]
        try:
            conn.execute(
                """INSERT INTO skills (skill_key, name, domain, pattern, code_example, when_to_use, anti_patterns, weight,
                   use_count, success_count, created_at, last_used, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?)""",
                (key, s.name, s.domain, s.pattern, s.code_example, s.when_to_use, s.anti_patterns, s.weight, now, s.source),
            )
            row_id = conn.execute("SELECT id FROM skills WHERE skill_key=?", (key,)).fetchone()["id"]
            _sync_skill_embedding(conn, row_id, s.name, s.domain, s.pattern, s.code_example)
            created += 1
        except conn.IntegrityError:
            conn.execute(
                "UPDATE skills SET pattern=?, code_example=?, when_to_use=?, anti_patterns=?, weight=MAX(weight,?), last_used=? WHERE skill_key=?",
                (s.pattern, s.code_example, s.when_to_use, s.anti_patterns, s.weight, now, key),
            )
            row_id = conn.execute("SELECT id FROM skills WHERE skill_key=?", (key,)).fetchone()["id"]
            _sync_skill_embedding(conn, row_id, s.name, s.domain, s.pattern, s.code_example)
            updated += 1

    conn.commit()
    return ApiResponse(ok=True, data={"created": created, "updated": updated})


# ── Quality Gatekeeper ──────────────────────────────────────────


class GatekeepSkillItem(BaseModel):
    name: str
    domain: str = "general"
    pattern: str = ""
    weight: float = 1.0


class GatekeepRequest(BaseModel):
    skills: List[GatekeepSkillItem] = Field(..., min_length=1, max_length=20)
    user_task: str = ""


_GATEKEEP_NOISE_PREFIXES = (
    "session_", "bash_", "created_module_", "created_func_",
    "created_router_", "edit_pattern_", "framework_", "deploy_",
)
_GATEKEEP_NOISE_KEYWORDS = (
    "files touched", "commands", "tool calls", "files,", "edits,",
)


def _heuristic_gatekeep(name: str, pattern: str) -> dict:
    """Rule-based fallback when LLM is unavailable."""
    if any(name.startswith(p) for p in _GATEKEEP_NOISE_PREFIXES):
        return {"verdict": "discard", "confidence": 0.9,
                "reason": f"Name prefix matches noise pattern"}
    pat_lower = pattern.lower()
    if any(k in pat_lower for k in _GATEKEEP_NOISE_KEYWORDS):
        return {"verdict": "discard", "confidence": 0.85,
                "reason": "Pattern contains session statistics, not reusable knowledge"}
    if len(pattern) < 20:
        return {"verdict": "discard", "confidence": 0.8,
                "reason": "Pattern too vague (<20 chars)"}
    return {"verdict": "keep", "confidence": 0.5,
            "reason": "Heuristic default: keep when uncertain"}


async def _gatekeep_with_llm(skills: list, user_task: str) -> list:
    """Use LLM to judge skill quality. Returns list of {name, verdict, confidence, reason}."""
    from .llm_bridge import chat

    skills_text = ""
    for i, s in enumerate(skills):
        skills_text += f"{i+1}. {s['name']} [{s.get('domain','')}]: {s.get('pattern','')[:120]}\n"

    system = (
        "You are a code skill quality gatekeeper. Determine if each auto-extracted "
        "skill is worth storing. Keep ONLY skills with PROJECT-SPECIFIC knowledge "
        "Claude cannot know from training data.\n\n"
        "DISCARD: generic patterns (FastAPI Body(), SQLite basics, git commands)\n"
        "DISCARD: session statistics (file counts, command counts, tool counts)\n"
        "DISCARD: vague one-liners with no actionable content\n"
        "KEEP: project-specific conventions, known pitfalls in THIS codebase\n"
        "KEEP: user's explicit preferences, corrections, naming conventions\n"
        "KEEP: stack-specific gotchas discovered through real failures\n\n"
        "Return JSON array only:\n"
        '[{"skill_name": "exact name from input", "verdict": "keep"|"discard", '
        '"confidence": 0.0-1.0, "reason": "one sentence"}]'
    )

    user_msg = f"Task: {user_task[:200] or 'unknown'}\nSkills:\n{skills_text}\nJudge each skill."

    try:
        response = await chat(user_msg, system=system, temperature=0.2, max_backends=3)
    except Exception as e:
        logger.warning(f"Gatekeep LLM failed: {e}")
        return []

    if not response or response.startswith("Error:"):
        return []

    # Parse response
    try:
        data = _json.loads(response.strip())
        if isinstance(data, list):
            return data
    except _json.JSONDecodeError:
        pass

    # Fallback: extract JSON array
    import re
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if match:
        try:
            data = _json.loads(match.group())
            if isinstance(data, list):
                return data
        except _json.JSONDecodeError:
            pass

    return []


@router.post("/gatekeep")
async def gatekeep_skills(req: GatekeepRequest):
    """LLM quality check on auto-extracted skills. Falls back to heuristic rules."""
    results = []

    # Try LLM first
    llm_results = await _gatekeep_with_llm(
        [{"name": s.name, "domain": s.domain, "pattern": s.pattern}
         for s in req.skills],
        req.user_task,
    )

    if llm_results:
        # Build lookup from LLM response
        llm_map = {}
        for r in llm_results:
            name = r.get("skill_name", "")
            llm_map[name] = {
                "verdict": r.get("verdict", "keep"),
                "confidence": r.get("confidence", 0.5),
                "reason": r.get("reason", ""),
            }
        for s in req.skills:
            if s.name in llm_map:
                results.append({
                    "name": s.name,
                    **llm_map[s.name],
                    "source": "llm",
                })
            else:
                results.append({
                    "name": s.name,
                    "verdict": "keep",
                    "confidence": 0.3,
                    "reason": "LLM did not judge this skill",
                    "source": "fallback",
                })
    else:
        # LLM failed — use heuristic for all
        for s in req.skills:
            h = _heuristic_gatekeep(s.name, s.pattern)
            results.append({
                "name": s.name,
                **h,
                "source": "heuristic",
            })

    kept = sum(1 for r in results if r["verdict"] == "keep")
    discarded = len(results) - kept
    logger.info(f"Gatekeep: {kept} kept, {discarded} discarded "
                f"(source={results[0]['source'] if results else 'none'})")

    return ApiResponse(ok=True, data={
        "results": results,
        "summary": {"kept": kept, "discarded": discarded, "total": len(results)},
    })


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
