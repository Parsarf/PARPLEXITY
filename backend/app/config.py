"""App settings loaded from environment variables.

Security note:
- Do NOT hardcode API keys in source code.
- Provide OPENAI_API_KEY via environment variables or a local .env file (not committed).
"""

from __future__ import annotations

import os

# Optional: load backend/.env if python-dotenv is installed.
# If it's not installed, this block safely does nothing.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


# Single source of version truth (used by FastAPI app and docs)
APP_VERSION: str = "0.7.0"

OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY") or None
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ── Search (Phase 7) ─────────────────────────────────────────────────────────
# Fallback: none | brave | searxng
SEARCH_FALLBACK_PROVIDER: str = (
    os.environ.get("SEARCH_FALLBACK_PROVIDER", "none").strip().lower()
)
if SEARCH_FALLBACK_PROVIDER not in ("none", "brave", "searxng"):
    SEARCH_FALLBACK_PROVIDER = "none"

BRAVE_SEARCH_API_KEY: str | None = os.environ.get("BRAVE_SEARCH_API_KEY") or None
# Single instance or comma-separated list (user-provided; no hardcoded public list in production)
SEARXNG_BASE_URL: str | None = os.environ.get("SEARXNG_BASE_URL") or None
_searxng_env = os.environ.get("SEARXNG_INSTANCES", "").strip()
SEARXNG_INSTANCES: list[str] = [
    u.strip() for u in _searxng_env.split(",") if u.strip()
] if _searxng_env else []

# Dev-only: allow hardcoded public SearXNG list; must log warning (not for production)
DEV_ALLOW_PUBLIC_SEARXNG: bool = (
    os.environ.get("DEV_ALLOW_PUBLIC_SEARXNG", "").strip().lower()
    in ("1", "true", "yes")
)
