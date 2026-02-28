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


OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY") or None
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
