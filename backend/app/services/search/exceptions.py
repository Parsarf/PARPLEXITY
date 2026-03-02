"""
Structured search exceptions for clear failure reporting (Phase 7).
Each carries provider, reason (safe to return to API), and category.
"""

from __future__ import annotations


class SearchError(Exception):
    """Generic search failure. Base for all search-layer exceptions."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "unknown",
        reason: str | None = None,
        category: str = "unknown",
    ):
        super().__init__(message)
        self.provider = provider
        self.reason = reason if reason is not None else message
        self.category = category


class SearchBlockedError(SearchError):
    """Search provider blocked the request (e.g. HTTP 429, captcha)."""

    def __init__(self, message: str, *, provider: str = "unknown", reason: str | None = None):
        r = reason or message
        super().__init__(message, provider=provider, reason=r, category="blocked")


class SearchParseError(SearchError):
    """Provider returned 200 but results could not be parsed."""

    def __init__(self, message: str, *, provider: str = "unknown", reason: str | None = None):
        r = reason or message
        super().__init__(message, provider=provider, reason=r, category="parse")


class SearchNetworkError(SearchError):
    """Timeout or connection error talking to the provider."""

    def __init__(self, message: str, *, provider: str = "unknown", reason: str | None = None):
        r = reason or message
        super().__init__(message, provider=provider, reason=r, category="network")
