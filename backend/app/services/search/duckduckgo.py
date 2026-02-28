"""DuckDuckGo HTML search. No paid APIs."""

from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class DuckDuckGoSearchError(Exception):
    """Raised when the HTTP request to DuckDuckGo fails."""

    pass


def _extract_url(href: str) -> str | None:
    """Resolve DDG redirect (/l/?uddg=...) to final URL, or return http(s) URLs as-is."""
    href = (href or "").strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg") or qs.get("u2")
        if uddg:
            return unquote(uddg[0])
    return None


# Safe cutoff for URL length (Pydantic HttpUrl max is 2083)
MAX_URL_LENGTH = 2000


def _is_valid_result_url(url: str) -> bool:
    """Skip long URLs and DuckDuckGo tracking/redirect links so SearchResult validation never fails."""
    if not url or not url.startswith("http"):
        return False
    if len(url) > MAX_URL_LENGTH:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        # Skip DDG redirect/tracking pages
        if "duckduckgo.com" in host:
            return False
    except Exception:
        return False
    return True


async def duckduckgo_search(
    query: str, num_results: int = 8
) -> list[dict[str, str]]:
    """
    Search DuckDuckGo HTML version and return a list of result dicts
    with keys: title, url, snippet (snippet may be empty string if missing).
    """
    encoded = quote_plus(query)
    url = f"https://duckduckgo.com/html/?q={encoded}"

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=15.0,
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise DuckDuckGoSearchError(f"DuckDuckGo search request failed: {e}") from e

    soup = BeautifulSoup(response.text, "lxml")
    results: list[dict[str, str]] = []
    # Result containers: .result (DDG HTML uses this class)
    for result_el in soup.select(".result"):
        if len(results) >= num_results:
            break
        link_el = result_el.select_one("a.result__a")
        if not link_el:
            continue
        raw_url = link_el.get("href") or ""
        # DDG often uses redirect links; resolve to final http(s) URL
        url = _extract_url(raw_url)
        if not url or not url.startswith("http"):
            # Fallback: try .result__url for direct link
            url_el = result_el.select_one("a.result__url")
            if url_el and url_el.get("href"):
                url = _extract_url(url_el["href"]) or url_el["href"]
            if not url or not url.startswith("http"):
                continue
        # Skip long or DDG tracking URLs so Pydantic SearchResult never gets url_too_long
        if not _is_valid_result_url(url):
            continue
        title = (link_el.get_text(strip=True) or "").strip()
        snippet_el = result_el.select_one(".result__snippet")
        snippet = (snippet_el.get_text(strip=True) if snippet_el else "") or ""
        results.append({"title": title, "url": url, "snippet": snippet or ""})

    return results
