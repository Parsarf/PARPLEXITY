"""
Keyword-based retrieval v1: tokenize query and chunk text, score by term frequency,
apply diversity cap (per-source limit), return top_k scored chunks.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import Chunk

# Small stopword set for optional removal
STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
     "have", "has", "had", "do", "does", "did", "will", "would", "could",
     "should", "may", "might", "must", "can", "to", "of", "in", "for",
     "on", "with", "at", "by", "from", "as", "it", "its", "or", "and", "but"}
)

MIN_TOKEN_LEN = 2
MAX_CHUNKS_TO_SCORE = 300


def tokenize(text: str) -> list[str]:
    """
    Lowercase, split on non-alphanumeric, drop short tokens, remove stopwords.
    Safe for empty or weird input.
    """
    if not text or not isinstance(text, str):
        return []
    # Lowercase and split on non-alphanumeric (keep letters and numbers)
    raw = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in raw if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS]


def score_text(query_tokens: list[str], text: str) -> float:
    """
    Frequency-based score: count how often each query token appears in text.
    Bonus for multiple occurrences. Returns 0.0 if no matches or empty query.
    """
    if not query_tokens or not text:
        return 0.0
    text_tokens = tokenize(text)
    if not text_tokens:
        return 0.0
    text_lower = text.lower()
    score = 0.0
    for qt in query_tokens:
        if len(qt) < MIN_TOKEN_LEN:
            continue
        # Count occurrences (simple substring count for bonus on repeats)
        count = text_lower.count(qt)
        if count > 0:
            # Base score + bonus for multiple hits
            score += count * (1.0 + 0.2 * (count - 1))
    return score


def rank_chunks(
    query: str,
    chunks: list["Chunk"],
    *,
    top_k: int = 10,
    per_source_cap: int = 2,
) -> list[dict]:
    """
    Rank chunks by keyword relevance to query; apply diversity cap per source.
    Returns list of dicts compatible with ScoredChunk (chunk_id, source_url,
    source_title, chunk_index, text, score). Safe for empty query/chunks.
    """
    query_tokens = tokenize(query or "")
    if not query_tokens:
        return []

    # Guardrail: cap how many chunks we score (deterministic order)
    to_score = chunks[:MAX_CHUNKS_TO_SCORE] if chunks else []

    scored: list[tuple[float, dict]] = []
    for ch in to_score:
        text = (ch.text or "") if hasattr(ch, "text") else ""
        score = score_text(query_tokens, text)
        if score == 0.0:
            continue
        d = {
            "chunk_id": ch.chunk_id,
            "source_url": ch.source_url,
            "source_title": ch.source_title,
            "chunk_index": ch.chunk_index,
            "text": ch.text,
            "score": round(score, 4),
        }
        scored.append((score, d))

    # Sort by score descending
    scored.sort(key=lambda x: -x[0])

    # Diversity: at most per_source_cap chunks per source_url
    seen_per_source: dict[str, int] = {}
    out: list[dict] = []
    for _score, d in scored:
        if len(out) >= top_k:
            break
        url = str(d.get("source_url", ""))
        count = seen_per_source.get(url, 0)
        if count >= per_source_cap:
            continue
        seen_per_source[url] = count + 1
        out.append(d)

    return out
