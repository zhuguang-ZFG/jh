"""Context injection endpoint — query relevant skills/patterns for a task.

Claude Code calls this to get context-aware suggestions before starting work.
"""
import json
import time
import hashlib
import asyncio as _asyncio
import threading
import logging
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from .db import get_conn
from .models import ApiResponse
from .vec_search import vec_search
from .embedding import embed_text
from .keywords import extract_keywords
from . import config

logger = logging.getLogger("evo.context")
router = APIRouter(prefix="/context", tags=["context"])


class ContextQuery(BaseModel):
    task: str  # User's task description
    domain: str = ""  # Optional domain filter
    limit: int = Field(default=10, ge=1, le=30)


@router.post("/query")
def query_context(q: ContextQuery):
    """Query relevant skills, patterns, and rules for a task."""
    conn = get_conn()
    result = {
        "skills": [],
        "patterns": [],
        "rules": [],
        "quality_tips": [],
        "session_insights": [],
    }

    # 1. Vector search for skills
    skills = vec_search(conn, "skills", q.task, limit=q.limit,
                        min_weight=0.2, domain=q.domain)
    result["skills"] = [_format_skill(r) for r in skills]

    # 2. Vector search for patterns
    patterns = vec_search(conn, "patterns", q.task, limit=q.limit,
                          min_weight=0.3, domain=q.domain)
    result["patterns"] = [_format_pattern(r) for r in patterns]

    # 3. Keyword search for meta rules (no vec table)
    keywords = extract_keywords(q.task)
    if keywords:
        like_clauses = " OR ".join(["rule_value LIKE ?" for _ in keywords])
        like_params = ["%{}%".format(k) for k in keywords]
        rows = conn.execute(
            "SELECT * FROM meta_rules WHERE ({}) LIMIT 5".format(like_clauses),
            like_params,
        ).fetchall()
        result["rules"] = [dict(r)["rule_value"] for r in rows]

    # 4. Quality tips from recent sessions
    cutoff = time.time() - 7 * 86400
    quality_rows = conn.execute(
        """SELECT delta FROM quality_snapshots
           WHERE phase='after' AND created_at > ?
           ORDER BY created_at DESC LIMIT 5""",
        (cutoff,),
    ).fetchall()
    for qr in quality_rows:
        try:
            delta = json.loads(qr["delta"])
            summary = delta.get("summary", {})
            if summary.get("syntax_errors_introduced", 0) > 0:
                result["quality_tips"].append(
                    "Recent sessions introduced syntax errors — double-check syntax"
                )
            if summary.get("complexity_delta", 0) > 5:
                result["quality_tips"].append(
                    "Complexity trending up — consider simplifying"
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # 5. Session insights from successful sessions
    session_rows = conn.execute(
        """SELECT lessons, outcome FROM sessions
           WHERE outcome='success' AND lessons != ''
           ORDER BY created_at DESC LIMIT 5"""
    ).fetchall()
    kw_list = extract_keywords(q.task)
    for sr in session_rows:
        lesson = sr["lessons"]
        if lesson and any(k in lesson.lower() for k in kw_list):
            result["session_insights"].append(lesson[:200])

    # Deduplicate
    result["skills"] = result["skills"][:q.limit]
    result["patterns"] = result["patterns"][:q.limit]
    result["quality_tips"] = list(set(result["quality_tips"]))[:5]
    result["session_insights"] = list(set(result["session_insights"]))[:3]

    return ApiResponse(ok=True, data=result)


@router.get("/summary")
def context_summary():
    """Quick summary of available context (for CLAUDE.md generation)."""
    conn = get_conn()
    skills = conn.execute(
        "SELECT name, domain, weight FROM skills WHERE weight > 0.3 ORDER BY weight DESC LIMIT 10"
    ).fetchall()
    patterns = conn.execute(
        "SELECT name, domain, description FROM patterns WHERE confidence > 0.4 ORDER BY confidence DESC LIMIT 10"
    ).fetchall()
    rules = conn.execute(
        "SELECT rule_value FROM meta_rules LIMIT 5"
    ).fetchall()

    lines = ["## Available Context\n"]
    if skills:
        lines.append("### Skills")
        for s in skills:
            lines.append("- {} [{}] (w={:.1f})".format(s["name"], s["domain"], s["weight"]))
    if patterns:
        lines.append("\n### Patterns")
        for p in patterns:
            lines.append("- {} [{}]: {}".format(p["name"], p["domain"], p["description"][:80]))
    if rules:
        lines.append("\n### Rules")
        for r in rules:
            lines.append("- {}".format(r["rule_value"][:100]))

    return ApiResponse(ok=True, data={"summary": "\n".join(lines)})


# ── Batch endpoint (single request for all context) ────────────

class ContextBatchRequest(BaseModel):
    task: str
    domain: str = ""
    limit: int = Field(default=5, ge=1, le=30)
    include: List[str] = Field(
        default=["skills", "patterns", "failures", "conventions",
                 "git_patterns", "briefing", "best_practices", "memories"],
        description="Which data categories to include",
    )


_batch_cache = {}  # {cache_key: {"ts": float, "data": dict}}
_BATCH_CACHE_TTL = 60  # seconds

# Predicted risks cache — separately managed from batch cache
_predicted_risks_cache: Dict[str, Dict[str, Any]] = {}
_RISK_CACHE_TTL = 600  # 10 minutes
_RISK_CACHE_LOCK = threading.Lock()
_MAX_RISK_CACHE = 200


def _generate_predicted_risks_sync(
    task: str, domain: str, failures: list
) -> list:
    """Generate predicted risks (sync, called from background thread).

    Returns up to 3 items with {risk, prevention} fields.
    Returns [] on any failure — never raises.
    """
    from .llm_bridge import chat

    failures_text = ""
    if failures:
        for f in failures[:5]:
            et = f.get("error_type", "?")
            desc = f.get("description", "")[:100]
            failures_text += f"- {et}: {desc}\n"
    if not failures_text:
        failures_text = "(none recorded)"

    system = (
        "You are a coding risk predictor. Given a specific task, domain, "
        "and recent failure history, predict the top 3 most likely mistakes "
        "the developer might make on THIS task. Focus on project-specific "
        "pitfalls and failure patterns, not generic coding advice. "
        "Each prediction must be actionable.\n\n"
        "Return a JSON array only:\n"
        '[{"risk": "one sentence describing the likely mistake", '
        '"prevention": "one sentence on how to prevent it"}]\n'
        "Max 3 items. No explanation outside JSON."
    )

    user_msg = (
        f"Task: {task[:300]}\n"
        f"Domain: {domain or 'general'}\n"
        f"Recent failure patterns:\n{failures_text}\n"
        "Predict the top 3 most likely mistakes for this task."
    )

    try:
        response = _asyncio.run(
            chat(user_msg, system=system, temperature=0.2, max_backends=3)
        )
    except Exception:
        return []

    if not response or response.startswith("Error:"):
        return []

    import re
    try:
        data = json.loads(response.strip())
        if isinstance(data, list):
            return [
                {"risk": r.get("risk", "")[:120],
                 "prevention": r.get("prevention", "")[:120]}
                for r in data[:3]
                if r.get("risk")
            ]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return [
                    {"risk": r.get("risk", "")[:120],
                     "prevention": r.get("prevention", "")[:120]}
                    for r in data[:3]
                    if r.get("risk")
                ]
        except json.JSONDecodeError:
            pass

    return []


@router.post("/batch")
def batch_context(q: ContextBatchRequest):
    """Single-request context batch — replaces 6+ serial API calls from hooks.

    Optimizations:
    - Embed query once, share across all vec_search calls
    - Briefing reuses already-searched results (no duplicate vec_search)
    - In-memory cache for repeated identical requests (60s TTL)
    """
    # Check cache
    cache_key = f"{q.task}:{q.domain}:{q.limit}:{':'.join(sorted(q.include))}"
    now = time.time()
    cached = _batch_cache.get(cache_key)
    if cached and (now - cached["ts"]) < _BATCH_CACHE_TTL:
        result_data = dict(cached["data"])
        if "predicted_risks" in q.include and q.task:
            task_hash = hashlib.md5(q.task.encode()).hexdigest()
            with _RISK_CACHE_LOCK:
                risk_cached = _predicted_risks_cache.get(task_hash)
            if risk_cached and risk_cached.get("done") and \
               (now - risk_cached["ts"]) < _RISK_CACHE_TTL:
                result_data["predicted_risks"] = risk_cached["risks"]
        return ApiResponse(ok=True, data=result_data)

    conn = get_conn()
    data = {}

    # Pre-compute embedding once for all vec_search calls
    task_emb = embed_text(q.task) if q.task else None

    if "skills" in q.include:
        skills = vec_search(conn, "skills", q.task, limit=q.limit,
                            min_weight=0.2, domain=q.domain,
                            precomputed_emb=task_emb)
        data["skills"] = [_format_skill(r) for r in skills]

    if "patterns" in q.include:
        patterns = vec_search(conn, "patterns", q.task, limit=q.limit,
                              min_weight=0.3, domain=q.domain,
                              precomputed_emb=task_emb)
        data["patterns"] = [_format_pattern(r) for r in patterns]

    if "failures" in q.include:
        if q.task:
            failures = vec_search(conn, "failure_patterns", q.task, limit=q.limit,
                                  precomputed_emb=task_emb)
            data["failures"] = [{k: v for k, v in f.items() if k != "_score"} for f in failures]
        else:
            rows = conn.execute(
                "SELECT * FROM failure_patterns ORDER BY occurrences DESC LIMIT ?",
                (q.limit,),
            ).fetchall()
            data["failures"] = [dict(r) for r in rows]

    if "conventions" in q.include:
        rows = conn.execute(
            "SELECT * FROM conventions ORDER BY confidence DESC LIMIT ?",
            (min(q.limit * 2, 20),),
        ).fetchall()
        all_convs = [dict(r) for r in rows]
        if q.task:
            lang = ""
            task_lower = q.task.lower()
            for ext, lang_name in [("py", "python"), ("js", "javascript"), ("ts", "typescript")]:
                if ext in task_lower:
                    lang = lang_name
                    break
            relevant = [c for c in all_convs
                        if lang and (lang in c.get("rule", "").lower()
                                     or lang in c.get("example", "").lower()
                                     or c.get("category") == "structure")]
            data["conventions"] = relevant[:4] if relevant else all_convs[:4]
        else:
            data["conventions"] = all_convs[:4]

    if "git_patterns" in q.include:
        rows = conn.execute(
            "SELECT * FROM git_patterns ORDER BY confidence DESC LIMIT ?",
            (min(q.limit, 10),),
        ).fetchall()
        data["git_patterns"] = [dict(r) for r in rows]

    if "briefing" in q.include and q.task:
        # Reuse already-searched results instead of re-running vec_search
        skills_for_briefing = data.get("skills", [])
        patterns_for_briefing = data.get("patterns", [])
        failures_for_briefing = data.get("failures", [])
        warnings = []
        for f in failures_for_briefing:
            fix = f.get("fix_suggestion", "")
            if fix:
                warnings.append(f"{f.get('error_type', '?')}: {fix[:100]}")
        data["briefing"] = {
            "warnings": warnings,
            "skills_count": len(skills_for_briefing),
            "patterns_count": len(patterns_for_briefing),
        }

    if "best_practices" in q.include:
        cutoff = time.time() - 90 * 86400
        lam = config.EMA_PROMPT_LAMBDA
        rows = conn.execute(
            f"""SELECT strategy, prompt_type,
                       COUNT(*) as uses,
                       SUM(CASE WHEN outcome='success'
                           THEN exp(-{lam} * ({cutoff} - created_at) / 86400.0) ELSE 0 END) /
                       SUM(exp(-{lam} * ({cutoff} - created_at) / 86400.0)) as ema_rate
                FROM prompt_outcomes
                WHERE strategy != '' AND created_at > {cutoff}
                GROUP BY strategy, prompt_type
                HAVING uses >= 2
                ORDER BY ema_rate DESC
                LIMIT ?""",
            (min(q.limit, 10),),
        ).fetchall()
        data["best_practices"] = [
            {
                "strategy": r["strategy"],
                "prompt_type": r["prompt_type"],
                "uses": r["uses"],
                "ema_rate": round(r["ema_rate"], 4) if r["ema_rate"] else 0,
            }
            for r in rows
        ]

    if "memories" in q.include and q.task:
        memories = vec_search(conn, "memories", q.task, limit=q.limit,
                              min_weight=0.3, domain=q.domain,
                              precomputed_emb=task_emb)
        data["memories"] = [
            {k: v for k, v in m.items() if k != "_score"}
            for m in memories
        ]

    # Effect-based recommendations: which sections have positive/negative lift
    try:
        from .effect_tracker import get_effective_sections
        recs = get_effective_sections(conn)
        if recs.get("data_available"):
            data["effect_recommendations"] = recs
    except Exception:
        pass  # non-critical

    # Quality health: trend assessment and recommendations
    try:
        from .quality_trends import get_quality_health as _get_qh
        health = _get_qh()
        if health.get("status") != "insufficient_data":
            data["quality_health"] = health
    except Exception:
        pass  # non-critical

    # Predicted risks: background LLM generation with cache
    if "predicted_risks" in q.include and q.task:
        task_hash = hashlib.md5(q.task.encode()).hexdigest()
        with _RISK_CACHE_LOCK:
            cached_risk = _predicted_risks_cache.get(task_hash)

        if cached_risk and cached_risk.get("done") and \
           (now - cached_risk["ts"]) < _RISK_CACHE_TTL:
            data["predicted_risks"] = cached_risk["risks"]
        elif not cached_risk:
            with _RISK_CACHE_LOCK:
                _predicted_risks_cache[task_hash] = {
                    "ts": now, "risks": [], "done": False}

            failures_for_risk = data.get("failures", [])
            domain_for_risk = q.domain or ""

            def _bg_generate():
                try:
                    risks = _generate_predicted_risks_sync(
                        q.task, domain_for_risk, failures_for_risk
                    )
                    with _RISK_CACHE_LOCK:
                        _predicted_risks_cache[task_hash] = {
                            "ts": time.time(), "risks": risks, "done": True}
                        if len(_predicted_risks_cache) > _MAX_RISK_CACHE:
                            oldest = sorted(
                                _predicted_risks_cache.items(),
                                key=lambda x: x[1]["ts"]
                            )
                            for k, v in oldest[:len(_predicted_risks_cache) // 4]:
                                del _predicted_risks_cache[k]
                    if risks:
                        logger.info(
                            "Predicted risks generated for task: %s", q.task[:50])
                except Exception:
                    with _RISK_CACHE_LOCK:
                        _predicted_risks_cache[task_hash]["done"] = True

            threading.Thread(target=_bg_generate, daemon=True).start()

    # Update cache (exclude predicted_risks — separately managed)
    data_for_cache = {
        k: v for k, v in data.items() if k != "predicted_risks"}
    _batch_cache[cache_key] = {"ts": now, "data": data_for_cache}

    return ApiResponse(ok=True, data=data)


# ── Context injection logging (Phase 3: effect tracking) ──────

class InjectionLogRequest(BaseModel):
    session_id: str
    sections: List[str] = Field(default_factory=list)
    failure_count: int = 0
    skill_count: int = 0
    pattern_count: int = 0
    has_fix_code: bool = False
    domain: str = ""
    skill_keys: List[str] = Field(default_factory=list, description="skill_key values of injected skills")


@router.post("/log-injection")
def log_injection(req: InjectionLogRequest):
    """Record a context injection event for effect tracking."""
    conn = get_conn()
    now = time.time()
    conn.execute(
        """INSERT INTO context_injections
           (session_id, sections, failure_count, skill_count, pattern_count,
            has_fix_code, domain, skill_keys, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            req.session_id,
            json.dumps(req.sections),
            req.failure_count,
            req.skill_count,
            req.pattern_count,
            1 if req.has_fix_code else 0,
            req.domain,
            json.dumps(req.skill_keys),
            now,
        ),
    )
    conn.commit()
    return ApiResponse(ok=True, message="Injection logged")


@router.get("/effect")
def get_effect_metrics():
    """Return effect tracking metrics — does context injection help?"""
    from .effect_tracker import compute_effect_metrics
    conn = get_conn()
    metrics = compute_effect_metrics(conn)
    return ApiResponse(ok=True, data=metrics)


@router.get("/effect-recommendations")
def get_effect_recommendations():
    """Return section recommendations based on effect metrics.

    Which sections to prioritize (positive lift) vs deprioritize (negative lift).
    """
    from .effect_tracker import get_effective_sections
    conn = get_conn()
    recs = get_effective_sections(conn)
    return ApiResponse(ok=True, data=recs)


@router.get("/quality-health")
def get_quality_health():
    """Return quality health assessment from weekly trends.

    Includes status (improving/declining/stable), trend data, and recommendations.
    """
    from .quality_trends import get_quality_health as _get
    health = _get()
    return ApiResponse(ok=True, data=health)


# ── Helpers ───────────────────────────────────────────────────

def _extract_keywords(text):
    # type: (str) -> List[str]
    """Extract meaningful keywords from task description."""
    import re
    # Remove common stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "this", "that",
        "these", "those", "it", "its", "and", "or", "not", "but", "if",
        "i", "you", "he", "she", "we", "they", "me", "him", "her", "us",
        "my", "your", "his", "our", "their", "what", "which", "who", "whom",
        "how", "when", "where", "why", "all", "each", "every", "both",
        "few", "more", "most", "other", "some", "such", "no", "only",
        "same", "than", "too", "very", "just", "also", "now", "here",
        "there", "then", "so", "up", "out", "about", "get", "got",
        "make", "made", "let", "need", "use", "using", "used",
        "fix", "add", "create", "update", "change", "remove", "delete",
        "help", "please", "want", "try", "need", "implement", "build",
    }
    words = re.findall(r"[a-zA-Z_]{3,}", text.lower())
    return list(set(w for w in words if w not in stop_words))[:8]


def _format_skill(row):
    r = dict(row)
    result = {
        "skill_key": r.get("skill_key", ""),
        "name": r["name"],
        "domain": r["domain"],
        "weight": round(r.get("weight", 1.0), 2),
        "pattern": r.get("pattern", "")[:200],
    }
    if r.get("code_example"):
        result["code_example"] = r["code_example"][:300]
    if r.get("when_to_use"):
        result["when_to_use"] = r["when_to_use"][:200]
    if r.get("anti_patterns"):
        result["anti_patterns"] = r["anti_patterns"][:200]
    return result


def _format_pattern(row):
    r = dict(row)
    return {
        "name": r["name"],
        "domain": r["domain"],
        "description": r.get("description", "")[:200],
        "confidence": round(r.get("confidence", 0.5), 2),
        "source_repo": r.get("source_repo", ""),
    }
