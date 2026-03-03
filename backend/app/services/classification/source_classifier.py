"""
Multi-signal source type classification.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

SOURCE_TYPES = [
    "peer_reviewed",
    "preprint",
    "gov",
    "edu",
    "institutional",
    "encyclopedia",
    "news",
    "blog",
    "unknown",
]

PREPRINT_DOMAINS = [
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "ssrn.com",
    "preprints.org",
    "chemrxiv.org",
    "eartharxiv.org",
    "psyarxiv.com",
    "osf.io",
    "engrxiv.org",
    "techrxiv.org",
]

GOV_TLDS = (".gov", ".mil")
GOV_DOMAINS = [
    "who.int",
    "europa.eu",
    "oecd.org",
    "un.org",
    "worldbank.org",
    "imf.org",
]

EDU_TLDS = [".edu", ".ac.uk", ".ac.jp", ".edu.au", ".edu.cn", ".ac.in"]
EDU_PERSONAL_PATH_SIGNALS = ["/~", "/people/", "/students/", "/blog/", "/personal/"]

INSTITUTIONAL_DOMAINS = [
    "nature.com", "science.org", "sciencedirect.com",
    "springer.com", "springerlink.com", "wiley.com",
    "tandfonline.com", "sagepub.com", "ieee.org",
    "acm.org", "plos.org", "pnas.org",
    "bmj.com", "thelancet.com", "nejm.org",
    "cell.com", "oup.com", "cambridge.org",
    "frontiersin.org", "mdpi.com", "hindawi.com",
    "jstor.org", "pubmed.ncbi.nlm.nih.gov",
    "scholar.google.com",
]

ENCYCLOPEDIA_DOMAINS = [
    "wikipedia.org", "britannica.com",
    "plato.stanford.edu",
    "iep.utm.edu",
    "scholarpedia.org",
]

NEWS_DOMAINS = [
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
    "nytimes.com", "washingtonpost.com", "theguardian.com",
    "wsj.com", "ft.com", "economist.com",
    "bloomberg.com", "cnbc.com", "cnn.com",
    "npr.org", "pbs.org", "aljazeera.com",
    "politico.com", "thehill.com", "axios.com",
    "arstechnica.com", "techcrunch.com", "wired.com",
    "theverge.com", "scientificamerican.com",
    "newscientist.com", "statnews.com",
]

BLOG_DOMAINS = [
    "medium.com", "substack.com", "wordpress.com",
    "blogspot.com", "blogger.com", "tumblr.com",
    "dev.to", "hashnode.com", "ghost.io",
    "quora.com", "reddit.com",
]

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
ACADEMIC_TERMS = [
    "abstract", "introduction", "methodology", "methods", "results",
    "discussion", "conclusion", "references", "et al.", "doi:",
    "journal", "vol.", "pp.",
]


def _domain_matches(hostname: str, domain_list: list[str]) -> str | None:
    """
    Check if hostname matches any domain in the list.
    Handles subdomains: "www.nature.com" matches "nature.com".
    Returns the matched domain string, or None.
    """
    hostname = hostname.lower().lstrip("www.")
    for domain in domain_list:
        if hostname == domain or hostname.endswith("." + domain):
            return domain
    return None


def _content_heuristics(
    text: str,
    title: str,
    is_pdf: bool,
    pdf_metadata: dict | None,
) -> tuple[str, str, list[str]]:
    """Content-based fallback classification. Always returns something."""
    text_slice = (text or "")[:5000].lower()
    title_slice = (title or "").lower()

    # 1. DOI in text
    if DOI_PATTERN.search((text or "")[:3000]):
        return ("peer_reviewed", "low", ["DOI pattern found in content"])

    # 2. PDF with references section
    if pdf_metadata and isinstance(pdf_metadata.get("sections_found"), list):
        sections_found = pdf_metadata["sections_found"]
        if "references" in sections_found and len(sections_found) >= 3:
            return ("peer_reviewed", "low", ["PDF has structured sections including references"])

    # 3. Academic structure markers
    count = sum(1 for term in ACADEMIC_TERMS if term in text_slice)
    if count >= 3:
        return ("peer_reviewed", "low", ["Content contains academic structural markers"])

    # 4. News signals
    if any(
        x in title_slice or x in text_slice
        for x in ("(ap)", "(reuters)", "staff reporter", "breaking:", "updated ")
    ):
        return ("news", "low", ["Content contains news markers"])

    # 5. Blog signals
    if any(
        x in title_slice or x in text_slice
        for x in (
            "my experience",
            "i think",
            "in my opinion",
            "personal blog",
            "subscribe to my",
            "follow me",
        )
    ):
        return ("blog", "low", ["Content contains personal/blog markers"])

    return ("unknown", "low", ["No classification signals matched"])


def classify_source(
    url: str,
    text: str,
    title: str,
    is_pdf: bool = False,
    pdf_metadata: dict | None = None,
) -> dict:
    """
    Classify a source by type using multiple signals.

    Args:
        url: The source URL.
        text: Extracted text content (first ~2500 chars typically).
        title: Source title.
        is_pdf: Whether this source is a PDF.
        pdf_metadata: Phase 8 metadata dict (may contain "source_type", "doi", "sections_found", etc.)

    Returns:
        dict with keys:
            - source_type: str (one of SOURCE_TYPES)
            - confidence: str ("high" | "medium" | "low")
            - signals: list[str] (human-readable reasons for classification)
    """
    url_str = str(url).strip()
    try:
        parsed = urlparse(url_str)
        hostname = (parsed.netloc or "").lower().strip()
        path = (parsed.path or "").lower()
    except Exception:
        hostname = ""
        path = ""

    # Signal 1 — Crossref source_type
    if pdf_metadata is not None:
        st = pdf_metadata.get("source_type")
        if st == "peer_reviewed":
            return {
                "source_type": "peer_reviewed",
                "confidence": "high",
                "signals": ["Crossref confirmed: journal-article with DOI"],
            }
        if st == "preprint":
            return {
                "source_type": "preprint",
                "confidence": "high",
                "signals": ["Crossref confirmed: preprint/posted-content"],
            }
        if st == "book":
            return {
                "source_type": "institutional",
                "confidence": "medium",
                "signals": ["Crossref confirmed: book type"],
            }

    # Signal 2 — Preprint domains
    if hostname:
        match = _domain_matches(hostname, PREPRINT_DOMAINS)
        if match:
            return {
                "source_type": "preprint",
                "confidence": "high",
                "signals": [f"Domain is a known preprint server: {match}"],
            }

    # Signal 3 — Government
    if hostname:
        for tld in GOV_TLDS:
            if hostname.endswith(tld):
                return {
                    "source_type": "gov",
                    "confidence": "high",
                    "signals": [f"Government TLD: {hostname}"],
                }
        match = _domain_matches(hostname, GOV_DOMAINS)
        if match:
            return {
                "source_type": "gov",
                "confidence": "high",
                "signals": [f"Known government/intergovernmental org: {match}"],
            }

    # Signal 4 — Educational (with personal/student check)
    if hostname:
        for tld in EDU_TLDS:
            if hostname.endswith(tld):
                if any(sig in path for sig in EDU_PERSONAL_PATH_SIGNALS):
                    return {
                        "source_type": "blog",
                        "confidence": "medium",
                        "signals": ["edu domain but personal/student page"],
                    }
                return {
                    "source_type": "edu",
                    "confidence": "high",
                    "signals": [f"Academic institution TLD: {hostname}"],
                }

    # Signal 5 — Institutional / publisher
    if hostname:
        match = _domain_matches(hostname, INSTITUTIONAL_DOMAINS)
        if match:
            has_doi = False
            if pdf_metadata and pdf_metadata.get("doi"):
                has_doi = True
            if not has_doi and url_str:
                has_doi = bool(DOI_PATTERN.search(url_str))
            if not has_doi and text:
                has_doi = bool(DOI_PATTERN.search((text or "")[:3000]))
            if has_doi:
                return {
                    "source_type": "peer_reviewed",
                    "confidence": "high",
                    "signals": [f"Published on known academic publisher: {match}", "DOI found"],
                }
            return {
                "source_type": "peer_reviewed",
                "confidence": "medium",
                "signals": [f"Published on known academic publisher: {match}", "No DOI confirmed"],
            }

    # Signal 6 — Encyclopedia
    if hostname:
        match = _domain_matches(hostname, ENCYCLOPEDIA_DOMAINS)
        if match:
            return {
                "source_type": "encyclopedia",
                "confidence": "high",
                "signals": [f"Known encyclopedia: {match}"],
            }

    # Signal 7 — News
    if hostname:
        match = _domain_matches(hostname, NEWS_DOMAINS)
        if match:
            return {
                "source_type": "news",
                "confidence": "high",
                "signals": [f"Known news outlet: {match}"],
            }

    # Signal 8 — Blog platforms
    if hostname:
        match = _domain_matches(hostname, BLOG_DOMAINS)
        if match:
            return {
                "source_type": "blog",
                "confidence": "high",
                "signals": [f"Known blog/opinion platform: {match}"],
            }

    # Signal 9 — Content heuristics
    st, conf, sigs = _content_heuristics(text, title, is_pdf, pdf_metadata)
    return {"source_type": st, "confidence": conf, "signals": sigs}
