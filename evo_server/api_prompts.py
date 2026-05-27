"""Prompt auto-tuning API — track prompt→result correlation + EMA ranking."""
import math
import time
from fastapi import APIRouter, Body
from .db import get_conn
from .models import ApiResponse
from . import config

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.post("/log")
def log_prompt(
    session_id: str = Body(...),
    prompt_type: str = Body(...),
    prompt_text: str = Body(""),
    strategy: str = Body(""),
    outcome: str = Body(...),
    duration_sec: int = Body(0),
):
    """Record a prompt/strategy and its outcome."""
    conn = get_conn()
    now = time.time()
    conn.execute(
        "INSERT INTO prompt_outcomes (session_id, prompt_type, prompt_text, strategy, "
        "outcome, duration_sec, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, prompt_type, prompt_text, strategy, outcome, duration_sec, now),
    )
    conn.commit()
    return ApiResponse(ok=True, data={"logged": True})


@router.get("/stats")
def prompt_stats():
    """Get success rate by prompt type."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT prompt_type, "
        "COUNT(*) as total, "
        "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) as successes, "
        "SUM(CASE WHEN outcome='failure' THEN 1 ELSE 0 END) as failures, "
        "AVG(duration_sec) as avg_duration "
        "FROM prompt_outcomes GROUP BY prompt_type ORDER BY total DESC"
    ).fetchall()
    result = []
    for r in rows:
        total = r["total"]
        successes = r["successes"]
        result.append({
            "prompt_type": r["prompt_type"],
            "total": total,
            "successes": successes,
            "failures": r["failures"],
            "success_rate": round(successes / total, 3) if total else 0,
            "avg_duration": round(r["avg_duration"], 1) if r["avg_duration"] else 0,
        })
    return ApiResponse(ok=True, data=result)


@router.get("/best")
def best_strategies(limit: int = 10):
    """Get best-performing strategies."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT strategy, prompt_type, "
        "COUNT(*) as total, "
        "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) as successes "
        "FROM prompt_outcomes WHERE strategy != '' "
        "GROUP BY strategy, prompt_type "
        "HAVING total >= 2 "
        "ORDER BY CAST(successes AS REAL) / total DESC, total DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.get("/best-ema")
def best_ema(prompt_type: str = "", days: int = 90, limit: int = 10):
    """EMA-weighted best strategies — recent results weighted higher.

    lambda=0.05 → half-life ~14 days. Uses SQLite's exp() function.
    """
    conn = get_conn()
    cutoff = time.time() - days * 86400
    lam = config.EMA_PROMPT_LAMBDA

    type_filter = "AND prompt_type = ?" if prompt_type else ""
    params = []
    if prompt_type:
        params.append(prompt_type)
    params.append(limit)

    rows = conn.execute(
        f"""SELECT strategy, prompt_type,
                   COUNT(*) as uses,
                   SUM(CASE WHEN outcome='success'
                       THEN exp(-{lam} * ({cutoff} - created_at) / 86400.0) ELSE 0 END) /
                   SUM(exp(-{lam} * ({cutoff} - created_at) / 86400.0)) as ema_rate
            FROM prompt_outcomes
            WHERE strategy != '' AND created_at > {cutoff} {type_filter}
            GROUP BY strategy, prompt_type
            HAVING uses >= 2
            ORDER BY ema_rate DESC
            LIMIT ?""",
        params,
    ).fetchall()

    result = []
    for r in rows:
        result.append({
            "strategy": r["strategy"],
            "prompt_type": r["prompt_type"],
            "uses": r["uses"],
            "ema_rate": round(r["ema_rate"], 4) if r["ema_rate"] else 0,
        })
    return ApiResponse(ok=True, data=result)


@router.get("/best-practices")
def best_practices(limit: int = 5):
    """Best strategy per prompt_type, ranked by EMA success rate."""
    conn = get_conn()
    cutoff = time.time() - 90 * 86400
    lam = config.EMA_PROMPT_LAMBDA

    # Get all prompt types
    types = conn.execute(
        "SELECT DISTINCT prompt_type FROM prompt_outcomes WHERE strategy != ''"
    ).fetchall()

    result = []
    for t in types:
        pt = t["prompt_type"]
        row = conn.execute(
            f"""SELECT strategy,
                      COUNT(*) as uses,
                      SUM(CASE WHEN outcome='success'
                          THEN exp(-{lam} * ({cutoff} - created_at) / 86400.0) ELSE 0 END) /
                      SUM(exp(-{lam} * ({cutoff} - created_at) / 86400.0)) as ema_rate
               FROM prompt_outcomes
               WHERE prompt_type = ? AND strategy != '' AND created_at > {cutoff}
               GROUP BY strategy
               HAVING uses >= 2
               ORDER BY ema_rate DESC
               LIMIT 1""",
            (pt,),
        ).fetchone()
        if row:
            result.append({
                "prompt_type": pt,
                "strategy": row["strategy"],
                "uses": row["uses"],
                "ema_rate": round(row["ema_rate"], 4) if row["ema_rate"] else 0,
            })

    result.sort(key=lambda x: x["ema_rate"], reverse=True)
    return ApiResponse(ok=True, data=result[:limit])
