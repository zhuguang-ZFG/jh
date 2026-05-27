"""Cross-project knowledge sharing API."""
import hashlib
import json
import time
from fastapi import APIRouter, Body
from .db import get_conn
from .models import ApiResponse

router = APIRouter(prefix="/shared", tags=["shared"])


@router.post("/publish")
def publish_knowledge(
    project_name: str = Body(...),
    knowledge_type: str = Body(...),
    name: str = Body(...),
    domain: str = Body(...),
    content: str = Body(...),
    confidence: float = Body(0.5),
):
    """Publish a skill or pattern to the shared knowledge pool."""
    conn = get_conn()
    now = time.time()
    key = hashlib.sha256(f"{project_name}:{knowledge_type}:{name[:80]}".encode()).hexdigest()[:16]
    try:
        conn.execute(
            """INSERT INTO shared_knowledge
               (share_key, project_name, knowledge_type, name, domain, content, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, project_name, knowledge_type, name, domain, content, confidence, now),
        )
        conn.commit()
        return ApiResponse(ok=True, data={"share_key": key})
    except conn.IntegrityError:
        return ApiResponse(ok=False, data={"error": "Already published"})


@router.get("")
def list_shared(knowledge_type: str = "", project_name: str = "", limit: int = 20):
    """List available shared knowledge."""
    conn = get_conn()
    conditions = ["imported_by = ''"]
    params = []
    if knowledge_type:
        conditions.append("knowledge_type=?")
        params.append(knowledge_type)
    if project_name:
        conditions.append("project_name=?")
        params.append(project_name)
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM shared_knowledge WHERE {' AND '.join(conditions)} "
        f"ORDER BY confidence DESC, created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return ApiResponse(ok=True, data=[dict(r) for r in rows])


@router.post("/import")
def import_knowledge(
    share_key: str = Body(...),
    target_project: str = Body(...),
):
    """Import shared knowledge into a project."""
    conn = get_conn()
    now = time.time()
    row = conn.execute(
        "SELECT * FROM shared_knowledge WHERE share_key=?", (share_key,)
    ).fetchone()
    if not row:
        return ApiResponse(ok=False, data={"error": "Not found"})
    if row["imported_by"]:
        return ApiResponse(ok=False, data={"error": "Already imported"})

    # Mark as imported
    conn.execute(
        "UPDATE shared_knowledge SET imported_by=? WHERE share_key=?",
        (target_project, share_key),
    )

    # Also add to local skills/patterns
    if row["knowledge_type"] == "skill":
        skill_key = hashlib.sha256(f"{row['name'][:80]}".encode()).hexdigest()[:16]
        try:
            conn.execute(
                """INSERT INTO skills (skill_key, name, domain, pattern, weight, created_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, 'shared_import')""",
                (skill_key, row["name"], row["domain"], row["content"],
                 row["confidence"], now),
            )
        except conn.IntegrityError:
            pass
    elif row["knowledge_type"] == "pattern":
        pattern_key = hashlib.sha256(f"{row['name'][:80]}".encode()).hexdigest()[:16]
        try:
            conn.execute(
                """INSERT INTO patterns (pattern_key, name, domain, description, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (pattern_key, row["name"], row["domain"], row["content"],
                 row["confidence"], now),
            )
        except conn.IntegrityError:
            pass

    conn.commit()
    return ApiResponse(ok=True, data={"imported": True, "type": row["knowledge_type"]})


@router.get("/stats")
def shared_stats():
    """Get sharing statistics."""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM shared_knowledge").fetchone()["c"]
    available = conn.execute(
        "SELECT COUNT(*) c FROM shared_knowledge WHERE imported_by = ''"
    ).fetchone()["c"]
    imported = conn.execute(
        "SELECT COUNT(*) c FROM shared_knowledge WHERE imported_by != ''"
    ).fetchone()["c"]
    by_project = conn.execute(
        "SELECT project_name, COUNT(*) as count FROM shared_knowledge "
        "GROUP BY project_name ORDER BY count DESC"
    ).fetchall()
    return ApiResponse(ok=True, data={
        "total": total,
        "available": available,
        "imported": imported,
        "by_project": [dict(r) for r in by_project],
    })
