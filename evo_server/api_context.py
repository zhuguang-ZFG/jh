"""Context injection endpoint — query relevant skills/patterns for a task.

Claude Code calls this to get context-aware suggestions before starting work.
"""
import json
import time
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from .db import get_conn
from .models import ApiResponse
from .vec_search import vec_search
from .keywords import extract_keywords

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
    return {
        "name": r["name"],
        "domain": r["domain"],
        "weight": round(r.get("weight", 1.0), 2),
        "pattern": r.get("pattern", "")[:200],
    }


def _format_pattern(row):
    r = dict(row)
    return {
        "name": r["name"],
        "domain": r["domain"],
        "description": r.get("description", "")[:200],
        "confidence": round(r.get("confidence", 0.5), 2),
        "source_repo": r.get("source_repo", ""),
    }
