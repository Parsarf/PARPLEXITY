"""Extract main readable text from HTML."""

import re

from bs4 import BeautifulSoup

try:
    from readability import Document
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_main_text(html: str) -> tuple[str, str]:
    """
    Extract main article title and plain text from HTML.
    Returns (title, text). Uses readability-lxml if available; else fallback.
    """
    if not html or not html.strip():
        return ("", "")

    if HAS_READABILITY:
        try:
            doc = Document(html)
            title = (doc.title() or "").strip()
            summary_html = doc.summary() or ""
            if summary_html:
                soup = BeautifulSoup(summary_html, "lxml")
                text = soup.get_text(separator=" ", strip=True)
                text = _normalize_whitespace(text)
                if not title and soup.title:
                    title = (soup.title.get_text(strip=True) or "").strip()
                return (title or "Untitled", text)
        except Exception:
            pass

    # Fallback: strip scripts/styles/nav/footer/header, take body text
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = ""
    if soup.title:
        title = (soup.title.get_text(strip=True) or "").strip()
    body = soup.find("body") or soup
    text = body.get_text(separator=" ", strip=True)
    text = _normalize_whitespace(text)
    if not title:
        title = "Untitled"
    return (title, text)
