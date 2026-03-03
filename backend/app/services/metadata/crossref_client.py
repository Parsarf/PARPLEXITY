"""
Crossref API client for DOI metadata enrichment.
"""

from __future__ import annotations

import httpx


async def fetch_crossref_metadata(doi: str, timeout: float = 5.0) -> dict | None:
    """
    Query Crossref for metadata about a DOI.

    Args:
        doi: A DOI string like "10.1234/example.5678"
        timeout: HTTP timeout in seconds.

    Returns:
        dict with keys:
            - title: str
            - authors: list[str] (formatted as "First Last")
            - year: int or None
            - journal: str or None
            - volume: str or None
            - issue: str or None
            - doi: str
            - publisher: str or None
            - source_type: str ("peer_reviewed" | "preprint" | "book" | "other")
        or None if the request fails or DOI is not found.
    """
    if not doi or not doi.strip():
        return None
    doi = doi.strip()
    url = f"https://api.crossref.org/works/{doi}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "ResearchAssistant/1.0 (mailto:your-project@example.com)",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:
        return None

    try:
        msg = data.get("message", {})
        title_list = msg.get("title", [""])
        title = title_list[0] if title_list else ""

        authors: list[str] = []
        for a in msg.get("author", []):
            given = a.get("given", "") or ""
            family = a.get("family", "") or ""
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        year = None
        for key in ("published-print", "published-online", "created"):
            obj = msg.get(key, {})
            parts = obj.get("date-parts", [[None]])
            if parts and parts[0]:
                year = parts[0][0]
                if year is not None:
                    try:
                        year = int(year)
                    except (TypeError, ValueError):
                        year = None
                    break

        container = msg.get("container-title", [""])
        journal = container[0] if container else None
        if journal == "":
            journal = None

        volume = msg.get("volume")
        if volume is not None:
            volume = str(volume)
        issue = msg.get("issue")
        if issue is not None:
            issue = str(issue)
        publisher = msg.get("publisher") or None

        raw_type = (msg.get("type") or "").lower()
        if raw_type == "journal-article":
            source_type = "peer_reviewed"
        elif raw_type == "posted-content":
            source_type = "preprint"
        elif "book" in raw_type:
            source_type = "book"
        else:
            source_type = "other"

        return {
            "title": title,
            "authors": authors,
            "year": year,
            "journal": journal,
            "volume": volume,
            "issue": issue,
            "doi": doi,
            "publisher": publisher,
            "source_type": source_type,
        }
    except Exception:
        return None
