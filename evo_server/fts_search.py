"""BM25 search engine with LIKE fallback — the core search primitive."""
import sqlite3
import logging
import re
from typing import List, Optional

logger = logging.getLogger("evo.fts_search")


def _build_fts_query(keywords: List[str]) -> str:
    """Build FTS5 MATCH query from keywords.

    Uses OR matching — any keyword match counts. Quoted to avoid FTS5 syntax errors.
    """
    safe = [re.sub(r'[^\w_]', '', k) for k in keywords if k]
    return " OR ".join(f'"{k}"' for k in safe if k)


def fts_search(conn: sqlite3.Connection, fts_table: str, query: str,
               limit: int = 10) -> List[dict]:
    """FTS5 MATCH + BM25 ranking. Returns list of {id, bm25_score, ...}."""
    sql = (
        f"SELECT rowid, bm25({fts_table}) AS bm25_score FROM {fts_table} "
        f"WHERE {fts_table} MATCH ? ORDER BY bm25_score LIMIT ?"
    )
    rows = conn.execute(sql, (query, limit)).fetchall()
    return [{"id": r["rowid"], "bm25_score": r["bm25_score"]} for r in rows]


def smart_search(conn: sqlite3.Connection, table: str, fts_table: str,
                 keywords: List[str], limit: int = 10, min_weight: float = 0.0,
                 domain: str = "") -> List[dict]:
    """Smart search: FTS5 BM25 first, auto-fallback to LIKE if FTS fails or returns nothing.

    Returns rows from `table` with an added `_score` field for ranking.
    """
    if not keywords:
        # No keywords — return top by weight/confidence
        order = "weight" if "weight" in _table_columns(conn, table) else "confidence"
        where = f"WHERE {order} > ?" if min_weight > 0 else ""
        params = [min_weight] if min_weight > 0 else []
        if domain:
            where = f"{where} AND domain=?" if where else f"WHERE domain=?"
            params.append(domain)
        rows = conn.execute(
            f"SELECT * FROM {table} {where} ORDER BY {order} DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    # Try FTS5 first
    fts_query = _build_fts_query(keywords)
    try:
        matches = fts_search(conn, fts_table, fts_query, limit * 2)
        if matches:
            ids = [m["id"] for m in matches]
            score_map = {m["id"]: m["bm25_score"] for m in matches}
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE id IN ({placeholders})", ids
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                bm25 = score_map.get(d["id"], 0)
                # Convert BM25 negative score to positive relevance (0-1 range, approx)
                d["_score"] = min(1.0, max(0.0, 1.0 + bm25 / 10.0))
                if domain and d.get("domain") != domain:
                    continue
                if min_weight > 0:
                    wcol = "weight" if "weight" in d else "confidence"
                    if d.get(wcol, 0) < min_weight:
                        continue
                result.append(d)
            result.sort(key=lambda x: x.get("_score", 0), reverse=True)
            return result[:limit]
    except Exception as e:
        logger.debug(f"FTS search failed, falling back to LIKE: {e}")

    # Fallback: LIKE search
    return _like_search(conn, table, keywords, limit, min_weight, domain)


def _like_search(conn: sqlite3.Connection, table: str, keywords: List[str],
                 limit: int, min_weight: float, domain: str) -> List[dict]:
    """Fallback LIKE-based search."""
    # Determine searchable columns based on table
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

    wcol = "weight" if table in ("skills",) else "confidence"
    if min_weight > 0:
        where += f" AND {wcol} > ?"
        like_params.append(min_weight)

    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {where} ORDER BY {wcol} DESC LIMIT ?",
        like_params + [limit],
    ).fetchall()
    result = [dict(r) for r in rows]
    for d in result:
        d["_score"] = 0.5  # neutral score for LIKE matches
    return result


def _search_columns(table: str) -> List[str]:
    """Columns to search for each table."""
    return {
        "skills": ["name", "pattern", "domain"],
        "patterns": ["name", "description", "domain"],
        "failure_patterns": ["description", "error_type", "fix_suggestion"],
        "memories": ["name", "pattern", "domain"],
    }.get(table, ["name", "description"])


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    """Get column names for a table."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}
    except Exception:
        return set()
