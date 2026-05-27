"""Memories — vectorized cross-session knowledge storage."""
import json
import time
import logging
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from .db import get_conn
from .models import ApiResponse
from .vec_search import vec_search
from .embedding import embed_text, vec_to_blob

logger = logging.getLogger("evo.memories")

router = APIRouter(prefix="/memories", tags=["memories"])

DEDUP_COSINE_THRESHOLD = 0.85


def _sync_memory_embedding(conn, row_id, content, domain, category):
    text = f"{content} {domain} {category}"
    emb = embed_text(text)
    if emb is None:
        return
    blob = vec_to_blob(emb)
    try:
        conn.execute("DELETE FROM memories_vec WHERE id = ?", (row_id,))
        conn.execute(
            "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
            (row_id, blob),
        )
    except Exception:
        pass


@router.post("/")
def create_memory(
    session_id: str = Body(""),
    category: str = Body(...),
    content: str = Body(...),
    domain: str = Body("general"),
    confidence: float = Body(0.5),
):
    """Create a memory with auto-vectorization. Deduplicates via cosine similarity."""
    conn = get_conn()
    now = time.time()

    # Dedup check: search for similar existing memories
    if confidence >= 0.6:
        similar = vec_search(conn, "memories", content, limit=3, min_weight=0.1)
        for s in similar:
            if s.get("_score", 0) >= DEDUP_COSINE_THRESHOLD:
                # Merge: boost weight and use_count
                conn.execute(
                    "UPDATE memories SET use_count = use_count + 1, "
                    "weight = MIN(weight * 1.05, 5.0), last_used = ? WHERE id = ?",
                    (now, s["id"]),
                )
                conn.commit()
                return ApiResponse(ok=True, data={"id": s["id"], "merged": True})

    try:
        conn.execute(
            "INSERT INTO memories (session_id, category, content, domain, "
            "confidence, use_count, weight, created_at, last_used) "
            "VALUES (?, ?, ?, ?, ?, 0, 1.0, ?, ?)",
            (session_id, category, content, domain, confidence, now, now),
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _sync_memory_embedding(conn, row_id, content, domain, category)
    except Exception as e:
        return ApiResponse(ok=False, message=str(e))

    conn.commit()
    return ApiResponse(ok=True, data={"id": row_id, "merged": False})


@router.post("/recall")
def recall_memories(
    query: str = Body(...),
    limit: int = Body(5),
    min_weight: float = Body(0.1),
    domain: str = Body(""),
):
    """Semantic recall of relevant memories."""
    conn = get_conn()
    results = vec_search(conn, "memories", query, limit=limit,
                         min_weight=min_weight, domain=domain)

    # Update use_count and last_used for recalled memories
    now = time.time()
    for r in results:
        conn.execute(
            "UPDATE memories SET use_count = use_count + 1, last_used = ? WHERE id = ?",
            (now, r["id"]),
        )
    conn.commit()

    return ApiResponse(ok=True, data=[
        {k: v for k, v in r.items() if k != "_score"}
        for r in results
    ])


@router.get("/")
def list_memories(
    domain: str = "",
    category: str = "",
    limit: int = 50,
):
    conn = get_conn()
    conditions = []
    params = []
    if domain:
        conditions.append("domain = ?")
        params.append(domain)
    if category:
        conditions.append("category = ?")
        params.append(category)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM memories{where} ORDER BY weight DESC, created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.delete("/{memory_id}")
def delete_memory(memory_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    try:
        conn.execute("DELETE FROM memories_vec WHERE id = ?", (memory_id,))
    except Exception:
        pass
    conn.commit()
    return ApiResponse(ok=True, data={"deleted": memory_id})


# ── LLM-enhanced memory extraction ─────────────────────────────

class TranscriptSummary(BaseModel):
    user_messages: List[str] = Field(default_factory=list)
    files_edited: List[str] = Field(default_factory=list)
    bash_commands: List[str] = Field(default_factory=list)
    errors_encountered: List[str] = Field(default_factory=list)
    outcome: str = ""


class MemoryExtractRequest(BaseModel):
    session_id: str = ""
    transcript_summary: TranscriptSummary
    domain: str = "general"
    max_memories: int = Field(default=5, ge=1, le=10)


EXTRACT_PROMPT = """Analyze this coding session and extract key memories for future sessions.
Return ONLY a JSON array of objects with keys: category, content, domain, confidence

Categories: decision (user preference/workflow choice), lesson (error learned/warning), context (project state/constraint), pattern (reusable technique)

Rules:
- Max {max_memories} memories
- Each memory: 1-2 sentences, actionable
- Skip noise (system messages, console output, test results unless they reveal patterns)
- Skip credentials/secrets/tokens
- Higher confidence for decisions and error lessons (0.7-0.9)
- Lower for patterns and context (0.4-0.6)
- Return ONLY the JSON array, no explanation

Session data:
Outcome: {outcome}
User messages: {user_messages}
Files edited: {files_edited}
Bash commands: {bash_commands}
Errors: {errors_encountered}"""


def _is_credential_content(text: str) -> bool:
    """Check if content contains credentials or secrets."""
    lower = text.lower()
    credential_patterns = [
        "api_key", "api secret", "token", "password", "credential",
        "private_key", "secret_key", "access_key", "auth_token",
        "bearer ", "sk-", "ak_", "pk_",
    ]
    return any(p in lower for p in credential_patterns)


@router.post("/extract")
async def extract_memories(req: MemoryExtractRequest):
    """LLM-enhanced memory extraction from session transcript.

    Uses free LLM backends to analyze session data and extract high-quality
    structured memories. Falls back to empty list if LLM fails.
    """
    from .llm_bridge import chat

    ts = req.transcript_summary

    # Build summary for LLM
    user_msgs = "; ".join(ts.user_messages[:10])
    files = ", ".join(ts.files_edited[:20])
    cmds = "; ".join(ts.bash_commands[:15])
    errors = "; ".join(ts.errors_encountered[:5])

    prompt = EXTRACT_PROMPT.format(
        max_memories=req.max_memories,
        outcome=ts.outcome or "unknown",
        user_messages=user_msgs or "(none)",
        files_edited=files or "(none)",
        bash_commands=cmds or "(none)",
        errors_encountered=errors or "(none)",
    )

    try:
        response = await chat(
            prompt,
            system="You are a coding session analyst. Extract memories from session transcripts.",
            temperature=0.3,
            max_backends=5,
        )
    except Exception as e:
        logger.warning(f"LLM memory extraction failed: {e}")
        return ApiResponse(ok=True, data={"memories": [], "saved": 0, "error": str(e)})

    if not response:
        return ApiResponse(ok=True, data={"memories": [], "saved": 0, "error": "no LLM response"})

    # Parse LLM response
    memories = []
    try:
        # Try direct JSON parse
        memories = json.loads(response)
    except json.JSONDecodeError:
        # Try extracting JSON array from response
        import re
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if match:
            try:
                memories = json.loads(match.group())
            except json.JSONDecodeError:
                pass

    if not isinstance(memories, list):
        return ApiResponse(ok=True, data={"memories": [], "saved": 0, "error": "no JSON array in response"})

    # Filter and save
    conn = get_conn()
    now = time.time()
    saved = 0
    valid_memories = []

    for m in memories:
        if not isinstance(m, dict):
            continue
        content = m.get("content", "").strip()
        if not content or len(content) < 10:
            continue
        if _is_credential_content(content):
            continue

        category = m.get("category", "context")
        if category not in ("decision", "lesson", "context", "pattern"):
            category = "context"
        domain = m.get("domain", req.domain) or req.domain
        confidence = float(m.get("confidence", 0.5))
        confidence = max(0.1, min(1.0, confidence))

        valid_memories.append({
            "category": category,
            "content": content,
            "domain": domain,
            "confidence": confidence,
        })

    # Save with dedup (reuse existing create logic)
    for m in valid_memories[:req.max_memories]:
        content = m["content"]
        domain = m["domain"]
        category = m["category"]
        confidence = m["confidence"]

        # Dedup check
        if confidence >= 0.6:
            similar = vec_search(conn, "memories", content, limit=3, min_weight=0.1)
            merged = False
            for s in similar:
                if s.get("_score", 0) >= DEDUP_COSINE_THRESHOLD:
                    conn.execute(
                        "UPDATE memories SET use_count = use_count + 1, "
                        "weight = MIN(weight * 1.05, 5.0), last_used = ? WHERE id = ?",
                        (now, s["id"]),
                    )
                    merged = True
                    break
            if merged:
                continue

        try:
            conn.execute(
                "INSERT INTO memories (session_id, category, content, domain, "
                "confidence, use_count, weight, created_at, last_used) "
                "VALUES (?, ?, ?, ?, ?, 0, 1.0, ?, ?)",
                (req.session_id, category, content, domain, confidence, now, now),
            )
            row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            _sync_memory_embedding(conn, row_id, content, domain, category)
            saved += 1
        except Exception as e:
            logger.warning(f"Failed to save memory: {e}")

    conn.commit()

    return ApiResponse(ok=True, data={
        "memories": valid_memories[:req.max_memories],
        "saved": saved,
    })
