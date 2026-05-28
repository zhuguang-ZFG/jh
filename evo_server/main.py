"""Evo-server — personal programming evolution platform."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import os
import time
import logging

from .db import get_conn, close_conn
from . import config
from .api_memory import router as memory_router
from .api_session import router as session_router
from .api_skills import router as skills_router
from .api_evo import router as evo_router
from .api_patterns import router as patterns_router
from .api_lima import router as lima_router
from .api_quality import router as quality_router
from .api_context import router as context_router
from .api_failures import router as learn_router
from .api_briefing import router as briefing_router
from .api_prompts import router as prompts_router
from .api_shared import router as shared_router
from .api_memories import router as memories_router

logger = logging.getLogger("evo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_conn()  # init DB on startup (loads sqlite-vec)

    # Rebuild vector embeddings on startup (background, non-blocking)
    def _init_embeddings():
        try:
            from .vec_sync import rebuild_all_embeddings
            rebuild_all_embeddings(conn)
        except Exception as e:
            logger.warning(f"Embedding rebuild skipped: {e}")

    import threading
    threading.Thread(target=_init_embeddings, daemon=True).start()

    _start_scheduler()
    yield
    _stop_scheduler()
    close_conn()


_scheduler = None


def _start_scheduler():
    global _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from .evolution_engine import run_weekly_evolution, run_daily_maintenance
        from .telegram_bot import send_notification
        import asyncio

        _scheduler = AsyncIOScheduler()

        # Weekly evolution: Monday 04:00 UTC (12:00 CST)
        _scheduler.add_job(
            _run_weekly_job, "cron", day_of_week="mon", hour=4, minute=0,
            id="weekly_evolution",
        )

        # Daily maintenance: 03:00 UTC (11:00 CST)
        _scheduler.add_job(
            _run_daily_job, "cron", hour=3, minute=0,
            id="daily_maintenance",
        )

        # LLM sync: 05:00 UTC (13:00 CST), daily
        if config.LLM_SYNC_ENABLED:
            _scheduler.add_job(
                _run_llm_sync_job, "cron", hour=5, minute=0,
                id="llm_sync",
            )

        # Cross-session discovery: 04:00 UTC (12:00 CST), daily
        _scheduler.add_job(
            _run_cross_session_job, "cron", hour=4, minute=0,
            id="cross_session_discovery",
        )

        # GitHub learning: 02:00 UTC (10:00 CST), daily
        _scheduler.add_job(
            _run_learning_job, "cron", hour=2, minute=30,
            id="github_learning",
        )

        # Weekly quality report: Monday 04:30 UTC (12:30 CST)
        _scheduler.add_job(
            _run_quality_report_job, "cron", day_of_week="mon", hour=4, minute=30,
            id="weekly_quality_report",
        )

        # LLM skill refinement: 06:00 UTC (14:00 CST), daily
        if config.LLM_SYNC_ENABLED:
            _scheduler.add_job(
                _run_skill_refinement_job, "cron", hour=6, minute=0,
                id="llm_skill_refinement",
            )

        # Retroactive fix generation: 07:00 UTC (15:00 CST), daily
        _scheduler.add_job(
            _run_fix_generation_job, "cron", hour=7, minute=0,
            id="retroactive_fix_generation",
        )

        # Effect analysis: 08:00 UTC (16:00 CST), daily
        _scheduler.add_job(
            _run_effect_analysis_job, "cron", hour=8, minute=0,
            id="effect_analysis",
        )

        # Nightly digest: 08:30 UTC (16:30 CST), daily
        _scheduler.add_job(
            _run_digest_job, "cron", hour=8, minute=30,
            id="nightly_digest",
        )

        _scheduler.start()
        logger.info("APScheduler started (weekly_evolution + daily_maintenance + quality_report + skill_refinement)")
    except ImportError:
        logger.warning("APScheduler not installed, cron jobs disabled")
    except Exception as e:
        logger.error(f"Scheduler start failed: {e}")


def _stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)


def _run_weekly_job():
    from .evolution_engine import run_weekly_evolution
    from .telegram_bot import send_notification
    import asyncio

    async def _do():
        result = await run_weekly_evolution()
        if result["proposal_ids"]:
            msg = (
                f"📊 *Weekly Evolution Report*\n"
                f"Sessions analyzed: {result['sessions_analyzed']}\n"
                f"Pass rate: {result['pass_rate']:.0%}\n"
                f"Proposals: {len(result['proposal_ids'])}\n"
                f"Top domains: {', '.join(d[0] for d in result['top_domains'][:3])}\n\n"
                f"Use /evo to review proposals."
            )
        else:
            msg = (
                f"📊 *Weekly Evolution Report*\n"
                f"Sessions analyzed: {result['sessions_analyzed']}\n"
                f"Not enough evidence for proposals. Keep coding!"
            )
        try:
            await send_notification(msg)
        except Exception:
            pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_do())
        else:
            loop.run_until_complete(_do())
    except RuntimeError:
        asyncio.run(_do())


def _run_daily_job():
    from .evolution_engine import run_daily_maintenance

    result = run_daily_maintenance()
    logger.info(f"Daily maintenance: {result}")


def _run_llm_sync_job():
    """LLM sync — query LongCat for improvement suggestions."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_llm_sync())
        else:
            loop.run_until_complete(_async_llm_sync())
    except RuntimeError:
        asyncio.run(_async_llm_sync())


async def _async_llm_sync():
    from .llm_bridge import chat, export_evo_knowledge
    from .telegram_bot import send_notification

    try:
        knowledge = export_evo_knowledge()
        skills_summary = ", ".join(
            f"{s['name']}[{s['domain']}]"
            for s in knowledge["top_skills"][:5]
        )
        response = await chat(
            f"Given skills: {skills_summary}\nSuggest 3 improvements.",
            system="Return JSON array: [{category, summary, confidence}]. No explanation.",
        )
        import json as _json
        suggestions = []
        try:
            suggestions = _json.loads(response)
        except Exception:
            pass
        msg = (
            f"🔗 *LLM Sync Complete*\n"
            f"Knowledge: {knowledge['skills_count']} skills, {knowledge['patterns_count']} patterns\n"
            f"Suggestions: {len(suggestions)}"
        )
        await send_notification(msg)
    except Exception as e:
        logger.error(f"LLM sync failed: {e}")
        await send_notification(f"LLM sync failed: {e}")


def _run_learning_job():
    """GitHub learning — scan trending repos for code patterns."""
    import subprocess
    import sys
    try:
        env = {
            **os.environ,
            "EVO_SERVER": "http://127.0.0.1:8090",
            "GITHUB_TOKEN": config.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN", ""),
        }
        result = subprocess.run(
            [sys.executable, "/opt/evo-server/learning/github_learner.py"],
            capture_output=True, text=True, timeout=300,
            env=env,
        )
        logger.info(f"GitHub learning: {result.stdout[-200:] if result.stdout else 'no output'}")
        if result.returncode != 0:
            logger.error(f"GitHub learning failed: {result.stderr[-200:]}")
    except Exception as e:
        logger.error(f"GitHub learning job error: {e}")


def _run_quality_report_job():
    """Weekly quality report — aggregate quality snapshots."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_quality_report())
        else:
            loop.run_until_complete(_async_quality_report())
    except RuntimeError:
        asyncio.run(_async_quality_report())


async def _async_quality_report():
    from .evolution_engine import run_weekly_quality_report
    from .telegram_bot import send_notification
    try:
        result = await run_weekly_quality_report()
        if result.get("status") == "created":
            msg = (
                f"📊 *Weekly Quality Report*\n"
                f"Week: {result['week']}\n"
                f"Sessions: {result['sessions']}\n"
                f"Success rate: {result['success_rate']:.0%}\n"
                f"Avg score: {result['avg_score']:.0f}"
            )
            await send_notification(msg)
    except Exception as e:
        logger.error(f"Quality report failed: {e}")


def _run_skill_refinement_job():
    """Daily LLM skill refinement — deduplicate, improve, prune skills."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_skill_refinement())
        else:
            loop.run_until_complete(_async_skill_refinement())
    except RuntimeError:
        asyncio.run(_async_skill_refinement())


async def _async_skill_refinement():
    from .evolution_engine import run_llm_skill_refinement
    from .telegram_bot import send_notification
    try:
        result = await run_llm_skill_refinement()
        status = result.get("status", "unknown")
        if status == "done":
            msg = (
                f"🔧 *Skill Refinement*\n"
                f"Total: {result['total_skills']} skills\n"
                f"Kept: {result['kept']}, Merged: {result['merged']}, "
                f"Deleted: {result['deleted']}, Rewritten: {result['rewritten']}"
            )
            await send_notification(msg)
        elif status == "skipped":
            logger.info("Skill refinement skipped: %s", result.get("reason"))
        else:
            logger.warning("Skill refinement: %s", status)
    except Exception as e:
        logger.error(f"Skill refinement failed: {e}")


def _run_fix_generation_job():
    """Retroactive fix generation — generate fix_code for failures missing it."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_fix_generation())
        else:
            loop.run_until_complete(_async_fix_generation())
    except RuntimeError:
        asyncio.run(_async_fix_generation())


async def _async_fix_generation():
    from .fix_generator import generate_fix
    from .db import get_conn

    conn = get_conn()
    rows = conn.execute(
        """SELECT pattern_key, error_type, description, file_context, domain
           FROM failure_patterns
           WHERE (fix_code IS NULL OR fix_code = '') AND occurrences >= 2
           ORDER BY occurrences DESC, last_seen DESC
           LIMIT 10"""
    ).fetchall()

    if not rows:
        logger.info("Fix generation: no failures needing fixes")
        return

    generated = 0
    for row in rows:
        try:
            fix_code, fix_type = await generate_fix(
                row["error_type"], row["description"],
                row["file_context"], row["domain"]
            )
            if fix_code:
                conn.execute(
                    "UPDATE failure_patterns SET fix_code=?, fix_type=? WHERE pattern_key=?",
                    (fix_code, fix_type, row["pattern_key"]),
                )
                generated += 1
        except Exception as e:
            logger.warning(f"Fix gen failed for {row['pattern_key']}: {e}")

    conn.commit()
    logger.info(f"Fix generation: {generated}/{len(rows)} succeeded")


def _run_effect_analysis_job():
    """Daily effect analysis — compute context injection effectiveness."""
    try:
        from .effect_tracker import run_daily_effect_analysis
        from .db import get_conn
        conn = get_conn()
        result = run_daily_effect_analysis(conn)
        logger.info(
            f"Effect analysis: lift={result['lift']:.3f}, "
            f"sessions={result['total_sessions']}"
        )
    except Exception as e:
        logger.error(f"Effect analysis failed: {e}")


def _run_digest_job():
    """Nightly digest — summarize the day's findings and push to Telegram."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_digest())
        else:
            loop.run_until_complete(_async_digest())
    except RuntimeError:
        asyncio.run(_async_digest())


async def _async_digest():
    from .telegram_bot import send_notification
    try:
        conn = get_conn()
        now = __import__("time").time()
        cutoff = now - 86400  # last 24 hours

        # Sessions in last 24h
        sessions = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) "
            "FROM sessions WHERE created_at > ?", (cutoff,)
        ).fetchone()
        total_s = sessions[0] or 0
        success_s = sessions[1] or 0
        rate_s = f"{success_s}/{total_s}" if total_s else "none"

        # New skills today
        new_skills = conn.execute(
            "SELECT COUNT(*) FROM skills WHERE created_at > ?", (cutoff,)
        ).fetchone()[0]

        # Cross-session discoveries
        discoveries = conn.execute(
            "SELECT name, pattern FROM skills WHERE source='cross_session' "
            "AND created_at > ? ORDER BY weight DESC LIMIT 3", (cutoff,)
        ).fetchall()

        # Effect lift
        lift_row = conn.execute(
            "SELECT lift from effect_metrics ORDER BY metric_date DESC LIMIT 1"
        ).fetchone()
        lift_val = round(lift_row["lift"], 3) if lift_row else None

        # Quality health
        q_row = conn.execute(
            "SELECT avg_score, success_rate FROM quality_weekly "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

        # Top failures in last 24h
        failures = conn.execute(
            "SELECT error_type, description, occurrences FROM failure_patterns "
            "WHERE last_seen > ? ORDER BY occurrences DESC LIMIT 3", (cutoff,)
        ).fetchall()

        # Top skills by weight
        top_skills = conn.execute(
            "SELECT name, domain, weight FROM skills WHERE weight > 1.0 "
            "ORDER BY weight DESC LIMIT 3"
        ).fetchall()

        # Build message
        lines = ["*Nightly Digest*\n"]

        lines.append("*Sessions:* %s (%s success)"
                    % (total_s, rate_s) if total_s else "*Sessions:* none today")

        if new_skills:
            lines.append("*New skills:* %d" % new_skills)

        if discoveries:
            lines.append("\n*Discoveries:*")
            for d in discoveries:
                lines.append("  - *%s*: %s"
                            % (d["name"], (d["pattern"] or "")[:60]))

        if lift_val is not None:
            direction = "↑" if lift_val > 0 else "↓"
            lines.append("\n*Effect lift:* %s%.3f" % (direction, lift_val))

        if q_row:
            qs = round(q_row["avg_score"], 0)
            qr = round(q_row["success_rate"] * 100)
            lines.append("*Quality:* score=%d, rate=%d%%" % (qs, qr))

        if failures:
            lines.append("\n*Top failures:*")
            for f in failures:
                lines.append("  - %s: %s (%dx)"
                            % (f["error_type"], (f["description"] or "")[:60],
                               f["occurrences"]))

        if top_skills:
            lines.append("\n*Top skills:*")
            for s in top_skills:
                lines.append("  - *%s* [%s] w=%.1f"
                            % (s["name"], s["domain"], s["weight"]))

        lines.append("\n_%s_" % "evolved   run /status for details")

        await send_notification("\n".join(lines))
        logger.info("Nightly digest sent (%d sessions, %d discoveries)",
                   total_s, len(discoveries))
    except Exception as e:
        logger.error("Nightly digest failed: %s", e)


def _run_cross_session_job():
    """Cross-session discovery — LLM finds hidden patterns across sessions."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_cross_session())
        else:
            loop.run_until_complete(_async_cross_session())
    except RuntimeError:
        asyncio.run(_async_cross_session())


async def _async_cross_session():
    from .evolution_engine import run_cross_session_discovery
    from .telegram_bot import send_notification
    try:
        result = await run_cross_session_discovery()
        status = result.get("status", "unknown")
        if status == "done":
            discoveries = result.get("discoveries", [])
            types = set(d.get("type", "?") for d in discoveries)
            msg = (
                f"🔍 *Cross-Session Discovery*\n"
                f"Sessions analyzed: {result['sessions_analyzed']}\n"
                f"Domains: {result.get('domains', 'unknown')}\n"
                f"Patterns found: {result['stored']} ({', '.join(types)})\n"
            )
            for d in discoveries[:3]:
                msg += f"\n• *{d.get('title', '?')}*: {d.get('recommendation', '')[:100]}"
            await send_notification(msg)
        elif status == "skipped":
            logger.info("Cross-session discovery skipped: %s",
                       result.get("reason"))
        else:
            logger.info("Cross-session discovery: %s", status)
    except Exception as e:
        logger.error(f"Cross-session discovery failed: {e}")


app = FastAPI(title="Evo-Server", version="0.2.0", lifespan=lifespan)

# --- API key middleware ---
EXEMPT_PATHS = {"/health", "/stats", "/docs", "/openapi.json", "/telegram/webhook"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)
    if config.API_KEY:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token != config.API_KEY:
            return JSONResponse(status_code=401, content={"ok": False, "message": "Unauthorized"})
    return await call_next(request)


# --- Request logging middleware ---
from collections import defaultdict
import threading

_request_stats = defaultdict(lambda: {"count": 0, "errors": 0, "total_ms": 0})
_stats_lock = threading.Lock()


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    import time as _time
    start = _time.monotonic()
    response = await call_next(request)
    elapsed_ms = int((_time.monotonic() - start) * 1000)
    path = request.url.path
    status = response.status_code
    with _stats_lock:
        stats = _request_stats[path]
        stats["count"] += 1
        stats["total_ms"] += elapsed_ms
        if status >= 400:
            stats["errors"] += 1
    if status >= 500:
        logger.warning(f"HTTP {status} {path} ({elapsed_ms}ms)")
    return response


# --- Routers ---
app.include_router(memory_router)
app.include_router(session_router)
app.include_router(skills_router)
app.include_router(evo_router)
app.include_router(patterns_router)
app.include_router(lima_router)
app.include_router(quality_router)
app.include_router(context_router)
app.include_router(learn_router)
app.include_router(briefing_router)
app.include_router(prompts_router)
app.include_router(shared_router)
app.include_router(memories_router)


# --- Health ---
@app.get("/health")
def health():
    conn = get_conn()
    stats = {
        "skills": conn.execute("SELECT COUNT(*) c FROM skills").fetchone()["c"],
        "patterns": conn.execute("SELECT COUNT(*) c FROM patterns").fetchone()["c"],
        "sessions": conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"],
        "evolutions": conn.execute("SELECT COUNT(*) c FROM evolutions WHERE status='proposed'").fetchone()["c"],
        "events": conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
    }
    # Vec embedding counts
    for vec_table in ["skills_vec", "patterns_vec", "failures_vec", "memories_vec"]:
        try:
            count = conn.execute(f"SELECT COUNT(*) c FROM {vec_table}").fetchone()["c"]
            stats[vec_table] = count
        except Exception:
            stats[vec_table] = "unavailable"
    return {"ok": True, "uptime": time.time(), "stats": stats}


@app.get("/stats")
def request_stats():
    """API request statistics — call count, errors, latency per path."""
    with _stats_lock:
        result = {}
        for path, s in sorted(_request_stats.items(), key=lambda x: -x[1]["count"]):
            avg_ms = s["total_ms"] // max(s["count"], 1)
            result[path] = {
                "count": s["count"],
                "errors": s["errors"],
                "avg_ms": avg_ms,
            }
    return {"ok": True, "paths": result}


# --- Auto-deploy ---
import subprocess as _subprocess


@app.post("/deploy")
def auto_deploy():
    """Trigger git pull + restart via deploy.sh in background.

    Spawns deploy.sh as independent process — response returns
    BEFORE the service restarts, so the HTTP response is clean.
    """
    _subprocess.Popen(
        ["/bin/bash", "/opt/evo-server/deploy.sh"],
        stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"ok": True, "message": "Deploy triggered — check Telegram for result"}


# --- Telegram webhook ---
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    # Verify secret token
    if config.TELEGRAM_WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != config.TELEGRAM_WEBHOOK_SECRET:
            return JSONResponse(status_code=403, content={"ok": False})

    body = await request.json()

    async def process():
        from .telegram_bot import handle_update
        conn = get_conn()
        try:
            await handle_update(body, conn)
        except Exception as e:
            logger.error(f"Telegram update error: {e}")

    background_tasks.add_task(process)
    return {"ok": True}
