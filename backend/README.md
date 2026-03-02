# Perplexity-style Backend (Phases 1–7)

## Overview

Backend-only API: search → fetch/extract → chunk → retrieve → OpenAI cited answer → Phase 6 quality/trust → **Phase 7 search reliability and clear failure reporting.**

App version is defined in `app/config.py` as `APP_VERSION` (single source of truth).

## Run

From this directory (`backend/`):

```bash
# One method only: use backend/requirements.txt
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Start server
python -m uvicorn app.main:app --reload --port 8000
```

- **GET /health** — returns `{"status":"ok"}`
- **POST /ask** — body: `{"query": "what is retrieval augmented generation", "num_results": 5}`

## Pipeline outputs (response shape)

`POST /ask` returns `AskResponse` with:

| Field | Description |
|-------|-------------|
| `query` | Echo of the query |
| `results` | List of `SearchResult`: title, url, snippet (from search) |
| `sources` | List of `SourceDoc`: title, url, snippet, text preview, optional error |
| `chunks` | All chunks from extracted source text |
| `top_chunks` | Top-ranked chunks used for the answer |
| `answer` | Cited answer text (or null on error) |
| `source_map` | Citation refs S1..SN (id, title, url) |
| `answer_error` | Set if OpenAI/answer step failed |
| `answer_claims` | Per-claim verification (Phase 6) |
| `quality` | Confidence, distinct_sources_used, citation_coverage, unsupported_claims, contradictions_detected |

## Search configuration (Phase 7)

Search is the single entry point via `app.services.search.search_facade`. Primary provider is DuckDuckGo HTML scraping; fallback is configurable.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes (for answers) | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Model for answer generation |
| `SEARCH_FALLBACK_PROVIDER` | No | `none` | `none` \| `brave` \| `searxng` |
| `BRAVE_SEARCH_API_KEY` | If fallback=brave | — | Brave Search API key |
| `SEARXNG_BASE_URL` | If fallback=searxng (single) | — | e.g. `https://search.example.com` |
| `SEARXNG_INSTANCES` | If fallback=searxng (multi) | — | Comma-separated instance URLs |
| `DEV_ALLOW_PUBLIC_SEARXNG` | No | — | Set `true` to allow hardcoded public instances (dev only; logs warning) |

- **Production:** Set a fallback (`brave` with `BRAVE_SEARCH_API_KEY`, or `searxng` with your own `SEARXNG_BASE_URL` / `SEARXNG_INSTANCES`). Do not rely on public SearXNG in production.
- No secrets in code: use environment variables or a local `.env` (not committed).

## Production note

- DDG HTML scraping may be **blocked** on some hosted IPs (e.g. 429, captcha). Use a production fallback: **Brave Search API** or **self-hosted SearXNG**.
- Public SearXNG instances are unreliable for production; use `SEARXNG_BASE_URL` or `SEARXNG_INSTANCES` with your own instance(s).

## Troubleshooting

When search fails, the API returns **HTTP 502** with a JSON `detail` that explains the reason (no raw HTML, no secrets):

| Example `detail` | Meaning |
|------------------|---------|
| `Search failed: ddg failed (HTTP 429) and fallback not configured` | DDG blocked (rate limit); set a fallback provider |
| `Search failed: ddg failed (DDG parse failed (no result containers matched)) and fallback not configured` | DDG returned 200 but page structure changed; set fallback or retry later |
| `Search failed: ddg failed (timeout) and fallback not configured` | Network/timeout to DDG; set fallback or check network |
| `Search failed: ddg failed (...) and fallback brave failed (HTTP 401)` | DDG failed and Brave API key missing/invalid |

## Repository hygiene

- **.gitignore** covers: `.env`, `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`. Do not commit `.env` or any file containing API keys.
- **Secrets scan** (run from repo root before commit):
  ```bash
  git grep -E 'sk-[a-zA-Z0-9]' -- '*.py' '*.env' '*.md' 2>/dev/null || true
  git grep -E 'OPENAI_API_KEY=' -- '*.py' '*.env' 2>/dev/null || true
  ```
  No matches should appear in tracked files.

## Definition of done (Phases 1–2, historical)

1. Server starts; GET /health returns `{"status":"ok"}`.
2. POST /ask returns HTTP 200 with `results` and `sources` (extracted text); PDFs skipped; fetch/extract in `app/services/fetch` and `app/services/extract`.

## Definition of done (Phase 7, current)

1. main.py calls only the search facade; no direct DDG usage.
2. No link-dump fallback; zero parseable results → explicit parse failure and clear 502 detail.
3. Fallback is configured via env (Brave or self-hosted SearXNG); no hardcoded public SearXNG in production path.
4. Search failures return 502 with a safe, informative `detail` (blocked vs parse vs timeout).
5. Dependencies: one install method (`pip install -r backend/requirements.txt`); no unused `duckduckgo-search`.
6. No secrets in tracked files; .gitignore covers .env, .venv, caches.
