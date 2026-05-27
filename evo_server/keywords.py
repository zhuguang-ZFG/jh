"""Unified keyword extraction — single source of truth for all search endpoints."""
import re
from typing import List

# Stop words (migrated from api_context.py)
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "this", "that",
    "these", "those", "it", "its", "and", "or", "not", "but", "if",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us",
    "my", "your", "his", "our", "their", "what", "which", "who", "whom",
    "how", "when", "where", "why", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "no", "only",
    "same", "than", "too", "very", "just", "also", "now", "here",
    "there", "then", "so", "up", "out", "about", "get", "got",
    "make", "made", "let", "need", "use", "using", "used",
    "fix", "add", "create", "update", "change", "remove", "delete",
    "help", "please", "want", "try", "implement", "build",
})


def extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """Extract meaningful keywords from text.

    Strategy: regex [a-zA-Z_]{3,} → lowercase → remove stop words → deduplicate → cap.
    This is the unified extraction used by all search endpoints.
    """
    if not text:
        return []
    words = re.findall(r"[a-zA-Z_]{3,}", text.lower())
    seen = set()
    result = []
    for w in words:
        if w not in _STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
        if len(result) >= max_keywords:
            break
    return result
