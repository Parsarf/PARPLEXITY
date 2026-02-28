"""
Structure-aware chunking: split text into units by paragraphs, pack into chunks
with min/max word limits, filter boilerplate, deduplicate.
"""

import hashlib
import re
from typing import Any


BOILERPLATE_PHRASES = ("cookie", "subscribe", "newsletter", "sign up")
BOILERPLATE_CHUNK_MAX_WORDS = 120  # drop short chunks containing these phrases


def _word_count(s: str) -> int:
    return len(s.split()) if s else 0


def _normalize_for_dedup(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _split_into_units(text: str) -> list[str]:
    """Pass 1: Split by blank lines, trim, drop empty."""
    if not text or not text.strip():
        return []
    units = re.split(r"\n\s*\n", text)
    return [u.strip() for u in units if u.strip()]


def _split_long_unit(unit: str, max_words: int) -> list[str]:
    """Split a single unit that exceeds max_words into subparts (by sentences)."""
    parts = re.split(r"(?<=[.!?])\s+", unit)
    subparts: list[str] = []
    current: list[str] = []
    current_words = 0
    for part in parts:
        w = _word_count(part)
        if current_words + w > max_words and current:
            subparts.append(" ".join(current))
            current = []
            current_words = 0
        if w > max_words:
            if current:
                subparts.append(" ".join(current))
                current = []
                current_words = 0
            # Split by max_words-sized word groups
            words = part.split()
            for i in range(0, len(words), max_words):
                subparts.append(" ".join(words[i : i + max_words]))
            continue
        current.append(part)
        current_words += w
    if current:
        subparts.append(" ".join(current))
    return subparts


def _pack_into_chunks(
    units: list[str],
    target_words: int,
    max_words: int,
    max_chunks: int,
) -> list[str]:
    """Pass 2: Pack units into chunks, split long units when needed."""
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for unit in units:
        if len(chunks) >= max_chunks:
            break
        w = _word_count(unit)
        if w > max_words:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_words = 0
            for sub in _split_long_unit(unit, max_words):
                if len(chunks) >= max_chunks:
                    break
                chunks.append(sub)
            continue
        if current_words + w > max_words and current:
            chunks.append(" ".join(current))
            current = [unit]
            current_words = w
        else:
            current.append(unit)
            current_words += w
    if current and len(chunks) < max_chunks:
        chunks.append(" ".join(current))
    return chunks


def _is_boilerplate_chunk(chunk: str) -> bool:
    """Drop short chunks that contain common boilerplate phrases."""
    if _word_count(chunk) >= BOILERPLATE_CHUNK_MAX_WORDS:
        return False
    lower = chunk.lower()
    return any(phrase in lower for phrase in BOILERPLATE_PHRASES)


def _deduplicate(chunks: list[str]) -> list[str]:
    """Pass 3: Deduplicate by normalized hash within this source."""
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        norm = _normalize_for_dedup(c)
        h = hashlib.sha256(norm.encode()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(c)
    return out


def chunk_source_text_v1(
    text: str,
    source_url: str,
    source_title: str,
    *,
    target_words: int = 350,
    max_words: int = 500,
    min_words: int = 60,
    max_chunks: int = 20,
) -> list[dict[str, Any]]:
    """
    Split source text into chunks (paragraph-aware), filter junk, dedupe.
    Returns list of dicts with Chunk schema fields: chunk_id, source_url, source_title,
    chunk_index, text, start_char (optional), end_char (optional).
    """
    units = _split_into_units(text)
    if not units:
        return []

    raw_chunks = _pack_into_chunks(units, target_words, max_words, max_chunks)

    # Pass 3: min_words, boilerplate filter
    filtered = [
        c for c in raw_chunks
        if _word_count(c) >= min_words and not _is_boilerplate_chunk(c)
    ]
    filtered = _deduplicate(filtered)

    # Build result dicts with metadata
    result: list[dict[str, Any]] = []
    for i, chunk_text in enumerate(filtered):
        chunk_id = hashlib.sha256(
            f"{source_url}{i}{chunk_text[:50]}".encode()
        ).hexdigest()
        result.append({
            "chunk_id": chunk_id,
            "source_url": source_url,
            "source_title": source_title,
            "chunk_index": i,
            "text": chunk_text,
            "start_char": None,
            "end_char": None,
        })
    return result
