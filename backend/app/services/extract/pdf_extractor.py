"""
PDF text and structure extraction using PyMuPDF.
"""

from __future__ import annotations

import re

import fitz  # PyMuPDF

MAX_PAGES_TO_PROCESS = 80
MIN_TEXT_FOR_VALID_PDF = 50


KNOWN_HEADINGS = [
    "abstract", "introduction", "background", "related work",
    "methods", "methodology", "materials and methods", "experimental",
    "results", "findings", "analysis",
    "discussion", "conclusion", "conclusions", "summary",
    "limitations", "future work",
    "references", "bibliography", "works cited",
    "acknowledgments", "acknowledgements", "appendix",
]

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
AUTHOR_LINE_PATTERN = re.compile(
    r"^[A-Z][a-z]+ [A-Z][a-z]+(?:\s*[,;&]\s*[A-Z][a-z]+ [A-Z][a-z]+)*",
    re.MULTILINE,
)


def _normalize_heading(line: str) -> str:
    """Normalize heading to lowercase, strip numbering like '1. Introduction'."""
    line = line.strip()
    m = re.match(r"^[\dA-Za-z]+[.)]\s*(.+)", line)
    if m:
        line = m.group(1)
    return line.lower().strip()


def _is_section_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    if lower in KNOWN_HEADINGS:
        return True
    if re.match(r"^[\dA-Za-z]+[.)]\s+.+", stripped):
        normalized = _normalize_heading(stripped)
        if normalized in KNOWN_HEADINGS or any(normalized.startswith(h) for h in KNOWN_HEADINGS if len(h) > 4):
            return True
        if len(normalized) >= 4 and len(normalized) <= 60:
            return True
    if len(stripped) >= 4 and len(stripped) <= 60 and stripped.isupper() and any(c.isalpha() for c in stripped):
        return True
    return False


def extract_pdf(pdf_bytes: bytes) -> dict:
    """
    Extract structured content from PDF bytes.

    Args:
        pdf_bytes: Raw bytes of a PDF file.

    Returns:
        dict with keys:
            - title: str (best guess at paper title, or "Untitled")
            - authors: list[str] (list of author names, may be empty)
            - abstract: str (abstract text, or "")
            - sections: list[dict] (each dict has "heading": str, "text": str)
            - references: str (raw references section text, or "")
            - doi: str or None
            - full_text: str (all text concatenated, for fallback use)
            - page_count: int
    """
    default_empty = {
        "title": "Untitled (PDF parse error)",
        "authors": [],
        "abstract": "",
        "sections": [],
        "references": "",
        "doi": None,
        "full_text": "",
        "page_count": 0,
    }

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return default_empty

    try:
        total_pages = len(doc)
        page_count = min(total_pages, MAX_PAGES_TO_PROCESS)

        full_text_parts: list[str] = []
        for i in range(min(len(doc), MAX_PAGES_TO_PROCESS)):
            page = doc[i]
            full_text_parts.append(page.get_text("text"))
        full_text = "\n".join(full_text_parts).strip()

        if len(full_text.strip()) < MIN_TEXT_FOR_VALID_PDF:
            doc.close()
            return {
                **default_empty,
                "title": "Untitled (scanned/image-only PDF)",
                "full_text": full_text,
                "page_count": total_pages,
            }

        title = ""
        if doc.metadata.get("title", "").strip() and len(doc.metadata.get("title", "").strip()) > 3:
            title = doc.metadata.get("title", "").strip()
        if not title and full_text:
            try:
                first_page = doc[0]
                blocks = first_page.get_text("dict").get("blocks", [])
                max_font = 0
                best_text = ""
                page_height = first_page.rect.height
                for block in blocks:
                    if "lines" not in block:
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            y = span.get("origin", (0, 0))[1]
                            if y > page_height * 0.4:
                                continue
                            sz = span.get("size", 0)
                            if sz > max_font:
                                max_font = sz
                                best_text = (span.get("text", "") or "").strip()
                if best_text:
                    title = best_text[:300].strip()
            except Exception:
                pass
        if not title:
            title = "Untitled"

        doi = None
        search_zone = (full_text[:3000] + " " + str(doc.metadata)).strip()
        m = DOI_PATTERN.search(search_zone)
        if m:
            doi = m.group(0)

        lines = full_text.split("\n")
        sections: list[dict[str, str]] = []
        i = 0
        preamble: list[str] = []
        while i < len(lines):
            line = lines[i]
            if _is_section_heading(line):
                preamble_text = "\n".join(preamble).strip()
                if len(preamble_text) > 200:
                    sections.append({"heading": "preamble", "text": preamble_text})
                preamble = []
                heading_normalized = _normalize_heading(line)
                if heading_normalized and heading_normalized not in KNOWN_HEADINGS:
                    for h in KNOWN_HEADINGS:
                        if heading_normalized.startswith(h) or h in heading_normalized:
                            heading_normalized = h
                            break
                section_lines: list[str] = []
                i += 1
                while i < len(lines) and not _is_section_heading(lines[i]):
                    section_lines.append(lines[i])
                    i += 1
                section_text = "\n".join(section_lines).strip()
                sections.append({"heading": heading_normalized or "section", "text": section_text})
                continue
            preamble.append(line)
            i += 1
        if preamble:
            preamble_text = "\n".join(preamble).strip()
            if len(preamble_text) > 200:
                sections.append({"heading": "preamble", "text": preamble_text})

        abstract = ""
        for s in sections:
            if s["heading"] == "abstract":
                abstract = s["text"]
                break
        if not abstract and full_text:
            first_part = full_text[:3000]
            abstract_match = re.search(r"\bAbstract\b\s*[-–—:]?\s*(.+?)(?=\n\n[A-Z]|\n\d+\.\s|\nIntroduction\b)", first_part, re.DOTALL | re.IGNORECASE)
            if abstract_match and len(abstract_match.group(1).strip()) > 50:
                abstract = abstract_match.group(1).strip()

        references = ""
        for s in sections:
            if s["heading"] in ("references", "bibliography", "works cited"):
                references = s["text"]
                break

        authors: list[str] = []
        author_zone = full_text[:2000]
        for line in author_zone.split("\n"):
            line = re.sub(r"[\d\*†‡§¶\s]+$", "", line.strip())
            if AUTHOR_LINE_PATTERN.match(line):
                names = re.split(r"\s*[,;&]\s*|\s+and\s+", line, flags=re.IGNORECASE)
                for n in names:
                    n = re.sub(r"^[\d\*†‡§¶\.\s]+|[\d\*†‡§¶\.\s]+$", "", n).strip()
                    if len(n) > 3 and " " in n:
                        authors.append(n)
                if authors:
                    break

        doc.close()

        return {
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "sections": sections,
            "references": references,
            "doi": doi,
            "full_text": full_text,
            "page_count": total_pages,
        }
    except Exception:
        doc.close()
        return {**default_empty, "title": "Untitled (PDF parse error)"}
