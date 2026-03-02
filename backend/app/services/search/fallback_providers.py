"""
Production fallback search providers (Phase 7).
Brave Search API and self-hosted SearXNG. No hardcoded public SearXNG list in production.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx

from .duckduckgo import _is_valid_url
from .exceptions import SearchError, SearchParseError, SearchNetworkError

logger = logging.getLogger(__name__)

# Only used when DEV_ALLOW_PUBLIC_SEARXNG=true and no SEARXNG_BASE_URL/SEARXNG_INSTANCES
DEV_PUBLIC_SEARXNG_LIST = [
    "https://searx.be",
    "https://search.mdosch.de",
]


class FallbackSearchProvider(Protocol):
    """Interface for fallback search providers."""

    async def search(
        self,
        query: str,
        num_results: int,
        client: httpx.AsyncClient,
    ) -> list[dict[str, str]]:
        """Return list of {title, url, snippet}. Raises SearchError on failure."""
        ...


class BraveSearchProvider:
    """Fallback using Brave Search API (requires BRAVE_SEARCH_API_KEY)."""

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY is required for brave fallback")

    async def search(
        self,
        query: str,
        num_results: int,
        client: httpx.AsyncClient,
    ) -> list[dict[str, str]]:
        url = "https://api.search.brave.com/res/v1/web/search"
        params = {"q": query, "count": min(num_results, 20)}
        headers = {"X-Subscription-Token": self.api_key}
        try:
            r = await client.get(url, params=params, headers=headers, timeout=15.0)
            r.raise_for_status()
        except httpx.TimeoutException as e:
            logger.warning("Brave search timeout: %s", e)
            raise SearchNetworkError(
                "Brave search timeout",
                provider="brave",
                reason="timeout",
            ) from e
        except (httpx.ConnectError, httpx.TransportError) as e:
            logger.warning("Brave search network error: %s", e)
            raise SearchNetworkError(
                "Brave search network error",
                provider="brave",
                reason="connection error",
            ) from e
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (401, 403, 429):
                raise SearchError(
                    f"Brave API error: {code}",
                    provider="brave",
                    reason=f"HTTP {code}",
                    category="blocked",
                ) from e
            raise SearchParseError(
                f"Brave API error: {code}",
                provider="brave",
                reason=f"HTTP {code}",
            ) from e

        data = r.json()
        results = []
        for item in data.get("web", {}).get("results", [])[:num_results]:
            url_val = item.get("url", "")
            if not url_val or not _is_valid_url(url_val):
                continue
            results.append({
                "title": item.get("title", ""),
                "url": url_val,
                "snippet": item.get("description", ""),
            })
        if not results:
            raise SearchParseError(
                "Brave returned no parseable results",
                provider="brave",
                reason="no results",
            )
        return results


class SearXNGProvider:
    """Fallback using self-hosted SearXNG instance(s). User must set SEARXNG_BASE_URL or SEARXNG_INSTANCES."""

    def __init__(self, base_url: str | None, instances: list[str], dev_public_allowed: bool):
        self.base_url = (base_url or "").strip()
        self.instances = [u.strip() for u in instances if u.strip()]
        self.dev_public_allowed = dev_public_allowed
        self._using_public_list = False
        if self.base_url:
            self._urls = [self.base_url.rstrip("/")]
        elif self.instances:
            self._urls = [u.rstrip("/") for u in self.instances]
        elif dev_public_allowed:
            self._using_public_list = True
            self._urls = [u.rstrip("/") for u in DEV_PUBLIC_SEARXNG_LIST]
        else:
            self._urls = []

    def is_configured(self) -> bool:
        return len(self._urls) > 0

    async def search(
        self,
        query: str,
        num_results: int,
        client: httpx.AsyncClient,
    ) -> list[dict[str, str]]:
        if self._using_public_list:
            logger.warning(
                "Using public SearXNG instances (DEV_ALLOW_PUBLIC_SEARXNG=true); "
                "not reliable for production. Set SEARXNG_BASE_URL or SEARXNG_INSTANCES for production."
            )
        if not self._urls:
            raise SearchError(
                "SearXNG fallback not configured (set SEARXNG_BASE_URL or SEARXNG_INSTANCES)",
                provider="searxng",
                reason="not configured",
                category="unknown",
            )
        last_error: Exception | None = None
        for instance in self._urls:
            try:
                return await _searxng_search_one(instance, query, num_results, client)
            except Exception as e:
                last_error = e
                logger.debug("SearXNG instance %s failed: %s", instance, e)
        if last_error:
            if isinstance(last_error, SearchError):
                raise last_error
            raise SearchNetworkError(
                f"All SearXNG instances failed: {last_error}",
                provider="searxng",
                reason="all instances failed",
            ) from last_error
        raise SearchError(
            "SearXNG returned no results",
            provider="searxng",
            reason="no results",
            category="parse",
        )


async def _searxng_search_one(
    base_url: str,
    query: str,
    num_results: int,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    url = f"{base_url}/search"
    params = {"q": query, "format": "json", "engines": "google,bing,duckduckgo"}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PerplexityBackend/1.0)"}
    try:
        r = await client.get(url, params=params, headers=headers, timeout=10.0)
        r.raise_for_status()
    except httpx.TimeoutException as e:
        raise SearchNetworkError(
            "SearXNG timeout",
            provider="searxng",
            reason="timeout",
        ) from e
    except (httpx.ConnectError, httpx.TransportError) as e:
        raise SearchNetworkError(
            "SearXNG connection error",
            provider="searxng",
            reason="connection error",
        ) from e
    data = r.json()
    results = []
    for item in data.get("results", [])[:num_results]:
        url_val = item.get("url", "")
        if not url_val or not _is_valid_url(url_val):
            continue
        results.append({
            "title": item.get("title", ""),
            "url": url_val,
            "snippet": item.get("content", ""),
        })
    if not results:
        raise SearchParseError(
            "SearXNG returned no parseable results",
            provider="searxng",
            reason="no results",
        )
    return results
