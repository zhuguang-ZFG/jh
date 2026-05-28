"""Hybrid search — sqlite-vec cosine + FTS5 BM25 with RRF fusion.

Combines vector similarity search (semantic) with FTS5 full-text search (keyword)
using Reciprocal Rank Fusion for robust ranking.
Falls back to FTS5-only or LIKE if vector search is unavailable.
"""
import struct
import logging
from typing import List, Optional

from .embedding import embed_text, vec_to_blob, blob_to_vec, EMBEDDING_DIM

logger = logging.getLogger("evo.vec_search")

# Table configs: (content_table, vec_table, fts_table, text_fields_for_embedding)
VEC_TABLES = {
    "skills": {
        "vec_table": "skills_vec",
        "fts_table": "skills_fts",
        "text_fields": ["name", "domain", "pattern"],
    },
    "patterns": {
        "vec_table": "patterns_vec",
        "fts_table": "patterns_fts",
        "text_fields": ["name", "domain", "description"],
    },
    "failure_patterns": {
        "vec_table": "failures_vec",
        "fts_table": "failures_fts",
        "text_fields": ["error_type", "description", "fix_suggestion", "fix_code", "domain"],
    },
    "memories": {
        "vec_table": "memories_vec",
        "fts_table": "memories_fts",
        "text_fields": ["content", "domain", "category"],
    },
}

# RRF constant — higher k gives less weight to top-ranked items
_RRF_K = 60


def vec_search(conn, table: str, query: str, limit: int = 10,
               min_weight: float = 0.0, domain: str = "",
               precomputed_emb=None) -> List[dict]:
    """Hybrid vector + BM25 search with RRF fusion.

    1. Run vector similarity search (semantic)
    2. Run FTS5 BM25 search (keyword)
    3. Merge via Reciprocal Rank Fusion
    4. Fallback chain: hybrid → vector-only → FTS5-only → LIKE

    Returns list of dicts with all columns + _score (higher=more similar).
    """
    config = VEC_TABLES.get(table)
    if not config:
        return _like_fallback(conn, table, query, limit, min_weight, domain)

    vec_table = config["vec_table"]
    fts_table = config["fts_table"]

    # Embed query
    query_vec = precomputed_emb if precomputed_emb is not None else embed_text(query)

    # Try hybrid search
    if query_vec is not None:
        vec_results = _vec_search_raw(conn, vec_table, table, query_vec, limit * 2, min_weight, domain)
        bm25_results = _bm25_search(conn, fts_table, table, query, limit * 2, min_weight, domain)

        if vec_results and bm25_results:
            # Both succeeded — RRF fusion
            merged = _rrf_merge(vec_results, bm25_results, limit)
            if merged:
                return merged
        elif vec_results:
            # Only vector worked
            return vec_results[:limit]
        elif bm25_results:
            # Only BM25 worked
            return bm25_results[:limit]

    # Vector embedding failed — try FTS5 only
    if query_vec is None:
        logger.debug("Embedding failed, trying FTS5-only")
        bm25_results = _bm25_search(conn, fts_table, table, query, limit, min_weight, domain)
        if bm25_results:
            return bm25_results

    # FTS5 might not be available — try vector only
    if query_vec is not None:
        vec_results = _vec_search_raw(conn, vec_table, table, query_vec, limit, min_weight, domain)
        if vec_results:
            return vec_results

    # Last resort: LIKE fallback
    return _like_fallback(conn, table, query, limit, min_weight, domain)


def _vec_search_raw(conn, vec_table: str, content_table: str,
                    query_vec: list, limit: int,
                    min_weight: float, domain: str) -> List[dict]:
    """Raw vector cosine search. Returns results with _score or empty list."""
    query_blob = vec_to_blob(query_vec)

    try:
        sql = f"""
            SELECT id, (1.0 - distance / 2.0) AS similarity
            FROM (
                SELECT id, vec_distance_cosine(embedding, :qblob) AS distance
                FROM {vec_table}
                ORDER BY distance
                LIMIT :lim
            )
        """
        params = {"qblob": query_blob, "lim": limit}
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            return []

        ids = [r["id"] for r in rows]
        sim_map = {r["id"]: r["similarity"] for r in rows}
        placeholders = ",".join("?" * len(ids))
        content_rows = conn.execute(
            f"SELECT * FROM {content_table} WHERE id IN ({placeholders})", ids
        ).fetchall()

        result = []
        for r in content_rows:
            d = dict(r)
            d["_score"] = sim_map.get(d["id"], 0.0)
            if domain and d.get("domain") != domain:
                continue
            if min_weight > 0:
                wcol = "weight" if "weight" in d else "confidence"
                if d.get(wcol, 0) < min_weight:
                    continue
            result.append(d)

        result.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return result

    except Exception as e:
        logger.debug(f"Vec search failed on {vec_table}: {e}")
        return []


def _bm25_search(conn, fts_table: str, content_table: str,
                 query: str, limit: int,
                 min_weight: float, domain: str) -> List[dict]:
    """FTS5 keyword search. Returns results with _score or empty list.

    FTS5 MATCH returns results in relevance order by default.
    We use position-based scoring (not bm25() which returns NULL on
    older SQLite with content= external content tables).
    """
    fts_query = _build_fts_query(query)
    if not fts_query:
        return []

    try:
        # FTS5 MATCH returns results ordered by relevance (best first)
        # Use rowid ordering as a stable tiebreaker
        sql = f"""
            SELECT rowid
            FROM {fts_table}
            WHERE {fts_table} MATCH :q
            ORDER BY rowid
            LIMIT :lim
        """
        rows = conn.execute(sql, {"q": fts_query, "lim": limit}).fetchall()

        if not rows:
            return []

        # Get content rows
        ids = [r["rowid"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        content_rows = conn.execute(
            f"SELECT * FROM {content_table} WHERE id IN ({placeholders})", ids
        ).fetchall()

        # Position-based scoring: score decays with position
        # score = 1.0 / (1 + position * 0.1) — top result gets ~0.91, 10th gets ~0.5
        id_to_pos = {r["rowid"]: i for i, r in enumerate(rows)}
        result = []
        for r in content_rows:
            d = dict(r)
            pos = id_to_pos.get(d["id"], len(rows))
            d["_score"] = 1.0 / (1.0 + pos * 0.1)
            if domain and d.get("domain") != domain:
                continue
            if min_weight > 0:
                wcol = "weight" if "weight" in d else "confidence"
                if d.get(wcol, 0) < min_weight:
                    continue
            result.append(d)

        result.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return result

    except Exception as e:
        logger.debug(f"FTS5 search failed on {fts_table}: {e}")
        return []


def _build_fts_query(query: str) -> str:
    """Build an FTS5 MATCH query from free text.

    Handles special characters and builds an OR query for multiple terms.
    """
    # Split into tokens, filter short ones
    tokens = []
    for w in query.split():
        w = w.strip().lower()
        # Remove FTS5 special chars: " AND OR NOT * ( ) : -
        cleaned = ""
        for ch in w:
            if ch.isalnum() or ch in ("_", "."):
                cleaned += ch
        if len(cleaned) >= 2:
            tokens.append(cleaned)

    if not tokens:
        return ""

    # Build OR query — each token is a required term
    # Use prefix matching for partial matches: term*
    terms = []
    for t in tokens[:8]:  # cap at 8 terms
        # Escape any remaining special chars and add prefix wildcard
        terms.append(f'"{t}"')

    return " OR ".join(terms)


def _rrf_merge(list_a: List[dict], list_b: List[dict], limit: int) -> List[dict]:
    """Merge two ranked lists using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank_i)) for each list where item appears.
    k=60 is the standard constant (Cormack et al., 2009).
    """
    # Build id->rank maps (1-based rank)
    rank_a = {}
    for i, item in enumerate(list_a):
        rank_a[item["id"]] = i + 1

    rank_b = {}
    for i, item in enumerate(list_b):
        rank_b[item["id"]] = i + 1

    # Merge all unique items
    all_items = {}
    for item in list_a:
        all_items[item["id"]] = item.copy()
    for item in list_b:
        if item["id"] not in all_items:
            all_items[item["id"]] = item.copy()

    # Compute RRF scores
    for item_id, item in all_items.items():
        rrf_score = 0.0
        if item_id in rank_a:
            rrf_score += 1.0 / (_RRF_K + rank_a[item_id])
        if item_id in rank_b:
            rrf_score += 1.0 / (_RRF_K + rank_b[item_id])
        item["_score"] = rrf_score

    # Sort by RRF score descending
    merged = sorted(all_items.values(), key=lambda x: x["_score"], reverse=True)
    return merged[:limit]


def _like_fallback(conn, table: str, query: str, limit: int,
                   min_weight: float, domain: str) -> List[dict]:
    """Fallback LIKE-based search when both vec and FTS5 are unavailable."""
    keywords = [w.lower() for w in query.split() if len(w) >= 3][:5]
    if not keywords:
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
        "failure_patterns": ["error_type", "description", "fix_suggestion", "fix_code"],
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
