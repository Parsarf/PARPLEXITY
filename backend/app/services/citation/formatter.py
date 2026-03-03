"""
Citation formatting: APA 7th, MLA 9th, Chicago 17th, and BibTeX.
"""

import re
from datetime import datetime, timezone


def _apa_authors(names: list[str]) -> str:
    """Format authors for APA: 'Last, F. I., Last, F. I., & Last, F. I.'"""
    if not names:
        return ""
    formatted = []
    for name in names:
        parts = name.strip().split()
        if len(parts) >= 2:
            last = parts[-1]
            initials = " ".join(p[0] + "." for p in parts[:-1])
            formatted.append(f"{last}, {initials}")
        elif len(parts) == 1:
            formatted.append(parts[0])
    if len(formatted) > 20:
        return ", ".join(formatted[:19]) + ", ... " + formatted[-1]
    if len(formatted) == 1:
        return formatted[0]
    elif len(formatted) == 2:
        return f"{formatted[0]} & {formatted[1]}"
    else:
        return ", ".join(formatted[:-1]) + ", & " + formatted[-1]


def _mla_authors(names: list[str]) -> str:
    """Format authors for MLA: 'Last, First, et al.' (first author inverted, rest normal)."""
    if not names:
        return ""
    parts = names[0].strip().split()
    if len(parts) >= 2:
        first_author = f"{parts[-1]}, {' '.join(parts[:-1])}"
    else:
        first_author = names[0]
    if len(names) == 1:
        return first_author
    elif len(names) == 2:
        return f"{first_author}, and {names[1]}"
    else:
        return f"{first_author}, et al."


def _chicago_authors(names: list[str]) -> str:
    """Format authors for Chicago: same as MLA first author inversion, then normal order."""
    if not names:
        return ""
    parts = names[0].strip().split()
    if len(parts) >= 2:
        first_author = f"{parts[-1]}, {' '.join(parts[:-1])}"
    else:
        first_author = names[0]
    if len(names) == 1:
        return first_author
    elif len(names) == 2:
        return f"{first_author}, and {names[1]}"
    elif len(names) <= 10:
        middle = ", ".join(names[1:-1])
        return f"{first_author}, {middle}, and {names[-1]}"
    else:
        return f"{first_author}, et al."


def _bibtex_key(authors: list[str], year: int | None, title: str) -> str:
    """Generate a BibTeX citation key: lastnameyearfirstword."""
    last = ""
    if authors:
        parts = authors[0].strip().split()
        last = parts[-1].lower() if parts else "unknown"
    else:
        last = "unknown"
    yr = str(year) if year else "nd"
    skip = {"a", "an", "the", "on", "in", "of", "for", "and", "to"}
    words = re.findall(r"[a-zA-Z]+", title.lower())
    first_word = "untitled"
    for w in words:
        if w not in skip:
            first_word = w
            break
    return f"{last}{yr}{first_word}"


def _escape_bibtex(text: str) -> str:
    """Escape special BibTeX characters."""
    for ch in ("&", "%", "$", "#", "_", "{", "}", "~", "^"):
        text = text.replace(ch, "\\" + ch)
    return text


def _format_apa(title, url, authors, year, journal, volume, issue, doi, publisher, source_type, access_date):
    """Format a citation in APA 7th edition style."""
    parts = []

    author_str = _apa_authors(authors)
    if author_str:
        parts.append(author_str)

        if year:
            parts.append(f"({year}).")
        else:
            parts.append("(n.d.).")

        if source_type in ("peer_reviewed", "preprint") and journal:
            parts.append(f"{title}.")
            journal_part = f"*{journal}*"
            if volume:
                journal_part += f", *{volume}*"
                if issue:
                    journal_part += f"({issue})"
            parts.append(journal_part + ".")
        else:
            parts.append(f"*{title}*.")
    else:
        if source_type in ("peer_reviewed", "preprint") and journal:
            parts.append(f"{title}.")
        else:
            parts.append(f"*{title}*.")

        if year:
            parts.append(f"({year}).")
        else:
            parts.append("(n.d.).")

    if doi:
        parts.append(f"https://doi.org/{doi}")
    else:
        parts.append(f"Retrieved {access_date}, from {url}")

    return " ".join(parts)


def _format_mla(title, url, authors, year, journal, volume, issue, doi, publisher, source_type, access_date):
    """Format a citation in MLA 9th edition style."""
    parts = []

    author_str = _mla_authors(authors)
    if author_str:
        parts.append(author_str + ".")

    if source_type in ("peer_reviewed", "preprint") and journal:
        parts.append(f'"{title}."')
        journal_part = f"*{journal}*"
        if volume:
            journal_part += f", vol. {volume}"
        if issue:
            journal_part += f", no. {issue}"
        if year:
            journal_part += f", {year}"
        parts.append(journal_part + ".")
    else:
        parts.append(f"*{title}*.")
        if publisher:
            parts.append(f"{publisher},")
        if year:
            parts.append(f"{year}.")

    if doi:
        parts.append(f"https://doi.org/{doi}.")
    else:
        parts.append(f"Accessed {access_date}. {url}.")

    return " ".join(parts)


def _format_chicago(title, url, authors, year, journal, volume, issue, doi, publisher, source_type, access_date):
    """Format a citation in Chicago 17th edition (Notes-Bibliography) style."""
    parts = []

    author_str = _chicago_authors(authors)
    if author_str:
        parts.append(author_str + ".")

    if source_type in ("peer_reviewed", "preprint") and journal:
        parts.append(f'"{title}."')
        journal_part = f"*{journal}*"
        if volume:
            journal_part += f" {volume}"
            if issue:
                journal_part += f", no. {issue}"
        if year:
            journal_part += f" ({year})"
        parts.append(journal_part + ".")
    else:
        parts.append(f"*{title}*.")
        if publisher:
            parts.append(f"{publisher}.")
        if year:
            parts.append(f"{year}.")

    if doi:
        parts.append(f"https://doi.org/{doi}.")
    else:
        parts.append(f"Accessed {access_date}. {url}.")

    return " ".join(parts)


def _format_bibtex(title, url, authors, year, journal, volume, issue, doi, publisher, source_type):
    """Format a citation as a BibTeX entry."""
    key = _bibtex_key(authors, year, title)

    if source_type in ("peer_reviewed",) and journal:
        entry_type = "article"
    elif source_type == "book":
        entry_type = "book"
    elif source_type == "preprint":
        entry_type = "unpublished"
    else:
        entry_type = "misc"

    safe_title = _escape_bibtex(title)

    lines = [f"@{entry_type}{{{key},"]
    lines.append(f'  title = {{{safe_title}}},')

    if authors:
        bib_authors = []
        for name in authors:
            parts = name.strip().split()
            if len(parts) >= 2:
                bib_authors.append(f"{parts[-1]}, {' '.join(parts[:-1])}")
            else:
                bib_authors.append(name)
        lines.append(f'  author = {{{" and ".join(bib_authors)}}},')

    if year:
        lines.append(f"  year = {{{year}}},")

    if journal:
        safe_journal = _escape_bibtex(journal)
        lines.append(f"  journal = {{{safe_journal}}},")

    if volume:
        lines.append(f"  volume = {{{volume}}},")

    if issue:
        lines.append(f"  number = {{{issue}}},")

    if publisher:
        safe_publisher = _escape_bibtex(publisher)
        lines.append(f"  publisher = {{{safe_publisher}}},")

    if doi:
        lines.append(f"  doi = {{{doi}}},")

    lines.append(f"  url = {{{url}}},")
    lines.append("}")

    return "\n".join(lines)


def format_citations(
    title: str,
    url: str,
    authors: list[str] | None = None,
    year: int | None = None,
    journal: str | None = None,
    volume: str | None = None,
    issue: str | None = None,
    doi: str | None = None,
    publisher: str | None = None,
    source_type: str = "unknown",
    access_date: str | None = None,
) -> dict:
    """
    Generate formatted citations in multiple styles.

    Args:
        title: Source title (required).
        url: Source URL (required).
        authors: List of author names in "First Last" format.
        year: Publication year.
        journal: Journal/publication name.
        volume: Volume number.
        issue: Issue number.
        doi: Digital Object Identifier.
        publisher: Publisher name.
        source_type: Classification from Phase 9.
        access_date: Date accessed, ISO format. Defaults to today.

    Returns:
        dict with keys:
            - apa: str (APA 7th edition formatted citation)
            - mla: str (MLA 9th edition formatted citation)
            - chicago: str (Chicago 17th edition formatted citation)
            - bibtex: str (BibTeX entry)
            - missing_fields: list[str] (fields that were unavailable)
    """
    authors = authors or []
    access_date = access_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    missing_fields = []

    if not authors:
        missing_fields.append("authors")
    if year is None:
        missing_fields.append("year")
    if source_type in ("peer_reviewed", "preprint") and not journal:
        missing_fields.append("journal")
    if not doi:
        missing_fields.append("doi")

    apa = _format_apa(title, url, authors, year, journal, volume, issue, doi, publisher, source_type, access_date)
    mla = _format_mla(title, url, authors, year, journal, volume, issue, doi, publisher, source_type, access_date)
    chicago = _format_chicago(title, url, authors, year, journal, volume, issue, doi, publisher, source_type, access_date)
    bibtex = _format_bibtex(title, url, authors, year, journal, volume, issue, doi, publisher, source_type)

    return {
        "apa": apa,
        "mla": mla,
        "chicago": chicago,
        "bibtex": bibtex,
        "missing_fields": missing_fields,
    }
