"""Embedding API — Alibaba text-embedding-v3 with batch + cache."""
import json
import time
import struct
import logging
import urllib.request
import urllib.error
from typing import List, Optional

logger = logging.getLogger("evo.embedding")

# Alibaba DashScope (OpenAI-compatible) embedding endpoint
EMBEDDING_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_DIM = 1024

_api_key: Optional[str] = None


def configure(api_key: str):
    global _api_key
    _api_key = api_key


def _get_key() -> str:
    if _api_key:
        return _api_key
    # Fallback to env
    import os
    key = os.getenv("ALIBABA_EMBEDDING_API_KEY", "")
    if not key:
        key = os.getenv("ALIBABA_API_KEY", "")
    return key


def embed_text(text: str) -> Optional[List[float]]:
    """Embed a single text string. Returns 1024-dim vector or None on error."""
    results = embed_batch([text])
    return results[0] if results else None


def embed_batch(texts: List[str], max_retries: int = 2) -> List[List[float]]:
    """Embed a batch of texts. Returns list of 1024-dim vectors.

    On failure, returns empty list. Retries on transient errors.
    """
    if not texts:
        return []

    api_key = _get_key()
    if not api_key:
        logger.warning("No Alibaba API key configured for embeddings")
        return []

    payload = json.dumps({
        "model": EMBEDDING_MODEL,
        "input": texts,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                EMBEDDING_URL, data=payload, method="POST", headers=headers,
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
                data = body.get("data", [])
                # Sort by index to preserve order
                data.sort(key=lambda x: x.get("index", 0))
                return [item["embedding"] for item in data]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.warning(f"Embedding API error (attempt {attempt+1}): {e.code} {body[:200]}")
            if e.code in (429, 500, 502, 503) and attempt < max_retries:
                time.sleep(1 * (attempt + 1))
                continue
            return []
        except Exception as e:
            logger.warning(f"Embedding API exception (attempt {attempt+1}): {e}")
            if attempt < max_retries:
                time.sleep(1)
                continue
            return []

    return []


def vec_to_blob(vec: List[float]) -> bytes:
    """Pack a float vector into a bytes blob for sqlite-vec storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def blob_to_vec(blob: bytes, dim: int = EMBEDDING_DIM) -> List[float]:
    """Unpack a bytes blob from sqlite-vec back into a float vector."""
    return list(struct.unpack(f"{dim}f", blob))


# Simple in-memory cache: text -> embedding
_cache: dict = {}
_CACHE_MAX = 500


def embed_text_cached(text: str) -> Optional[List[float]]:
    """Embed with in-memory cache to avoid repeated API calls."""
    if text in _cache:
        return _cache[text]
    vec = embed_text(text)
    if vec is not None:
        if len(_cache) >= _CACHE_MAX:
            # Evict oldest entries (simple: clear half)
            keys = list(_cache.keys())[:_CACHE_MAX // 2]
            for k in keys:
                del _cache[k]
        _cache[text] = vec
    return vec


def embed_for_storage(text: str) -> Optional[bytes]:
    """Embed text and return as bytes blob ready for sqlite-vec."""
    vec = embed_text_cached(text)
    if vec is None:
        return None
    return vec_to_blob(vec)


def build_search_text(name: str, domain: str, description: str = "",
                      pattern: str = "", extra: str = "") -> str:
    """Build a rich text representation for embedding from structured fields.

    Combines fields into a meaningful search text for semantic matching.
    """
    parts = []
    if name:
        parts.append(name)
    if domain:
        parts.append(f"in {domain} domain")
    if description:
        parts.append(description)
    if pattern:
        parts.append(pattern)
    if extra:
        parts.append(extra)
    return " ".join(parts)
