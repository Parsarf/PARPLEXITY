"""
Search facade: single entry point for main.py (Phase 7).
Normalizes query, runs DDG with retries/backoff, optional production fallback,
returns results or structured exceptions. No link-dump; zero results = failure.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from app import config
from app.services.search.duckduckgo import _ddg_search
from app.services.search.exceptions import (
    SearchError,
    SearchBlockedError,
    SearchParseError,
    SearchNetworkError,
)
from app.services.search.fallback_providers import (
    BraveSearchProvider,
    SearXNGProvider,
)

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 400
DDG_RETRIES = 3
DDG_BACKOFF_BASE = 1.0
DDG_TIMEOUT = 15.0


def _normalize_query(query: str) -> str:
    """Trim, collapse whitespace, cap length."""
    if not query or not isinstance(query, str):
        return ""
    q = re.sub(r"\s+", " ", query.strip())
    if len(q) > MAX_QUERY_LENGTH:
        q = q[:MAX_QUERY_LENGTH].rstrip()
    return q


def _dedupe_by_url(results: list[dict[str, str]]) -> list[dict[str, str]]:
    """Deduplicate by normalized URL (lower, strip trailing slash)."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in results:
        url = (r.get("url") or "").strip().lower()
        url = url.rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(r)
    return out


def _get_fallback_provider():
    """Build fallback provider from config, or None."""
    provider = config.SEARCH_FALLBACK_PROVIDER
    if provider == "none":
        return None
    if provider == "brave":
        if not config.BRAVE_SEARCH_API_KEY:
            logger.warning("SEARCH_FALLBACK_PROVIDER=brave but BRAVE_SEARCH_API_KEY not set")
            return None
        return BraveSearchProvider(config.BRAVE_SEARCH_API_KEY)
    if provider == "searxng":
        return SearXNGProvider(
            config.SEARXNG_BASE_URL,
            config.SEARXNG_INSTANCES,
            config.DEV_ALLOW_PUBLIC_SEARXNG,
        )
    return None


async def search(
    query: str,
    num_results: int = 8,
    *,
    timeout: float = DDG_TIMEOUT,
) -> list[dict[str, str]]:
    """
    Single entry point for search. Normalizes query, tries DDG with retries/backoff,
    then optional fallback. Returns list of {title, url, snippet}. No garbage results.
    Raises SearchBlockedError, SearchParseError, SearchNetworkError, or SearchError
    with provider, reason, category for clear API error reporting.
    """
    q = _normalize_query(query)
    if not q:
        raise SearchError(
            "Empty query after normalization",
            provider="unknown",
            reason="empty query",
            category="unknown",
        )

    logger.info("Search starting: query=%r, num_results=%d", q[:80], num_results)
    ddg_failure_reason: str | None = None
    ddg_failure_category: str | None = None

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        # ── DDG with retries and backoff ─────────────────────────────────────
        for attempt in range(DDG_RETRIES):
            if attempt > 0:
                delay = DDG_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.info("DDG retry %d/%d after %.1fs backoff", attempt + 1, DDG_RETRIES, delay)
                await asyncio.sleep(delay)
            try:
                results = await _ddg_search(q, num_results, client)
                results = _dedupe_by_url(results)
                if not results:
                    ddg_failure_reason = "DDG returned no parseable results"
                    ddg_failure_category = "parse"
                    break
                logger.info(
                    "Search succeeded via ddg: %d results (attempt %d)",
                    len(results),
                    attempt + 1,
                )
                return results
            except httpx.TimeoutException as e:
                logger.warning("DDG timeout (attempt %d): %s", attempt + 1, e)
                ddg_failure_reason = "timeout"
                ddg_failure_category = "network"
            except (httpx.ConnectError, httpx.TransportError, httpx.ProxyError) as e:
                logger.warning("DDG network error (attempt %d): %s", attempt + 1, e)
                ddg_failure_reason = "connection error"
                ddg_failure_category = "network"
            except SearchBlockedError as e:
                logger.warning("DDG blocked (attempt %d): %s", attempt + 1, e.reason)
                ddg_failure_reason = e.reason
                ddg_failure_category = "blocked"
                break
            except SearchParseError as e:
                logger.warning("DDG parse failed (attempt %d): %s", attempt + 1, e.reason)
                ddg_failure_reason = e.reason
                ddg_failure_category = "parse"
                break

        # All DDG attempts failed; try fallback or raise
        if ddg_failure_reason is None:
            ddg_failure_reason = "timeout or connection error after retries"
            ddg_failure_category = "network"

        fallback = _get_fallback_provider()
        if fallback and not (
            isinstance(fallback, SearXNGProvider) and not fallback.is_configured()
        ):
            logger.info("Attempting fallback provider: %s", config.SEARCH_FALLBACK_PROVIDER)
            try:
                results = await fallback.search(q, num_results, client)
                results = _dedupe_by_url(results)
                logger.info("Search succeeded via fallback: %d results", len(results))
                return results
            except SearchError as e:
                # Combine DDG and fallback failure for clear reporting
                combined = (
                    f"ddg failed ({ddg_failure_reason}) and fallback {e.provider} failed ({e.reason})"
                )
                logger.warning("Search failed: %s", combined)
                raise SearchError(
                    combined,
                    provider=e.provider,
                    reason=combined,
                    category=e.category,
                ) from e
        else:
            # No fallback configured
            if config.SEARCH_FALLBACK_PROVIDER == "brave" and not config.BRAVE_SEARCH_API_KEY:
                detail = f"ddg failed ({ddg_failure_reason}) and fallback not configured (BRAVE_SEARCH_API_KEY missing)"
            elif config.SEARCH_FALLBACK_PROVIDER == "searxng" and not config.SEARXNG_BASE_URL and not config.SEARXNG_INSTANCES and not config.DEV_ALLOW_PUBLIC_SEARXNG:
                detail = f"ddg failed ({ddg_failure_reason}) and fallback not configured (SEARXNG_BASE_URL or SEARXNG_INSTANCES not set)"
            else:
                detail = f"ddg failed ({ddg_failure_reason}) and fallback not configured"

            if ddg_failure_category == "blocked":
                raise SearchBlockedError(
                    detail,
                    provider="ddg",
                    reason=ddg_failure_reason,
                )
            if ddg_failure_category == "parse":
                raise SearchParseError(
                    detail,
                    provider="ddg",
                    reason=ddg_failure_reason,
                )
            if ddg_failure_category == "network":
                raise SearchNetworkError(
                    detail,
                    provider="ddg",
                    reason=ddg_failure_reason,
                )
            raise SearchError(
                detail,
                provider="ddg",
                reason=ddg_failure_reason,
                category=ddg_failure_category or "unknown",
            )
    # Unreachable but satisfy type checker
    raise SearchError("Search failed", provider="ddg", reason="unknown", category="unknown")
