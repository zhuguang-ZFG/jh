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

logger = logging.getLogger("evo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_conn()  # init DB on startup
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

        # GitHub learning: 02:00 UTC (10:00 CST), daily
        _scheduler.add_job(
            _run_learning_job, "cron", hour=2, minute=30,
            id="github_learning",
        )

        _scheduler.start()
        logger.info("APScheduler started (weekly_evolution + daily_maintenance)")
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

    result = asyncio.run(run_weekly_evolution())
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
        loop = asyncio.get_event_loop()
        loop.create_task(send_notification(msg))
    except Exception:
        pass


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
        result = subprocess.run(
            [sys.executable, "/opt/evo-server/learning/github_learner.py"],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "EVO_SERVER": "http://127.0.0.1:8090"},
        )
        logger.info(f"GitHub learning: {result.stdout[-200:] if result.stdout else 'no output'}")
        if result.returncode != 0:
            logger.error(f"GitHub learning failed: {result.stderr[-200:]}")
    except Exception as e:
        logger.error(f"GitHub learning job error: {e}")


app = FastAPI(title="Evo-Server", version="0.1.0", lifespan=lifespan)

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
