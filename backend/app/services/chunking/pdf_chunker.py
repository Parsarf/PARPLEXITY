"""
Section-aware chunking for PDF documents.
"""

from __future__ import annotations

import hashlib
import re

SKIP_HEADINGS = frozenset({
    "references", "bibliography", "works cited",
    "acknowledgments", "acknowledgements", "appendix",
})
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _word_count(s: str) -> int:
    return len(s.split()) if s else 0


def chunk_pdf_sections(
    pdf_data: dict,
    source_url: str,
    source_title: str,
    max_words_per_chunk: int = 300,
    min_words_per_chunk: int = 30,
    max_chunks: int = 20,
) -> list[dict]:
    """
    Chunk PDF content by section boundaries.

    Args:
        pdf_data: Output dict from extract_pdf().
        source_url: URL the PDF was fetched from (or upload path).
        source_title: Title to use (usually pdf_data["title"]).
        max_words_per_chunk: Split sections longer than this.
        min_words_per_chunk: Drop chunks shorter than this.
        max_chunks: Maximum total chunks to return.

    Returns:
        List of chunk dicts compatible with the Chunk schema:
        {
            "chunk_id": str,
            "source_url": str,
            "source_title": str,
            "chunk_index": int,
            "text": str,
            "start_char": None,
            "end_char": None,
            "section_heading": str,
            "page_number": None,
        }
    """
    section_tuples: list[tuple[str, str]] = []

    if (pdf_data.get("abstract") or "").strip():
        section_tuples.append(("abstract", (pdf_data["abstract"] or "").strip()))

    for sec in pdf_data.get("sections", []):
        heading = (sec.get("heading") or "").strip().lower()
        text = (sec.get("text") or "").strip()
        if heading in SKIP_HEADINGS:
            continue
        if not text:
            continue
        section_tuples.append((heading, text))

    if not section_tuples and (pdf_data.get("full_text") or "").strip():
        section_tuples.append(("full_text", (pdf_data["full_text"] or "").strip()))

    chunks: list[dict] = []
    for heading, text in section_tuples:
        if len(chunks) >= max_chunks:
            break
        wc = _word_count(text)
        if wc <= max_words_per_chunk:
            if wc >= min_words_per_chunk:
                chunks.append({"section_heading": heading, "text": text})
        else:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            current: list[str] = []
            current_words = 0
            for para in paragraphs:
                pw = _word_count(para)
                if pw > max_words_per_chunk:
                    if current and current_words >= min_words_per_chunk:
                        chunks.append({"section_heading": heading, "text": " ".join(current)})
                        if len(chunks) >= max_chunks:
                            break
                    current = []
                    current_words = 0
                    sentences = SENTENCE_SPLIT.split(para)
                    for sent in sentences:
                        sw = _word_count(sent)
                        if sw > max_words_per_chunk:
                            words = sent.split()
                            for i in range(0, len(words), max_words_per_chunk):
                                part = " ".join(words[i : i + max_words_per_chunk])
                                if _word_count(part) >= min_words_per_chunk:
                                    chunks.append({"section_heading": heading, "text": part})
                                    if len(chunks) >= max_chunks:
                                        break
                            continue
                        if current_words + sw > max_words_per_chunk and current:
                            chunks.append({"section_heading": heading, "text": " ".join(current)})
                            if len(chunks) >= max_chunks:
                                break
                            current = []
                            current_words = 0
                        current.append(sent)
                        current_words += sw
                    if current and current_words >= min_words_per_chunk:
                        chunks.append({"section_heading": heading, "text": " ".join(current)})
                        if len(chunks) >= max_chunks:
                            break
                    current = []
                    current_words = 0
                    continue
                if current_words + pw > max_words_per_chunk and current:
                    chunks.append({"section_heading": heading, "text": " ".join(current)})
                    if len(chunks) >= max_chunks:
                        break
                    current = []
                    current_words = 0
                current.append(para)
                current_words += pw
            if current and current_words >= min_words_per_chunk and len(chunks) < max_chunks:
                chunks.append({"section_heading": heading, "text": " ".join(current)})

    chunks = chunks[:max_chunks]

    result: list[dict] = []
    for i, c in enumerate(chunks):
        text = c["text"]
        heading = c["section_heading"]
        chunk_id = hashlib.sha256(
            f"{source_url}:{i}:{text[:50]}".encode()
        ).hexdigest()[:16]
        result.append({
            "chunk_id": chunk_id,
            "source_url": source_url,
            "source_title": source_title,
            "chunk_index": i,
            "text": text,
            "start_char": None,
            "end_char": None,
            "section_heading": heading,
            "page_number": None,
        })
    return result
