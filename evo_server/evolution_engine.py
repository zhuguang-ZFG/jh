"""Evolution engine — analyze sessions, propose improvements, apply approved changes."""
import json
import time
import hashlib
import logging
from collections import Counter
from .db import get_conn
from . import config

logger = logging.getLogger("evo.evolution")


# ── Session analysis ──────────────────────────────────────────────

def analyze_recent_sessions(days: int = 7) -> dict:
    """Analyze sessions from the past N days. Returns stats + evidence."""
    conn = get_conn()
    cutoff = time.time() - days * 86400

    sessions = conn.execute(
        "SELECT * FROM sessions WHERE created_at > ? ORDER BY created_at",
        (cutoff,),
    ).fetchall()

    if not sessions:
        return {"total": 0, "sessions": []}

    total = len(sessions)
    outcomes = Counter(s["outcome"] for s in sessions)
    tools = Counter(s["tool"] for s in sessions)
    success_count = outcomes.get("success", 0)
    fail_count = outcomes.get("failure", 0)
    pass_rate = success_count / total if total else 0

    # Extract all changed files to infer language/domain distribution
    all_files = []
    for s in sessions:
        try:
            files = json.loads(s["changed_files"])
            all_files.extend(files)
        except (json.JSONDecodeError, TypeError):
            pass

    lang_dist = Counter()
    domain_dist = Counter()
    for f in all_files:
        ext = f.rsplit(".", 1)[-1] if "." in f else ""
        lang_dist[ext] += 1
        # Infer domain from path
        fp = f.lower()
        if any(k in fp for k in ("test", "spec")):
            domain_dist["testing"] += 1
        elif any(k in fp for k in ("api", "route", "handler")):
            domain_dist["api"] += 1
        elif any(k in fp for k in ("model", "schema", "db")):
            domain_dist["data"] += 1
        elif any(k in fp for k in ("config", "deploy", "ci", "docker")):
            domain_dist["devops"] += 1
        else:
            domain_dist["general"] += 1

    # Collect lessons
    lessons = [s["lessons"] for s in sessions if s["lessons"]]

    # Collect session IDs as evidence
    evidence_ids = [s["session_id"] for s in sessions]

    return {
        "total": total,
        "success_count": success_count,
        "fail_count": fail_count,
        "pass_rate": pass_rate,
        "tools": dict(tools),
        "top_domains": domain_dist.most_common(5),
        "top_extensions": lang_dist.most_common(5),
        "lessons": lessons,
        "evidence_ids": evidence_ids,
        "sessions": [dict(s) for s in sessions],
    }


# ── Proposal generation ───────────────────────────────────────────

def generate_proposals(analysis: dict) -> list[dict]:
    """Generate evolution proposals based on session analysis."""
    proposals = []
    if analysis["total"] < config.EVIDENCE_MIN:
        logger.info(f"Not enough evidence ({analysis['total']}/{config.EVIDENCE_MIN})")
        return proposals

    pass_rate = analysis["pass_rate"]

    # 1. Low pass rate → suggest strategy improvement
    if pass_rate < config.PASS_RATE_MIN and analysis["fail_count"] >= 2:
        proposals.append({
            "category": "strategy",
            "summary": (
                f"Pass rate is {pass_rate:.0%} ({analysis['success_count']}/{analysis['total']}) "
                f"over the last sessions. Consider reviewing failure patterns "
                f"and adjusting approach for {', '.join(d[0] for d in analysis['top_domains'][:3])} domains."
            ),
            "evidence_ids": analysis["evidence_ids"],
            "confidence": round(1.0 - pass_rate, 2),
        })

    # 2. High pass rate + lessons → promote lessons to skills
    if pass_rate >= config.PASS_RATE_MIN and analysis["lessons"]:
        for lesson in analysis["lessons"][:3]:
            proposals.append({
                "category": "skill",
                "summary": f"Promote lesson to skill: {lesson[:200]}",
                "evidence_ids": analysis["evidence_ids"],
                "confidence": round(pass_rate * 0.8, 2),
            })

    # 3. Tool imbalance → suggest diversification
    tools = analysis["tools"]
    if len(tools) == 1 and analysis["total"] >= 5:
        only_tool = list(tools.keys())[0]
        proposals.append({
            "category": "strategy",
            "summary": (
                f"All {analysis['total']} sessions used {only_tool}. "
                f"Consider diversifying tools for broader skill coverage."
            ),
            "evidence_ids": analysis["evidence_ids"],
            "confidence": 0.4,
        })

    # 4. Domain concentration → suggest exploration
    domains = analysis["top_domains"]
    if domains and domains[0][1] > analysis["total"] * 0.7:
        top = domains[0][0]
        proposals.append({
            "category": "pattern",
            "summary": (
                f"{domains[0][1]}/{analysis['total']} sessions focused on {top}. "
                f"Consider exploring other domains for well-rounded growth."
            ),
            "evidence_ids": analysis["evidence_ids"],
            "confidence": 0.5,
        })

    return proposals


# ── Proposal persistence ──────────────────────────────────────────

def save_proposals(proposals: list[dict]) -> list[int]:
    """Save proposals to DB. Returns list of created evo IDs."""
    conn = get_conn()
    ids = []
    now = time.time()
    for p in proposals:
        evo_key = hashlib.sha256(
            f"{p['category']}:{p['summary'][:100]}:{now}".encode()
        ).hexdigest()[:16]
        try:
            cur = conn.execute(
                """INSERT INTO evolutions (evo_key, category, summary, evidence_ids, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    evo_key,
                    p["category"],
                    p["summary"],
                    json.dumps(p["evidence_ids"]),
                    p["confidence"],
                    now,
                ),
            )
            ids.append(cur.lastrowid)
        except Exception:
            pass  # duplicate key, skip
    conn.commit()
    return ids


# ── Apply approved evolution ──────────────────────────────────────

def apply_evolution(evo_id: int) -> str:
    """Apply an approved evolution. Returns action description."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM evolutions WHERE id=? AND status='approved'", (evo_id,)).fetchone()
    if not row:
        return "Evolution not found or not approved"

    category = row["category"]
    summary = row["summary"]
    now = time.time()

    if category == "skill":
        # Promote to a skill
        skill_key = hashlib.sha256(summary.encode()).hexdigest()[:16]
        domain = _infer_domain_from_summary(summary)
        try:
            conn.execute(
                """INSERT INTO skills (skill_key, name, domain, pattern, weight, created_at, source)
                   VALUES (?, ?, ?, ?, 1.0, ?, 'evolved')""",
                (skill_key, summary[:80], domain, summary, now),
            )
            action = f"Created skill from evolution #{evo_id}"
        except Exception:
            action = f"Skill already exists for evolution #{evo_id}"

    elif category == "pattern":
        # Add as a pattern
        pattern_key = hashlib.sha256(summary.encode()).hexdigest()[:16]
        domain = _infer_domain_from_summary(summary)
        try:
            conn.execute(
                """INSERT INTO patterns (pattern_key, name, domain, description, confidence, created_at)
                   VALUES (?, ?, ?, ?, 0.6, ?)""",
                (pattern_key, summary[:80], domain, summary, now),
            )
            action = f"Created pattern from evolution #{evo_id}"
        except Exception:
            action = f"Pattern already exists for evolution #{evo_id}"

    elif category == "strategy":
        # Add as a meta rule
        rule_key = f"strategy_{evo_id}"
        try:
            conn.execute(
                """INSERT INTO meta_rules (rule_key, rule_value, category, created_at)
                   VALUES (?, ?, 'strategy', ?)""",
                (rule_key, summary, now),
            )
            action = f"Added strategy rule from evolution #{evo_id}"
        except Exception:
            action = f"Strategy rule already exists for evolution #{evo_id}"

    else:
        action = f"No apply handler for category '{category}'"

    # Mark as applied
    conn.execute(
        "UPDATE evolutions SET status='applied', resolved_at=? WHERE id=?",
        (now, evo_id),
    )
    conn.commit()
    return action


def _infer_domain_from_summary(summary: str) -> str:
    s = summary.lower()
    if any(k in s for k in ("test", "spec")):
        return "testing"
    if any(k in s for k in ("api", "route", "endpoint")):
        return "api"
    if any(k in s for k in ("database", "schema", "migration")):
        return "data"
    if any(k in s for k in ("deploy", "ci", "docker", "nginx")):
        return "devops"
    if any(k in s for k in ("frontend", "react", "ui")):
        return "frontend"
    return "general"


# ── Weekly evolution run ──────────────────────────────────────────

def run_weekly_evolution() -> dict:
    """Full weekly evolution cycle: analyze → propose → notify."""
    logger.info("Starting weekly evolution cycle")
    analysis = analyze_recent_sessions(days=7)
    logger.info(f"Analyzed {analysis['total']} sessions")

    proposals = generate_proposals(analysis)
    logger.info(f"Generated {len(proposals)} proposals")

    saved_ids = save_proposals(proposals)
    logger.info(f"Saved {len(saved_ids)} proposals to DB")

    return {
        "sessions_analyzed": analysis["total"],
        "proposals_generated": len(proposals),
        "proposal_ids": saved_ids,
        "pass_rate": analysis.get("pass_rate", 0),
        "top_domains": analysis.get("top_domains", []),
    }


# ── Daily skill maintenance ──────────────────────────────────────

def run_daily_maintenance() -> dict:
    """Daily maintenance: evict dead skills, compress old sessions."""
    conn = get_conn()
    now = time.time()

    # Evict skills with weight < 0.1 that haven't been used in 30 days
    cutoff = now - 30 * 86400
    evicted = conn.execute(
        "DELETE FROM skills WHERE weight < 0.1 AND last_used < ? AND last_used > 0",
        (cutoff,),
    ).rowcount

    # Compress sessions older than 30 days (keep summary, drop details)
    old_sessions = conn.execute(
        "SELECT id, session_id, lessons FROM sessions WHERE created_at < ? AND lessons != ''",
        (now - 30 * 86400,),
    ).fetchall()

    compressed = 0
    for s in old_sessions:
        # Keep lessons but clear changed_files to save space
        conn.execute(
            "UPDATE sessions SET changed_files='[]' WHERE id=?",
            (s["id"],),
        )
        compressed += 1

    conn.commit()
    return {"evicted_skills": evicted, "compressed_sessions": compressed}
