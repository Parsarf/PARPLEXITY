"""
Quote verification: checks that extracted quotes exist in source text.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def _normalize_text(text: str) -> str:
    """Normalize text for fuzzy comparison."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _best_fuzzy_match(quote: str, source: str) -> float:
    """
    Find the best fuzzy match score for quote within source.
    Uses a sliding window approach with SequenceMatcher.
    Returns float between 0.0 and 1.0.
    """
    if not quote or not source:
        return 0.0

    quote_words = quote.split()
    source_words = source.split()
    quote_len = len(quote_words)

    if quote_len == 0:
        return 0.0
    if len(source_words) == 0:
        return 0.0

    best_score = 0.0
    min_window = max(1, int(quote_len * 0.8))
    max_window = min(len(source_words), int(quote_len * 1.2))

    for window_size in range(min_window, max_window + 1):
        for i in range(len(source_words) - window_size + 1):
            window = " ".join(source_words[i : i + window_size])
            score = SequenceMatcher(None, quote, window).ratio()
            if score > best_score:
                best_score = score
            if best_score >= 0.95:
                return best_score

    return best_score


def verify_quotes(
    evidence_blocks: list[dict],
    source_text_lookup: dict[str, str],
) -> list[dict]:
    """
    Verify that each quote in the evidence blocks actually exists in the cited source.
    Returns list of blocks with added quote_verified, quote_match_score, quote_match_type, page_number.
    """
    result = []
    for block in evidence_blocks:
        block = dict(block)
        if block.get("quote") is None:
            block["quote_verified"] = False
            block["quote_match_score"] = 0.0
            block["quote_match_type"] = "no_quote"
            block["page_number"] = None
            result.append(block)
            continue

        source_id = block.get("source_id", "")
        if source_id not in source_text_lookup:
            block["quote_verified"] = False
            block["quote_match_score"] = 0.0
            block["quote_match_type"] = "not_found"
            block["page_number"] = None
            result.append(block)
            continue

        source_text = source_text_lookup[source_id]
        quote = block["quote"]
        normalized_quote = _normalize_text(quote)
        normalized_source = _normalize_text(source_text)

        if normalized_quote in normalized_source:
            block["quote_verified"] = True
            block["quote_match_score"] = 1.0
            block["quote_match_type"] = "exact"
        else:
            match_score = _best_fuzzy_match(normalized_quote, normalized_source)
            if match_score >= 0.85:
                block["quote_verified"] = True
                block["quote_match_score"] = round(match_score, 4)
                block["quote_match_type"] = "fuzzy"
            else:
                block["quote_verified"] = False
                block["quote_match_score"] = round(match_score, 4)
                block["quote_match_type"] = "not_found"
        block["page_number"] = None
        result.append(block)

    return result


def assign_page_numbers(
    evidence_blocks: list[dict],
    chunks: list,
    chunk_id_to_sid: dict[str, str],
) -> None:
    """
    In-place: set page_number on evidence blocks by finding which chunk contains the quote.
    """
    source_chunks: dict[str, list[tuple[str, int | None]]] = {}
    for chunk in chunks:
        chunk_dict = chunk if isinstance(chunk, dict) else chunk.__dict__
        cid = chunk_dict.get("chunk_id", "")
        sid = chunk_id_to_sid.get(cid)
        if not sid:
            continue
        text = chunk_dict.get("text", "")
        page = chunk_dict.get("page_number")
        if sid not in source_chunks:
            source_chunks[sid] = []
        source_chunks[sid].append((text, page))

    for block in evidence_blocks:
        if block.get("page_number") is not None:
            continue
        if block.get("quote") is None:
            block["page_number"] = None
            continue

        sid = block.get("source_id", "")
        if sid not in source_chunks:
            block["page_number"] = None
            continue

        normalized_quote = _normalize_text(block["quote"])
        best_page = None
        best_score = 0.0

        for chunk_text, page in source_chunks[sid]:
            normalized_chunk = _normalize_text(chunk_text)
            if normalized_quote in normalized_chunk:
                best_page = page
                break
            score = SequenceMatcher(None, normalized_quote, normalized_chunk).ratio()
            if score > best_score:
                best_score = score
                best_page = page

        block["page_number"] = best_page
