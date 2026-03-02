# Single entry point for main.py (Phase 7)
from app.services.search.search_facade import search
from app.services.search.exceptions import (
    SearchError,
    SearchBlockedError,
    SearchParseError,
    SearchNetworkError,
)

__all__ = [
    "search",
    "SearchError",
    "SearchBlockedError",
    "SearchParseError",
    "SearchNetworkError",
]
