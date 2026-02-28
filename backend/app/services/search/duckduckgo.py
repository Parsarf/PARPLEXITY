"""
Robust search with DuckDuckGo HTML as primary + SearXNG as fallback.
Falls back gracefully and detects bot blocks explicitly.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

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
    # Strategy C – ultra-minimal fallback: grab any <a> with an external href
    # inside an element that looks like a search result block
    {
        "container": "div[class*='result']",
        "link":      "a[href]",
        "snippet":   "p, span[class*='snippet'], span[class*='desc']",
    },
]


def _parse_ddg_html(html: str, num_results: int) -> list[dict[str, str]]:
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

    # Last resort: dump all external links from the page
    logger.warning("All DDG selector strategies failed, falling back to link dump")
    results = []
    for a in soup.find_all("a", href=True):
        if len(results) >= num_results:
            break
        url = _extract_url(a["href"])
        if url and _is_valid_url(url):
            results.append({
                "title": a.get_text(strip=True) or url,
                "url": url,
                "snippet": "",
            })
    return results


# ── DDG search ────────────────────────────────────────────────────────────────

class SearchBlockedError(Exception):
    """DDG (or another backend) actively blocked the request."""


class SearchError(Exception):
    """Generic search failure."""


async def _ddg_search(
    query: str,
    num_results: int,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}&kl=us-en"
    headers = {
        "User-Agent": _next_ua(),
        # DDG respects these and is less likely to serve a stripped page
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://duckduckgo.com/",
        "DNT": "1",
    }
    try:
        r = await client.get(url, headers=headers)
    except (httpx.ProxyError, httpx.ConnectError, httpx.TransportError) as e:
        raise SearchBlockedError(f"DDG network-level block: {e}") from e

    block_reason = _detect_block(r.text, r.status_code)
    if block_reason:
        raise SearchBlockedError(f"DDG blocked ({block_reason})")

    results = _parse_ddg_html(r.text, num_results)
    if not results:
        raise SearchError("DDG returned no parseable results")
    return results


# ── SearXNG fallback (free, self-hosted instances — public list) ──────────────
# These are community-run, uptime varies. We try them in parallel and take
# the first that responds. You can add your own self-hosted instance first.

SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://search.mdosch.de",
    "https://searxng.world",
    "https://searx.tiekoetter.com",
]


async def _searxng_search(
    query: str,
    num_results: int,
    client: httpx.AsyncClient,
    instance: str,
) -> list[dict[str, str]]:
    url = f"{instance}/search"
    params = {"q": query, "format": "json", "engines": "google,bing,duckduckgo"}
    headers = {"User-Agent": _next_ua()}
    r = await client.get(url, params=params, headers=headers, timeout=10.0)
    r.raise_for_status()
    data = r.json()
    results = []
    for item in data.get("results", [])[:num_results]:
        url_ = item.get("url", "")
        if _is_valid_url(url_):
            results.append({
                "title":   item.get("title", ""),
                "url":     url_,
                "snippet": item.get("content", ""),
            })
    return results


async def _searxng_search_any(
    query: str,
    num_results: int,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    """Try all SearXNG instances concurrently, return first success."""
    tasks = {
        asyncio.create_task(
            _searxng_search(query, num_results, client, inst)
        ): inst
        for inst in SEARXNG_INSTANCES
    }
    pending = set(tasks)
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            try:
                result = t.result()
                if result:
                    # Cancel remaining
                    for p in pending:
                        p.cancel()
                    return result
            except Exception as e:
                logger.debug("SearXNG instance failed: %s — %s", tasks[t], e)
    raise SearchError("All SearXNG instances failed")


# ── Public API ────────────────────────────────────────────────────────────────

async def search(
    query: str,
    num_results: int = 8,
    *,
    timeout: float = 15.0,
    use_fallback: bool = True,
) -> list[dict[str, str]]:
    """
    Search the web. Returns list of {"title", "url", "snippet"} dicts.

    Strategy:
      1. Try DuckDuckGo HTML scraping
      2. On block / parse failure → try SearXNG JSON API (multiple instances)

    Raises SearchError only if ALL backends fail.
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        # ── Primary: DDG ──────────────────────────────────────────────────────
        try:
            results = await _ddg_search(query, num_results, client)
            logger.info("DDG search succeeded: %d results", len(results))
            return results
        except SearchBlockedError as e:
            logger.warning("DDG blocked, trying fallback. Reason: %s", e)
        except SearchError as e:
            logger.warning("DDG parse failed, trying fallback. Reason: %s", e)

        # ── Fallback: SearXNG ─────────────────────────────────────────────────
        if not use_fallback:
            raise SearchError("DDG failed and fallback disabled")

        try:
            results = await _searxng_search_any(query, num_results, client)
            logger.info("SearXNG fallback succeeded: %d results", len(results))
            return results
        except SearchError:
            raise SearchError(
                f"All search backends failed for query: {query!r}"
            )


# ── Convenience sync wrapper ──────────────────────────────────────────────────

def search_sync(query: str, num_results: int = 8) -> list[dict[str, str]]:
    return asyncio.run(search(query, num_results))


# ── Quick smoke test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.DEBUG)
    results = search_sync("python asyncio tutorial", num_results=5)
    print(json.dumps(results, indent=2))