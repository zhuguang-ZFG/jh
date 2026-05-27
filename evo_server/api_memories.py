"""Memories — vectorized cross-session knowledge storage."""
import time
from fastapi import APIRouter, Body
from .db import get_conn
from .models import ApiResponse
from .vec_search import vec_search
from .embedding import embed_text, vec_to_blob

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
