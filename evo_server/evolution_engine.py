"""Evolution engine — analyze sessions, propose improvements, apply approved changes."""
import json
import time
import hashlib
import logging
from collections import Counter
from typing import List, Dict
from .db import get_conn
from . import config

logger = logging.getLogger("evo.evolution")


# ── LiMa-powered analysis ─────────────────────────────────────────

async def analyze_with_lima(analysis: dict) -> dict:
    """Use LiMa to intelligently analyze sessions and generate proposals."""
    from .lima_bridge import chat_with_lima

    if analysis["total"] < 2:
        return {"proposals": [], "raw_analysis": "Not enough sessions for LiMa analysis"}

    # Build context from sessions
    sessions_text = []
    for s in analysis["sessions"][:10]:
        sessions_text.append(
            f"- Session {s['session_id']}: tool={s['tool']}, outcome={s['outcome']}, "
            f"files={s['changed_files'][:200]}, lessons={s['lessons'][:100]}"
        )

    prompt = f"""Analyze these coding sessions and suggest improvements.

Sessions ({analysis['total']} total, {analysis['pass_rate']:.0%} success rate):
{chr(10).join(sessions_text)}

Top domains: {analysis['top_domains'][:3]}
Lessons collected: {len(analysis['lessons'])}

Return JSON array of proposals. Each proposal:
{{"category": "skill|pattern|strategy", "summary": "clear actionable suggestion", "confidence": 0.0-1.0}}

Focus on:
1. Patterns in failures — what keeps going wrong?
2. Success patterns — what's working that should be formalized?
3. Missing skills — what domains lack coverage?

Return ONLY the JSON array, no explanation."""

    response = await chat_with_lima(
        prompt,
        system="You are a programming evolution engine. Analyze coding sessions and suggest concrete improvements. Return only valid JSON."
    )

    # Strip markdown code blocks if present
    clean = response.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

    try:
        proposals = json.loads(clean)
        if isinstance(proposals, list):
            for p in proposals:
                p["evidence_ids"] = analysis["evidence_ids"]
            return {"proposals": proposals, "raw_analysis": response}
    except json.JSONDecodeError:
        pass

    return {"proposals": [], "raw_analysis": response}


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

def generate_proposals(analysis):
    # type: (dict) -> List[Dict]
    """Generate evolution proposals based on session analysis.

    Generates proposals for BOTH failure and success paths.
    """
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
            if lesson and len(lesson) > 10:
                proposals.append({
                    "category": "skill",
                    "summary": f"Promote lesson to skill: {lesson[:200]}",
                    "evidence_ids": analysis["evidence_ids"],
                    "confidence": round(pass_rate * 0.8, 2),
                })

    # 3. High success rate → formalize as proven technique
    if pass_rate >= 0.9 and analysis["total"] >= config.EVIDENCE_MIN:
        top_domains = [d[0] for d in analysis["top_domains"][:3]]
        if top_domains:
            proposals.append({
                "category": "skill",
                "summary": (
                    f"High success rate ({pass_rate:.0%}) across {analysis['total']} sessions. "
                    f"Formalize {', '.join(top_domains)} expertise as proven techniques."
                ),
                "evidence_ids": analysis["evidence_ids"],
                "confidence": round(pass_rate * 0.9, 2),
            })

    # 4. Tool imbalance → suggest diversification
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

    # 5. Domain concentration → suggest exploration
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

    # 6. Enough evidence but no proposals yet → generate a general review
    if not proposals and analysis["total"] >= config.EVIDENCE_MIN:
        proposals.append({
            "category": "strategy",
            "summary": (
                f"{analysis['total']} sessions analyzed, {pass_rate:.0%} success rate. "
                f"Top domains: {', '.join(d[0] for d in analysis['top_domains'][:3])}. "
                f"System operating well — continue monitoring for patterns."
            ),
            "evidence_ids": analysis["evidence_ids"],
            "confidence": 0.5,
        })

    return proposals


# ── Proposal persistence ──────────────────────────────────────────

def save_proposals(proposals):
    # type: (List[Dict]) -> List[int]
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


# ── Auto-approve high-confidence proposals ────────────────────────

def auto_approve_and_apply() -> dict:
    """Auto-approve proposals with confidence >= threshold, then apply them.

    Called after save_proposals() in the weekly evolution cycle.
    Returns stats: {approved, applied, failed}.
    """
    import uuid
    conn = get_conn()
    now = time.time()
    threshold = config.AUTO_APPROVE_THRESHOLD

    candidates = conn.execute(
        "SELECT id, evo_key, category, summary, confidence FROM evolutions "
        "WHERE status='proposed' AND confidence >= ? ORDER BY confidence DESC",
        (threshold,),
    ).fetchall()

    if not candidates:
        return {"approved": 0, "applied": 0, "failed": 0}

    approved = 0
    applied = 0
    failed = 0

    for row in candidates:
        evo_id = row["id"]
        # Approve
        conn.execute(
            "UPDATE evolutions SET status='approved', resolved_at=? WHERE id=?",
            (now, evo_id),
        )
        conn.execute(
            """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
               VALUES (?, 'evolution_engine', 'evolution_auto_approve', 'approved', ?, ?)""",
            (
                str(uuid.uuid4())[:8],
                json.dumps({
                    "evo_id": evo_id,
                    "category": row["category"],
                    "confidence": row["confidence"],
                    "summary": row["summary"][:100],
                }),
                now,
            ),
        )
        approved += 1

        # Apply
        try:
            action = apply_evolution(evo_id)
            applied += 1
            logger.info(f"Auto-applied evolution #{evo_id}: {action}")
        except Exception as e:
            failed += 1
            logger.warning(f"Auto-apply failed for evolution #{evo_id}: {e}")

    conn.commit()
    return {"approved": approved, "applied": applied, "failed": failed}


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
            row_id = conn.execute("SELECT id FROM skills WHERE skill_key=?", (skill_key,)).fetchone()["id"]
            _sync_vec(conn, "skills", row_id, {"name": summary[:80], "domain": domain, "pattern": summary})
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
            row_id = conn.execute("SELECT id FROM patterns WHERE pattern_key=?", (pattern_key,)).fetchone()["id"]
            _sync_vec(conn, "patterns", row_id, {"name": summary[:80], "domain": domain, "description": summary})
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


def _sync_vec(conn, table, row_id, row_data):
    try:
        from .vec_sync import sync_row_embedding
        sync_row_embedding(conn, table, row_id, row_data)
    except Exception:
        pass


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

async def run_weekly_evolution() -> dict:
    """Full weekly evolution cycle: analyze → LiMa proposes → notify."""
    import asyncio

    logger.info("Starting weekly evolution cycle")
    analysis = analyze_recent_sessions(days=7)
    logger.info(f"Analyzed {analysis['total']} sessions")

    # Try LiMa-powered analysis first
    lima_result = await analyze_with_lima(analysis)
    proposals = lima_result["proposals"]

    # Fallback to rule-based if LiMa returns nothing
    if not proposals:
        logger.info("LiMa returned no proposals, falling back to rule-based")
        proposals = generate_proposals(analysis)

    logger.info(f"Generated {len(proposals)} proposals")

    saved_ids = save_proposals(proposals)
    logger.info(f"Saved {len(saved_ids)} proposals to DB")

    # Auto-approve and apply high-confidence proposals
    auto_result = auto_approve_and_apply()
    logger.info(f"Auto-approve: {auto_result}")

    return {
        "sessions_analyzed": analysis["total"],
        "proposals_generated": len(proposals),
        "proposal_ids": saved_ids,
        "pass_rate": analysis.get("pass_rate", 0),
        "top_domains": analysis.get("top_domains", []),
        "source": "liMa" if lima_result["proposals"] else "rule_based",
        "auto_approved": auto_result.get("approved", 0),
        "auto_applied": auto_result.get("applied", 0),
    }


# ── Daily skill maintenance ──────────────────────────────────────

def run_daily_maintenance() -> dict:
    """Daily maintenance: evict dead skills, compress old sessions, promote lessons."""
    conn = get_conn()
    now = time.time()
    stats = {}

    # 1. Evict skills with weight < 0.1 that haven't been used in 30 days
    cutoff = now - 30 * 86400
    evicted = conn.execute(
        "DELETE FROM skills WHERE weight < 0.1 AND last_used < ? AND last_used > 0",
        (cutoff,),
    ).rowcount
    stats["evicted_skills"] = evicted

    # 2. Compress sessions older than 7 days (clear changed_files, keep lessons)
    week_ago = now - 7 * 86400
    compressed = conn.execute(
        "UPDATE sessions SET changed_files='[]' WHERE created_at < ? AND changed_files != '[]'",
        (week_ago,),
    ).rowcount
    stats["compressed_sessions"] = compressed

    # 3. Hard cap: keep max 200 sessions, delete oldest beyond that
    total = conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
    if total > 200:
        excess = total - 200
        # Preserve lessons from excess sessions before deleting
        excess_rows = conn.execute(
            "SELECT id, lessons FROM sessions ORDER BY created_at ASC LIMIT ?",
            (excess,),
        ).fetchall()
        promoted = 0
        for row in excess_rows:
            if row["lessons"] and len(row["lessons"]) > 10:
                _maybe_promote_lesson(conn, row["lessons"], now)
                promoted += 1
        conn.execute(
            "DELETE FROM sessions WHERE id IN (SELECT id FROM sessions ORDER BY created_at ASC LIMIT ?)",
            (excess,),
        )
        stats["deleted_excess"] = excess
        stats["promoted_from_excess"] = promoted

    # 4. Auto-promote high-success lessons to skills
    recent = conn.execute(
        "SELECT lessons, outcome FROM sessions WHERE created_at > ? AND lessons != ''",
        (now - 14 * 86400,),
    ).fetchall()
    new_skills = 0
    for row in recent:
        if row["outcome"] == "success" and row["lessons"]:
            if _maybe_promote_lesson(conn, row["lessons"], now):
                new_skills += 1
    stats["new_skills_promoted"] = new_skills

    conn.commit()
    return stats


def _maybe_promote_lesson(conn, lesson_text: str, now: float) -> bool:
    """Promote a lesson to a skill if it's substantive and not already known."""
    lesson = lesson_text.strip()[:200]
    if len(lesson) < 15:
        return False
    import hashlib
    skill_key = hashlib.sha256(lesson.encode()).hexdigest()[:16]
    existing = conn.execute(
        "SELECT id FROM skills WHERE skill_key=?", (skill_key,)
    ).fetchone()
    if existing:
        return False
    # Infer domain from lesson text
    domain = "general"
    lower = lesson.lower()
    if any(k in lower for k in ("python", "django", "flask", "fastapi")):
        domain = "python"
    elif any(k in lower for k in ("rust", "cargo")):
        domain = "rust"
    elif any(k in lower for k in ("go ", "golang")):
        domain = "go"
    elif any(k in lower for k in ("react", "typescript", "javascript", "vue")):
        domain = "frontend"
    elif any(k in lower for k in ("docker", "nginx", "deploy", "ci/cd")):
        domain = "devops"
    conn.execute(
        """INSERT INTO skills (skill_key, name, domain, pattern, weight, use_count,
                               success_count, created_at, last_used, source)
           VALUES (?, ?, ?, ?, 0.6, 1, 1, ?, ?, 'auto_promoted')""",
        (skill_key, lesson[:60], domain, lesson, now, now),
    )
    return True


# ── Weekly quality report ──────────────────────────────────────

async def run_weekly_quality_report() -> dict:
    """Generate weekly quality report from quality_snapshots."""
    from .quality_trends import run_weekly_quality_report as _run
    result = _run()
    logger.info(f"Quality report: {result}")
    return result


# ── LLM Skill Refinement ─────────────────────────────────────

async def run_llm_skill_refinement() -> dict:
    """Use LLM to review, deduplicate, and improve skill descriptions.

    Runs daily. Processes skills in batches of 20 to avoid LLM context limits.
    """
    from .llm_bridge import chat
    from .db import get_conn

    conn = get_conn()
    skills = conn.execute(
        "SELECT id, name, domain, pattern, weight, use_count FROM skills ORDER BY id"
    ).fetchall()

    if len(skills) < 5:
        logger.info("Skill refinement: not enough skills (%d), skipping", len(skills))
        return {"status": "skipped", "reason": "not_enough_skills", "count": len(skills)}

    kept = 0
    merged = 0
    deleted = 0
    rewritten = 0

    # Process in batches of 20
    batch_size = 20
    for i in range(0, len(skills), batch_size):
        batch = skills[i:i+batch_size]
        skill_lines = []
        for s in batch:
            skill_lines.append(
                f"{s['id']}: {s['name']}[{s['domain']}] "
                f"w={s['weight']:.1f} use={s['use_count']} "
                f"{s['pattern'][:80]}"
            )

        prompt = (
            f"Review these {len(batch)} skills. Decide for each: keep, merge, delete, or rewrite.\n"
            f"Rules: don't delete skills with use>3. Prefer merge over delete.\n"
            f"Return JSON array only:\n"
            f'[{{"action":"keep","id":1}},{{"action":"delete","id":2,"reason":"noise"}}]\n\n'
            f"Skills:\n" + "\n".join(skill_lines)
        )

        try:
            response = await chat(
                prompt,
                system="Return ONLY a JSON array. No explanation.",
            )
        except Exception as e:
            logger.warning("Skill refinement batch %d LLM error: %s", i, e)
            continue

        if not response:
            continue

        # Parse response
        import re as _re
        match = _re.search(r"\[.*\]", response, _re.DOTALL)
        if not match:
            logger.warning("Skill refinement batch %d: no JSON", i)
            continue

        try:
            actions = json.loads(match.group())
        except json.JSONDecodeError:
            continue

        for act in actions:
            action = act.get("action", "")
            if action == "keep":
                kept += 1
            elif action == "delete":
                sid = act.get("id")
                if sid and sid > 0:
                    row = conn.execute("SELECT use_count FROM skills WHERE id=?", (sid,)).fetchone()
                    if row and row["use_count"] > 3:
                        continue
                    conn.execute("DELETE FROM skills WHERE id=?", (sid,))
                    deleted += 1
            elif action == "merge":
                from_id = act.get("from_id")
                to_id = act.get("to_id")
                if from_id and to_id and from_id != to_id:
                    target = conn.execute("SELECT pattern FROM skills WHERE id=?", (to_id,)).fetchone()
                    source = conn.execute("SELECT pattern FROM skills WHERE id=?", (from_id,)).fetchone()
                    if target and source:
                        merged_pattern = target["pattern"] + " | " + source["pattern"][:80]
                        conn.execute(
                            "UPDATE skills SET pattern=?, weight=MIN(weight+0.1, 1.5) WHERE id=?",
                            (merged_pattern[:300], to_id),
                        )
                        conn.execute("DELETE FROM skills WHERE id=?", (from_id,))
                        merged += 1
            elif action == "rewrite":
                sid = act.get("id")
                new_pattern = act.get("new_pattern", "")
                if sid and new_pattern:
                    conn.execute(
                        "UPDATE skills SET pattern=?, weight=MIN(weight+0.05, 1.5) WHERE id=?",
                        (new_pattern[:300], sid),
                    )
                    rewritten += 1

    conn.commit()

    result = {
        "status": "done",
        "total_skills": len(skills),
        "kept": kept,
        "merged": merged,
        "deleted": deleted,
        "rewritten": rewritten,
    }
    logger.info("Skill refinement: %s", result)
    return result


# ── Cross-session pattern discovery ────────────────────────────


async def run_cross_session_discovery() -> dict:
    """Analyze recent sessions with LLM to find hidden cross-session patterns.

    Discovers patterns invisible to single-session analysis:
    - Recurring failure combinations
    - Success patterns that emerge across sessions
    - Workflow improvements
    - File change correlations

    Returns: {status, discoveries, sessions_analyzed, domains}
    """
    conn = get_conn()
    cutoff = time.time() - 7 * 86400  # last 7 days

    # Fetch recent sessions
    sessions = conn.execute(
        """SELECT session_id, goal, outcome, lessons, created_at
           FROM sessions WHERE created_at > ?
           ORDER BY created_at DESC LIMIT 30""",
        (cutoff,),
    ).fetchall()

    if len(sessions) < 5:
        return {
            "status": "skipped",
            "reason": "not_enough_sessions",
            "discoveries": [],
            "sessions_analyzed": len(sessions),
        }

    # Fetch failure patterns
    failures = conn.execute(
        """SELECT error_type, description, domain, occurrences
           FROM failure_patterns WHERE occurrences >= 2
           ORDER BY occurrences DESC LIMIT 20"""
    ).fetchall()

    # Fetch existing top skills
    skills = conn.execute(
        "SELECT name, domain FROM skills WHERE weight > 0.5 ORDER BY weight DESC LIMIT 15"
    ).fetchall()

    # Build session summary
    session_lines = []
    for s in sessions:
        outcome_symbol = "+" if s["outcome"] == "success" else (
            "-" if s["outcome"] == "failure" else "~")
        goal = (s["goal"] or "unknown")[:100]
        lessons = (s["lessons"] or "")[:120]
        session_lines.append(
            f"[{outcome_symbol}] {goal} -- {lessons}"
        )

    failure_lines = []
    for f in failures:
        failure_lines.append(
            f"- {f['error_type']}[{f['domain'] or 'general'}]: "
            f"{f['description'][:120]} ({f['occurrences']}x)"
        )

    skill_names = ", ".join(
        f"{s['name']}[{s['domain']}]" for s in skills[:10]
    ) or "(none)"

    # Build prompt
    system = (
        "Analyze programming session data and find HIDDEN PATTERNS that only "
        "emerge across multiple sessions. Focus on patterns a developer would "
        "NOT notice from a single session.\n\n"
        "Return a JSON array of discoveries, each with:\n"
        '- type: "risk_pattern" | "success_pattern" | "workflow_improvement" | "dependency_issue"\n'
        '- title: short descriptive name\n'
        '- description: what was observed across sessions\n'
        '- recommendation: what to do differently\n'
        '- confidence: 0.0-1.0\n'
        '- affected_files: [] (if any file pattern detected, else empty array)\n\n'
        "Only report patterns with evidence from 3+ sessions. Max 5 discoveries.\n"
        "Return ONLY the JSON array, no other text."
    )

    domain_counts = {}
    for s in sessions:
        d = "general"
        goal_lower = (s["goal"] or "").lower()
        for kw_dom in ("python", "api", "rust", "go", "devops", "test", "frontend", "js"):
            if kw_dom in goal_lower:
                d = kw_dom
                break
        domain_counts[d] = domain_counts.get(d, 0) + 1
    domains_text = ", ".join(
        f"{d}({c})" for d, c in
        sorted(domain_counts.items(), key=lambda x: -x[1])[:5]
    )

    user_msg = (
        f"Sessions in last 7 days ({len(sessions)} total):\n"
        + "\n".join(session_lines) + "\n\n"
        f"Top domains: {domains_text}\n\n"
        f"Top failure patterns:\n"
        + ("\n".join(failure_lines) if failure_lines else "(none)") + "\n\n"
        f"Top skills: {skill_names}\n\n"
        "Discover cross-session patterns."
    )

    discoveries = []
    try:
        from .llm_bridge import chat
        response = await chat(
            user_msg, system=system, temperature=0.3, max_backends=5
        )

        if response and not response.startswith("Error:"):
            try:
                data = json.loads(response.strip())
                if isinstance(data, list):
                    discoveries = data
            except json.JSONDecodeError:
                import re
                match = re.search(r"\[.*\]", response, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group())
                        if isinstance(data, list):
                            discoveries = data
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        logger.warning(f"Cross-session discovery LLM failed: {e}")

    # Store discoveries
    stored = 0
    for d in discoveries[:5]:
        d_type = d.get("type", "risk_pattern")
        title = d.get("title", "discovered_pattern")[:100]
        desc = d.get("description", "")[:300]
        rec = d.get("recommendation", "")[:200]
        confidence = min(max(d.get("confidence", 0.5), 0.0), 1.0)
        affected = d.get("affected_files", [])

        now = time.time()
        try:
            if d_type in ("risk_pattern", "dependency_issue"):
                # Store as failure_pattern for prevention
                key = hashlib.sha256(
                    f"{title}:{desc[:80]}".encode()
                ).hexdigest()[:16]
                try:
                    conn.execute(
                        """INSERT INTO failure_patterns
                           (pattern_key, error_type, description, fix_suggestion,
                            domain, occurrences, confidence, created_at, last_seen)
                           VALUES (?, ?, ?, ?, 'general', 1, ?, ?, ?)""",
                        (key, title, desc, rec, confidence, now, now),
                    )
                    stored += 1
                except conn.IntegrityError:
                    pass
            else:
                # Store as skill
                sk = hashlib.sha256(
                    f"{title}:general:{desc[:80]}".encode()
                ).hexdigest()[:16]
                try:
                    conn.execute(
                        """INSERT INTO skills
                           (skill_key, name, domain, pattern, when_to_use, weight,
                            use_count, success_count, created_at, last_used, source)
                           VALUES (?, ?, 'general', ?, ?, ?, 0, 0, ?, 0, 'cross_session')""",
                        (sk, title, desc, rec, confidence, now),
                    )
                    stored += 1
                except conn.IntegrityError:
                    pass
        except Exception as e:
            logger.warning(f"Failed to store discovery '{title}': {e}")

    if stored:
        conn.commit()
        # Sync vec+fts for new skills
        try:
            from . import fts_sync
            fts_sync.rebuild_fts(conn, "skills")
        except Exception:
            pass
        try:
            from . import vec_sync
            vec_sync.rebuild_all_embeddings(conn)
        except Exception:
            pass

    result = {
        "status": "done" if stored else "no_discoveries",
        "discoveries": discoveries[:5],
        "stored": stored,
        "sessions_analyzed": len(sessions),
        "domains": domains_text,
    }
    logger.info(f"Cross-session discovery: {stored} stored from "
                f"{len(sessions)} sessions ({domains_text})")
    return result
