"""
Build source_map (S1..SN) and pack top_chunks into a single context string
for the OpenAI prompt, with a max character budget.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import ScoredChunk, SourceRef


def build_source_map(
    top_chunks: list["ScoredChunk"],
) -> tuple[list["SourceRef"], dict[str, str]]:
    """
    Assign stable labels S1..SN by unique source URL (order of first appearance).
    Returns (list of SourceRef, dict mapping chunk_id -> source_id e.g. "S1").
    """
    from app.schemas import SourceRef

    source_refs: list[SourceRef] = []
    url_to_id: dict[str, str] = {}
    chunk_id_to_source_id: dict[str, str] = {}
    n = 0
    for ch in top_chunks:
        url = str(ch.source_url)
        if url not in url_to_id:
            n += 1
            sid = f"S{n}"
            url_to_id[url] = sid
            source_refs.append(
                SourceRef(id=sid, title=ch.source_title, url=ch.source_url)
            )
        chunk_id_to_source_id[ch.chunk_id] = url_to_id[url]
    return source_refs, chunk_id_to_source_id


def pack_context(
    top_chunks: list["ScoredChunk"],
    chunk_id_to_source_id: dict[str, str],
    *,
    max_chars: int = 12000,
) -> str:
    """
    Build context string: [S1] <title> — <url>
    <chunk text>

    [S2] ...
    Truncate from the end to stay within max_chars. Deterministic.
    """
    parts: list[str] = []
    total = 0
    for ch in top_chunks:
        sid = chunk_id_to_source_id.get(ch.chunk_id, "S?")
        block = f"[{sid}] {ch.source_title} — {ch.source_url}\n{ch.text}\n\n"
        if total + len(block) <= max_chars:
            parts.append(block)
            total += len(block)
        else:
            remaining = max_chars - total
            if remaining > 80:
                # Fit a truncated version of this chunk
                header = f"[{sid}] {ch.source_title} — {ch.source_url}\n"
                rest = remaining - len(header) - 2
                if rest > 0:
                    parts.append(header + (ch.text[:rest] + "\n\n"))
            break
    return "".join(parts) if parts else ""
