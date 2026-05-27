"""Vector similarity search — sqlite-vec cosine + LIKE fallback."""
import struct
import logging
from typing import List, Optional

from .embedding import embed_text, vec_to_blob, blob_to_vec, EMBEDDING_DIM

logger = logging.getLogger("evo.vec_search")

# Table configs: (content_table, vec_table, text_fields_for_embedding)
VEC_TABLES = {
    "skills": {
        "vec_table": "skills_vec",
        "text_fields": ["name", "domain", "pattern"],
    },
    "patterns": {
        "vec_table": "patterns_vec",
        "text_fields": ["name", "domain", "description"],
    },
    "failure_patterns": {
        "vec_table": "failures_vec",
        "text_fields": ["error_type", "description", "fix_suggestion", "domain"],
    },
    "memories": {
        "vec_table": "memories_vec",
        "text_fields": ["content", "domain", "category"],
    },
}


def vec_search(conn, table: str, query: str, limit: int = 10,
               min_weight: float = 0.0, domain: str = "") -> List[dict]:
    """Vector similarity search using sqlite-vec cosine distance.

    1. Embed the query text
    2. Search vec table for nearest neighbors
    3. Join with content table for full row data
    4. Fallback to LIKE if vec search fails

    Returns list of dicts with all columns + _score (cosine similarity 0-1, higher=more similar).
    """
    config = VEC_TABLES.get(table)
    if not config:
        return _like_fallback(conn, table, query, limit, min_weight, domain)

    vec_table = config["vec_table"]

    # Embed query
    query_vec = embed_text(query)
    if query_vec is None:
        logger.debug("Embedding failed, falling back to LIKE")
        return _like_fallback(conn, table, query, limit, min_weight, domain)

    query_blob = vec_to_blob(query_vec)

    try:
        # vec_distance_cosine returns distance (0=identical, 2=opposite)
        # We convert to similarity: 1 - distance/2 → range [0, 1]
        sql = f"""
            SELECT id, (1.0 - distance / 2.0) AS similarity
            FROM (
                SELECT id, vec_distance_cosine(embedding, :qblob) AS distance
                FROM {vec_table}
                ORDER BY distance
                LIMIT :lim
            )
        """
        params = {"qblob": query_blob, "lim": limit * 2}
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            return _like_fallback(conn, table, query, limit, min_weight, domain)

        # Join with content table
        ids = [r["id"] for r in rows]
        sim_map = {r["id"]: r["similarity"] for r in rows}
        placeholders = ",".join("?" * len(ids))
        content_rows = conn.execute(
            f"SELECT * FROM {table} WHERE id IN ({placeholders})", ids
        ).fetchall()

        result = []
        for r in content_rows:
            d = dict(r)
            d["_score"] = sim_map.get(d["id"], 0.0)

            # Apply domain filter
            if domain and d.get("domain") != domain:
                continue

            # Apply weight filter
            if min_weight > 0:
                wcol = "weight" if "weight" in d else "confidence"
                if d.get(wcol, 0) < min_weight:
                    continue

            result.append(d)

        result.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return result[:limit]

    except Exception as e:
        logger.debug(f"Vec search failed on {vec_table}, falling back to LIKE: {e}")
        return _like_fallback(conn, table, query, limit, min_weight, domain)


def _like_fallback(conn, table: str, query: str, limit: int,
                   min_weight: float, domain: str) -> List[dict]:
    """Fallback LIKE-based search when vec search is unavailable."""
    keywords = [w.lower() for w in query.split() if len(w) >= 3][:5]
    if not keywords:
        # No searchable keywords — just return top by weight
        wcol = "weight" if table == "skills" else "confidence"
        where = f"WHERE {wcol} > ?" if min_weight > 0 else ""
        params = [min_weight] if min_weight > 0 else []
        if domain:
            where = f"{where} AND domain=?" if where else "WHERE domain=?"
            params.append(domain)
        rows = conn.execute(
            f"SELECT * FROM {table} {where} ORDER BY {wcol} DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [_add_neutral_score(dict(r)) for r in rows]

    # Build LIKE clauses
    search_cols = _search_columns(table)
    like_parts = []
    like_params = []
    for col in search_cols:
        for kw in keywords:
            like_parts.append(f"{col} LIKE ?")
            like_params.append(f"%{kw}%")

    where = f"({' OR '.join(like_parts)})"
    if domain:
        where += " AND domain=?"
        like_params.append(domain)

    wcol = "weight" if table == "skills" else "confidence"
    if min_weight > 0:
        where += f" AND {wcol} > ?"
        like_params.append(min_weight)

    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {where} ORDER BY {wcol} DESC LIMIT ?",
        like_params + [limit],
    ).fetchall()
    return [_add_neutral_score(dict(r)) for r in rows]


def _search_columns(table: str) -> List[str]:
    return {
        "skills": ["name", "domain", "pattern"],
        "patterns": ["name", "domain", "description"],
        "failure_patterns": ["error_type", "description", "fix_suggestion"],
        "memories": ["content", "domain", "category"],
    }.get(table, ["name", "description"])


def _add_neutral_score(d: dict) -> dict:
    d["_score"] = 0.5
    return d


def build_embed_text(row: dict, text_fields: List[str]) -> str:
    """Build embedding text from a database row's fields."""
    parts = []
    for f in text_fields:
        val = row.get(f, "")
        if val:
            parts.append(str(val))
    return " ".join(parts)
