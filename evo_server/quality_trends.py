"""Quality trends — weekly aggregation and reporting."""
import json
import time
from datetime import datetime, timedelta
from .db import get_conn
import logging

logger = logging.getLogger("evo.quality")


def get_current_week() -> str:
    """Return ISO week string like '2026-W21'."""
    return datetime.utcnow().strftime("%G-W%V")


def get_week_start(week_str: str) -> float:
    """Convert ISO week string to epoch timestamp (Monday 00:00 UTC)."""
    year, week = week_str.split("-W")
    return datetime.strptime(f"{year}-W{week}-1", "%G-W%V-%u").timestamp()


def run_weekly_quality_report() -> dict:
    """Aggregate quality snapshots into a weekly report."""
    conn = get_conn()
    now = time.time()
    current_week = get_current_week()

    # Check if already reported this week
    existing = conn.execute(
        "SELECT id FROM quality_weekly WHERE week_start=?", (current_week,)
    ).fetchone()
    if existing:
        return {"status": "already_reported", "week": current_week}

    # Get sessions from this week
    week_start = get_week_start(current_week)
    sessions = conn.execute(
        "SELECT session_id, outcome, lessons FROM sessions WHERE created_at >= ?",
        (week_start,),
    ).fetchall()

    if not sessions:
        return {"status": "no_sessions", "week": current_week}

    total = len(sessions)
    successes = sum(1 for s in sessions if s["outcome"] == "success")
    success_rate = successes / total if total else 0

    # Get quality snapshots from this week
    snapshots = conn.execute(
        "SELECT snapshot, delta FROM quality_snapshots WHERE created_at >= ?",
        (week_start,),
    ).fetchall()

    avg_score = 0
    if snapshots:
        scores = []
        for snap in snapshots:
            try:
                data = json.loads(snap["snapshot"])
                if "score" in data:
                    scores.append(data["score"])
            except (json.JSONDecodeError, TypeError):
                pass
        avg_score = sum(scores) / len(scores) if scores else 0

    # Top improvements and regressions from deltas
    improvements = []
    regressions = []
    for snap in snapshots:
        try:
            delta = json.loads(snap["delta"])
            if delta.get("score_delta", 0) > 0:
                improvements.append(delta.get("description", "improved"))
            elif delta.get("score_delta", 0) < 0:
                regressions.append(delta.get("description", "regressed"))
        except (json.JSONDecodeError, TypeError):
            pass

    # Save weekly report
    snapshot_json = {
        "sessions": total,
        "successes": successes,
        "avg_score": round(avg_score, 1),
        "improvements_count": len(improvements),
        "regressions_count": len(regressions),
    }
    conn.execute(
        "INSERT INTO quality_weekly (week_start, avg_score, total_sessions, success_rate, "
        "top_improvements, top_regressions, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            current_week,
            avg_score,
            total,
            success_rate,
            json.dumps(improvements[:5], ensure_ascii=False),
            json.dumps(regressions[:5], ensure_ascii=False),
            json.dumps(snapshot_json, ensure_ascii=False),
            now,
        ),
    )
    conn.commit()

    logger.info(f"Weekly quality report: {current_week} — {total} sessions, {success_rate:.0%} success")
    return {
        "status": "created",
        "week": current_week,
        "sessions": total,
        "success_rate": success_rate,
        "avg_score": avg_score,
    }


def get_quality_trend(weeks: int = 4) -> list:
    """Get quality trend for the last N weeks."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT week_start, avg_score, total_sessions, success_rate, "
        "top_improvements, top_regressions FROM quality_weekly "
        "ORDER BY created_at DESC LIMIT ?",
        (weeks,),
    ).fetchall()
    return [dict(r) for r in rows]


def format_quality_report(trend: list) -> str:
    """Format quality trend into a readable Telegram message."""
    if not trend:
        return "No quality reports yet."

    lines = ["*Code Quality Trend*\n"]
    for r in trend:
        bar = "█" * int(r["success_rate"] * 10) + "░" * (10 - int(r["success_rate"] * 10))
        lines.append(
            f"*{r['week_start']}* — score={r['avg_score']:.0f} "
            f"sessions={r['total_sessions']}"
        )
        lines.append(f"  Success: {bar} {r['success_rate']:.0%}")

        try:
            improvements = json.loads(r["top_improvements"])
            if improvements:
                lines.append(f"  ↑ {improvements[0][:60]}")
        except (json.JSONDecodeError, TypeError):
            pass

        try:
            regressions = json.loads(r["top_regressions"])
            if regressions:
                lines.append(f"  ↓ {regressions[0][:60]}")
        except (json.JSONDecodeError, TypeError):
            pass
        lines.append("")

    # Week-over-week comparison
    if len(trend) >= 2:
        curr = trend[0]
        prev = trend[1]
        score_delta = curr["avg_score"] - prev["avg_score"]
        rate_delta = curr["success_rate"] - prev["success_rate"]
        direction = "↑" if score_delta > 0 else "↓" if score_delta < 0 else "→"
        lines.append(f"*vs last week:* {direction} score {score_delta:+.0f}, rate {rate_delta:+.0%}")

    return "\n".join(lines)
