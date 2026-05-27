"""Session logging + periodic flush endpoint."""
import json
import time
import uuid
import hashlib
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from typing import List, Optional
from .db import get_conn
from .models import SessionLog, ApiResponse
from . import config

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/log")
def log_session(s: SessionLog):
    conn = get_conn()
    now = time.time()
    try:
        conn.execute(
            """INSERT INTO sessions (session_id, tool, goal, outcome, changed_files,
                                     lessons, duration_sec, git_diff, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.session_id,
                s.tool,
                s.goal,
                s.outcome,
                json.dumps(s.changed_files),
                s.lessons,
                s.duration_sec,
                s.git_diff,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4())[:8],
                s.tool,
                "session_end",
                s.outcome,
                json.dumps({"session_id": s.session_id, "goal": s.goal}),
                now,
            ),
        )
        conn.commit()
    except conn.IntegrityError:
        return ApiResponse(ok=False, message="Duplicate session_id")

    # Phase 2: Extract skills from git diff
    extracted_skills = []
    if s.git_diff and len(s.git_diff) > 50:
        try:
            from .skill_extractor import extract_skills_from_diff
            extracted_skills = extract_skills_from_diff(s.git_diff, s.changed_files)
            if extracted_skills:
                _save_extracted_skills(conn, extracted_skills, now)
        except Exception as e:
            import logging
            logging.getLogger("evo.session").warning(f"Skill extraction from diff failed: {e}")

    return ApiResponse(ok=True, message="Session logged", data={
        "skills_extracted": len(extracted_skills),
    })


@router.get("/recent")
def recent_sessions(limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


# ── Periodic flush endpoint ────────────────────────────────────

class FlushSkill(BaseModel):
    name: str
    domain: str = "general"
    pattern: str = ""
    weight: float = 1.0
    source: str = "session"


class FlushMemory(BaseModel):
    category: str = "context"
    content: str
    domain: str = "general"
    confidence: float = 0.5


class SessionFlushRequest(BaseModel):
    session_id: str
    goal: str = ""
    skills: List[FlushSkill] = Field(default_factory=list)
    memories: List[FlushMemory] = Field(default_factory=list)
    changed_files: List[str] = Field(default_factory=list)
    domain: str = "general"


@router.post("/flush")
def flush_session(req: SessionFlushRequest):
    """Periodic session flush — uploads accumulated skills/memories mid-session.

    Unlike /session/log (final, once-per-session), this endpoint:
    - Is called every ~5 minutes during active sessions
    - Creates a partial session record if none exists
    - Merges skills/memories (dedup by content hash)
    - Safe to call multiple times — idempotent per session
    """
    conn = get_conn()
    now = time.time()
    stats = {"skills": 0, "memories": 0, "session": "none"}

    # 1. Batch save skills
    if req.skills:
        created = 0
        updated = 0
        for s in req.skills:
            key = hashlib.sha256(
                f"{s.name}:{s.domain}:{s.pattern[:80]}".encode()
            ).hexdigest()[:16]
            try:
                conn.execute(
                    """INSERT INTO skills (skill_key, name, domain, pattern, weight,
                       use_count, success_count, created_at, last_used, source)
                       VALUES (?, ?, ?, ?, ?, 0, 0, ?, 0, ?)""",
                    (key, s.name, s.domain, s.pattern, s.weight, now, s.source),
                )
                created += 1
            except conn.IntegrityError:
                conn.execute(
                    "UPDATE skills SET pattern=?, weight=MAX(weight,?), last_used=? WHERE skill_key=?",
                    (s.pattern, s.weight, now, key),
                )
                updated += 1
        stats["skills"] = created + updated

        # Sync embeddings for new/updated skills
        try:
            from .vec_sync import sync_row_embedding
            for s in req.skills:
                key = hashlib.sha256(
                    f"{s.name}:{s.domain}:{s.pattern[:80]}".encode()
                ).hexdigest()[:16]
                row = conn.execute(
                    "SELECT id FROM skills WHERE skill_key=?", (key,)
                ).fetchone()
                if row:
                    sync_row_embedding(conn, "skills", row["id"], {
                        "name": s.name, "domain": s.domain, "pattern": s.pattern,
                    })
        except Exception:
            pass  # non-critical

    # 2. Save memories (dedup by content prefix)
    if req.memories:
        saved = 0
        for m in req.memories:
            # Dedup: check if similar memory already exists
            prefix = m.content[:40]
            existing = conn.execute(
                "SELECT id FROM memories WHERE content LIKE ? AND domain=? LIMIT 1",
                (f"{prefix}%", m.domain),
            ).fetchone()
            if existing:
                continue  # skip duplicate

            conn.execute(
                """INSERT INTO memories (session_id, category, content, domain,
                   confidence, use_count, weight, created_at, last_used)
                   VALUES (?, ?, ?, ?, ?, 0, 1.0, ?, 0)""",
                (req.session_id, m.category, m.content, m.domain, m.confidence, now),
            )
            saved += 1
        stats["memories"] = saved

        # Sync embeddings for new memories
        if saved > 0:
            try:
                from .vec_sync import sync_row_embedding
                new_rows = conn.execute(
                    "SELECT id, content, domain, category FROM memories WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (req.session_id, saved),
                ).fetchall()
                for row in new_rows:
                    sync_row_embedding(conn, "memories", row["id"], {
                        "content": row["content"],
                        "domain": row["domain"],
                        "category": row["category"],
                    })
            except Exception:
                pass

    # 3. Create or update session record
    existing = conn.execute(
        "SELECT id, changed_files FROM sessions WHERE session_id=?",
        (req.session_id,),
    ).fetchone()

    if existing:
        # Merge changed_files
        try:
            old_files = json.loads(existing["changed_files"])
        except Exception:
            old_files = []
        merged = list(dict.fromkeys(old_files + req.changed_files))  # dedup, preserve order
        conn.execute(
            "UPDATE sessions SET changed_files=?, goal=CASE WHEN goal='' THEN ? ELSE goal END WHERE session_id=?",
            (json.dumps(merged[:100]), req.goal, req.session_id),
        )
        stats["session"] = "updated"
    else:
        conn.execute(
            """INSERT INTO sessions (session_id, tool, goal, outcome, changed_files,
               lessons, duration_sec, created_at)
               VALUES (?, 'claude_code', ?, 'partial', ?, '', 0, ?)""",
            (req.session_id, req.goal, json.dumps(req.changed_files[:100]), now),
        )
        stats["session"] = "created"

    # 4. Log flush event
    conn.execute(
        """INSERT INTO events (event_id, source, event_type, outcome, details, recorded_at)
           VALUES (?, 'claude_code', 'session_flush', 'ok', ?, ?)""",
        (
            str(uuid.uuid4())[:8],
            json.dumps(stats),
            now,
        ),
    )

    conn.commit()
    return ApiResponse(ok=True, data=stats)


def _save_extracted_skills(conn, skills, now):
    """Save skills extracted from git diff into skills table."""
    for s in skills:
        key = hashlib.sha256(
            f"{s['name']}:{s['domain']}:{s['pattern'][:80]}".encode()
        ).hexdigest()[:16]
        try:
            conn.execute(
                """INSERT INTO skills (skill_key, name, domain, pattern, weight,
                   use_count, success_count, created_at, last_used, source, code_example)
                   VALUES (?, ?, ?, ?, ?, 0, 0, ?, 0, ?, ?)""",
                (key, s["name"], s["domain"], s["pattern"],
                 s.get("weight", 0.5), now, s.get("source", "git_diff"),
                 s.get("code_example", "")),
            )
        except conn.IntegrityError:
            # Update: merge code_example if we have one and existing doesn't
            existing = conn.execute(
                "SELECT code_example FROM skills WHERE skill_key=?", (key,)
            ).fetchone()
            new_example = s.get("code_example", "")
            if new_example and (not existing or not existing["code_example"]):
                conn.execute(
                    "UPDATE skills SET code_example=?, weight=MAX(weight,?), last_used=? WHERE skill_key=?",
                    (new_example, s.get("weight", 0.5), now, key),
                )
            else:
                conn.execute(
                    "UPDATE skills SET weight=MAX(weight,?), last_used=? WHERE skill_key=?",
                    (s.get("weight", 0.5), now, key),
                )
    conn.commit()

    # Sync embeddings for new skills
    try:
        from .vec_sync import sync_row_embedding
        for s in skills:
            key = hashlib.sha256(
                f"{s['name']}:{s['domain']}:{s['pattern'][:80]}".encode()
            ).hexdigest()[:16]
            row = conn.execute("SELECT id FROM skills WHERE skill_key=?", (key,)).fetchone()
            if row:
                sync_row_embedding(conn, "skills", row["id"], {
                    "name": s["name"], "domain": s["domain"], "pattern": s["pattern"],
                })
    except Exception:
        pass
