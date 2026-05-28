"""FTS5 index sync — rebuild and incremental updates."""
import sqlite3
import logging
from typing import List, Optional
from .db import get_conn

logger = logging.getLogger("evo.fts")

# FTS table definitions: (content_table, fts_table, indexed_columns)
_FTS_TABLES = [
    ("skills", "skills_fts", ["name", "domain", "pattern"]),
    ("patterns", "patterns_fts", ["name", "domain", "description"]),
    ("failure_patterns", "failures_fts", ["error_type", "description", "fix_suggestion", "fix_code", "domain"]),
    ("memories", "memories_fts", ["content", "domain", "category"]),
]


def rebuild_fts(conn: sqlite3.Connection, content_table: str, fts_table: str, columns: List[str]):
    """Full rebuild of a single FTS table from content table."""
    cols = ", ".join(columns)
    try:
        conn.execute(f"DELETE FROM {fts_table}")
        conn.execute(
            f"INSERT INTO {fts_table}(rowid, {cols}) "
            f"SELECT id, {cols} FROM {content_table}"
        )
        conn.commit()
        count = conn.execute(f"SELECT COUNT(*) FROM {fts_table}").fetchone()[0]
        logger.info(f"FTS rebuild {fts_table}: {count} rows")
    except Exception as e:
        logger.warning(f"FTS rebuild {fts_table} failed: {e}")


def rebuild_all_fts(conn: Optional[sqlite3.Connection] = None):
    """Rebuild all FTS tables from content tables."""
    if conn is None:
        conn = get_conn()
    for content_table, fts_table, columns in _FTS_TABLES:
        rebuild_fts(conn, content_table, fts_table, columns)


def sync_fts_row(conn: sqlite3.Connection, content_table: str, fts_table: str,
                 row_id: int, columns: List[str]):
    """Incremental sync: delete old + insert new for a single row."""
    cols = ", ".join(columns)
    try:
        conn.execute(f"DELETE FROM {fts_table} WHERE rowid = ?", (row_id,))
        conn.execute(
            f"INSERT INTO {fts_table}(rowid, {cols}) "
            f"SELECT id, {cols} FROM {content_table} WHERE id = ?",
            (row_id,),
        )
    except Exception as e:
        logger.warning(f"FTS sync {fts_table} row {row_id} failed: {e}")


def sync_fts_by_key(conn: sqlite3.Connection, content_table: str, fts_table: str,
                    key_column: str, key_value: str, columns: List[str]):
    """Sync FTS for a row identified by a key column (e.g. skill_key)."""
    row = conn.execute(f"SELECT id FROM {content_table} WHERE {key_column} = ?", (key_value,)).fetchone()
    if row:
        sync_fts_row(conn, content_table, fts_table, row["id"], columns)
