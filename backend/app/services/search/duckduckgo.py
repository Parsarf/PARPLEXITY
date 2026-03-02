"""
Robust search with DuckDuckGo HTML as primary + SearXNG as fallback.
Falls back gracefully and detects bot blocks explicitly.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.search.exceptions import SearchBlockedError, SearchParseError

logger = logging.getLogger(__name__)

MAX_URL_LENGTH = 2000

# ── Rotate through several real browser UAs ───────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

_ua_index = 0


def _next_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


# ── URL helpers ───────────────────────────────────────────────────────────────

def _extract_url(href: str) -> str | None:
    href = (href or "").strip()
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("/"):
        qs = parse_qs(urlparse(href).query)
        for key in ("uddg", "u2", "u"):
            if key in qs:
                return unquote(qs[key][0])
    return None


def _is_valid_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    if len(url) > MAX_URL_LENGTH:
        return False
    host = urlparse(url).netloc.lower()
    return "duckduckgo.com" not in host


# ── Bot / block detection ─────────────────────────────────────────────────────

_BLOCK_SIGNALS = [
    "duckduckgo.com/sorry",
    "duckduckgo.com/abuse",
    "unusual traffic",
    "captcha",
    "verify you are human",
    "access denied",
    "checking your browser",
]


def _detect_block(html: str, status: int) -> str | None:
    """Return a human-readable reason if DDG blocked us, else None."""
    if status in (403, 429, 503):
        return f"HTTP {status}"
    lower = html.lower()
    for signal in _BLOCK_SIGNALS:
        if signal in lower:
            return f"bot-detection signal: '{signal}'"
    # Sanity: if the page is tiny it's probably an error page
    if len(html) < 500:
        return f"suspiciously short response ({len(html)} bytes)"
    return None


# ── DDG HTML selector sets (try each in order) ───────────────────────────────
# DDG has changed its HTML a few times. We try multiple selector combos.

_SELECTOR_STRATEGIES = [
    # Strategy A – current DDG HTML (2024–2025)
    {
        "container": ".results_links_deep, .result",
        "link":      "h2.result__title a, a.result__a",
        "snippet":   ".result__snippet",
    },
    # Strategy B – older DDG HTML
    {
        "container": ".web-result",
        "link":      ".result__a",
        "snippet":   ".result__snippet",
    },
    # Strategy C – minimal fallback: result-like containers with link + snippet
    {
        "container": "div[class*='result']",
        "link":      "a[href]",
        "snippet":   "p, span[class*='snippet'], span[class*='desc']",
    },
]


def _parse_ddg_html(html: str, num_results: int) -> list[dict[str, str]]:
    """Parse DDG HTML with multiple selector strategies. No link-dump fallback."""
    soup = BeautifulSoup(html, "lxml")

    for strategy in _SELECTOR_STRATEGIES:
        containers = soup.select(strategy["container"])
        if not containers:
            continue

        results: list[dict[str, str]] = []
        for el in containers:
            if len(results) >= num_results:
                break
            link_el = el.select_one(strategy["link"])
            if not link_el:
                continue
            url = _extract_url(link_el.get("href", ""))
            if not url or not _is_valid_url(url):
                continue
            title = link_el.get_text(strip=True)
            snippet_el = el.select_one(strategy["snippet"])
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            results.append({"title": title, "url": url, "snippet": snippet})

        if results:
            logger.debug("DDG parse succeeded with strategy: %s", strategy["container"])
            return results

    # No strategy produced valid results — treat as parse failure, do not return random URLs
    raise SearchParseError(
        "DDG parse failed (no result containers matched)",
        provider="ddg",
        reason="DDG parse failed (no result containers matched)",
    )


# ── DDG search ────────────────────────────────────────────────────────────────


async def _ddg_search(
    query: str,
    num_results: int,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}&kl=us-en"
    headers = {
        "User-Agent": _next_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://duckduckgo.com/",
        "DNT": "1",
    }
    # Let network errors (timeout, connect) propagate so facade can raise SearchNetworkError
    r = await client.get(url, headers=headers)
    block_reason = _detect_block(r.text, r.status_code)
    if block_reason:
        raise SearchBlockedError(
            f"DDG blocked ({block_reason})",
            provider="ddg",
            reason=block_reason,
        )

    results = _parse_ddg_html(r.text, num_results)
    return results


# Public API is search_facade.search(); this module exposes only _ddg_search for the facade.