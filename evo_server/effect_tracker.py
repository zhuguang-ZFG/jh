"""Effect tracker — measures whether context injection improves outcomes.

Computes:
- with_context vs without_context success rates (lift)
- Per-section contribution (failures, skills, patterns)
- fix_code impact on repeated failures
"""
import json
import time
import logging
from typing import Dict

logger = logging.getLogger("evo.effect")


def compute_effect_metrics(conn) -> Dict:
    """Compute effect metrics from context_injections + sessions tables.

    Only considers injections with real session_ids (from Stop hook flush).
    Pseudo session_ids (s-*) from in-flight sessions are excluded.
    """
    now = time.time()
    cutoff_30d = now - 30 * 86400

    # 1. Get injections with REAL session_ids (flushed by Stop hook)
    #    Real session_ids: UUID format or any non "s-" prefixed
    injected_rows = conn.execute(
        """SELECT DISTINCT session_id FROM context_injections
           WHERE created_at > ? AND session_id NOT LIKE 's-%'""",
        (cutoff_30d,),
    ).fetchall()
    injected_ids = {r["session_id"] for r in injected_rows}

    # 2. Get all sessions (last 30 days, exclude partial)
    all_sessions = conn.execute(
        """SELECT session_id, outcome FROM sessions
           WHERE created_at > ? AND outcome != 'partial'""",
        (cutoff_30d,),
    ).fetchall()

    with_ctx = []
    without_ctx = []
    session_outcomes = {}
    for s in all_sessions:
        session_outcomes[s["session_id"]] = s["outcome"]
        if s["session_id"] in injected_ids:
            with_ctx.append(s["outcome"])
        else:
            without_ctx.append(s["outcome"])

    # 3. Compute success rates
    def success_rate(outcomes):
        if not outcomes:
            return 0.0
        return sum(1 for o in outcomes if o == "success") / len(outcomes)

    with_rate = success_rate(with_ctx)
    without_rate = success_rate(without_ctx)
    lift = with_rate - without_rate

    # 4. Per-section contribution
    section_stats = conn.execute(
        """SELECT sections, session_id FROM context_injections
           WHERE created_at > ? AND session_id NOT LIKE 's-%'""",
        (cutoff_30d,),
    ).fetchall()

    section_outcomes = {}
    for row in section_stats:
        sid = row["session_id"]
        outcome = session_outcomes.get(sid, "")
        if not outcome:
            continue  # no matching session — skip
        try:
            sections = json.loads(row["sections"])
        except Exception:
            sections = []

        for section in sections:
            if section not in section_outcomes:
                section_outcomes[section] = {"total": 0, "success": 0}
            section_outcomes[section]["total"] += 1
            if outcome == "success":
                section_outcomes[section]["success"] += 1

    top_sections = {}
    for section, stats in section_outcomes.items():
        if stats["total"] >= 1:
            rate = stats["success"] / stats["total"]
            top_sections[section] = {
                "success_rate": round(rate, 3),
                "sessions": stats["total"],
                "lift_vs_baseline": round(rate - without_rate, 3),
            }

    # 5. fix_code impact — do failures with fix_code recur less?
    fix_impact = _compute_fix_impact(conn, cutoff_30d)

    # 6. Injection frequency stats
    total_injections = conn.execute(
        """SELECT COUNT(*) c FROM context_injections WHERE created_at > ?""",
        (cutoff_30d,),
    ).fetchone()["c"]
    real_injections = len(injected_ids)

    return {
        "period_days": 30,
        "total_sessions": len(all_sessions),
        "with_context": len(with_ctx),
        "without_context": len(without_ctx),
        "with_context_rate": round(with_rate, 3),
        "without_context_rate": round(without_rate, 3),
        "lift": round(lift, 3),
        "by_section": top_sections,
        "fix_code_impact": fix_impact,
        "injection_stats": {
            "total_records": total_injections,
            "with_real_session": real_injections,
        },
    }


def _compute_fix_impact(conn, cutoff: float) -> Dict:
    """Compare recurrence rate for failures with vs without fix_code."""
    with_fix = conn.execute(
        """SELECT pattern_key, occurrences FROM failure_patterns
           WHERE fix_code IS NOT NULL AND fix_code != '' AND last_seen > ?""",
        (cutoff,),
    ).fetchall()

    without_fix = conn.execute(
        """SELECT pattern_key, occurrences FROM failure_patterns
           WHERE (fix_code IS NULL OR fix_code = '') AND last_seen > ?""",
        (cutoff,),
    ).fetchall()

    def avg_occurrences(rows):
        if not rows:
            return 0
        return sum(r["occurrences"] for r in rows) / len(rows)

    avg_with = avg_occurrences(with_fix)
    avg_without = avg_occurrences(without_fix)

    return {
        "with_fix_code": len(with_fix),
        "without_fix_code": len(without_fix),
        "avg_recurrence_with_fix": round(avg_with, 1),
        "avg_recurrence_without_fix": round(avg_without, 1),
    }


def run_daily_effect_analysis(conn) -> Dict:
    """Run daily and store aggregated metrics."""
    metrics = compute_effect_metrics(conn)
    now = time.time()

    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")

    conn.execute(
        """INSERT OR REPLACE INTO effect_metrics
           (metric_date, with_context, without_context,
            with_context_success, without_context_success,
            lift, top_sections, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            today,
            metrics["with_context"],
            metrics["without_context"],
            int(metrics["with_context_rate"] * metrics["with_context"]),
            int(metrics["without_context_rate"] * metrics["without_context"]),
            metrics["lift"],
            json.dumps(metrics["by_section"]),
            now,
        ),
    )
    conn.commit()

    logger.info(
        f"Effect analysis: lift={metrics['lift']:.3f} "
        f"(with={metrics['with_context_rate']:.3f}, "
        f"without={metrics['without_context_rate']:.3f})"
    )
    return metrics
