"""Embedding sync — populate and incremental-update vec tables."""
import logging
import sqlite3
from typing import List, Optional

from .embedding import embed_batch, vec_to_blob, build_search_text, EMBEDDING_DIM
from .vec_search import VEC_TABLES

logger = logging.getLogger("evo.vec_sync")


def rebuild_all_embeddings(conn: Optional[sqlite3.Connection] = None):
    """Rebuild all vec tables from content tables.

    Called on startup to ensure embeddings are in sync.
    Skips if vec tables are not available (sqlite-vec not loaded).
    """
    if conn is None:
        from .db import get_conn
        conn = get_conn()

    for content_table, config in VEC_TABLES.items():
        _rebuild_table(conn, content_table, config)


def _rebuild_table(conn: sqlite3.Connection, content_table: str, config: dict):
    """Rebuild embeddings for a single table."""
    vec_table = config["vec_table"]
    text_fields = config["text_fields"]

    # Check if vec table exists
    try:
        conn.execute(f"SELECT COUNT(*) FROM {vec_table}")
    except Exception:
        logger.debug(f"Vec table {vec_table} not available, skipping rebuild")
        return

    # Get all rows from content table
    rows = conn.execute(f"SELECT * FROM {content_table}").fetchall()
    if not rows:
        logger.info(f"No rows in {content_table}, skipping vec rebuild")
        return

    # Check existing embeddings
    existing_ids = set()
    try:
        for r in conn.execute(f"SELECT id FROM {vec_table}").fetchall():
            existing_ids.add(r["id"])
    except Exception:
        pass

    # Filter to rows without embeddings
    new_rows = [r for r in rows if dict(r)["id"] not in existing_ids]
    if not new_rows:
        logger.info(f"All {len(rows)} rows in {content_table} already embedded")
        return

    logger.info(f"Embedding {len(new_rows)} new rows for {content_table}...")

    # Build texts for embedding
    texts = []
    for row in new_rows:
        rd = dict(row)
        text = build_search_text(
            name=rd.get("name", ""),
            domain=rd.get("domain", ""),
            description=rd.get("description", rd.get("pattern", "")),
            pattern=rd.get("pattern", ""),
            extra=rd.get("error_type", "") + " " + rd.get("fix_suggestion", ""),
        )
        texts.append(text)

    # Batch embed (Alibaba API max batch size = 10)
    batch_size = 8
    total_embedded = 0
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]
        batch_rows = new_rows[i:i + batch_size]

        embeddings = embed_batch(batch_texts)
        if not embeddings:
            logger.warning(f"Embedding batch failed at offset {i}, stopping")
            break

        for row, emb in zip(batch_rows, embeddings):
            row_id = dict(row)["id"]
            blob = vec_to_blob(emb)
            try:
                conn.execute(f"DELETE FROM {vec_table} WHERE id = ?", (row_id,))
                conn.execute(
                    f"INSERT INTO {vec_table} (id, embedding) VALUES (?, ?)",
                    (row_id, blob),
                )
                total_embedded += 1
            except Exception as e:
                logger.warning(f"Insert embedding failed for {content_table} id={row_id}: {e}")

    conn.commit()
    logger.info(f"Embedded {total_embedded}/{len(new_rows)} rows for {content_table}")


def sync_row_embedding(conn: sqlite3.Connection, content_table: str,
                       row_id: int, row_data: dict):
    """Embed a single row and insert/update its vec entry.

    Called after INSERT/UPDATE on content tables.
    """
    config = VEC_TABLES.get(content_table)
    if not config:
        return

    vec_table = config["vec_table"]
    text_fields = config["text_fields"]

    # Build search text
    text = build_search_text(
        name=row_data.get("name", ""),
        domain=row_data.get("domain", ""),
        description=row_data.get("description", row_data.get("pattern", "")),
        pattern=row_data.get("pattern", ""),
        extra=row_data.get("error_type", "") + " " + row_data.get("fix_suggestion", ""),
    )

    from .embedding import embed_text
    emb = embed_text(text)
    if emb is None:
        logger.warning(f"Embed failed for {content_table} id={row_id}")
        return

    blob = vec_to_blob(emb)
    try:
        conn.execute(f"DELETE FROM {vec_table} WHERE id = ?", (row_id,))
        conn.execute(
            f"INSERT INTO {vec_table} (id, embedding) VALUES (?, ?)",
            (row_id, blob),
        )
    except Exception as e:
        logger.warning(f"Vec sync failed for {content_table} id={row_id}: {e}")
