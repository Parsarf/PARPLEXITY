# Perplexity-style Backend — Complete Developer Reference

This is the **single source document** for understanding the entire project: what it does, how it works, every module, every constant, and every flow. Read this to understand the system without reading the code.

---

## 1. What This Project Is

- **Type:** Backend-only API (no frontend).
- **Purpose:** Answer a user question by searching the web, fetching and extracting content from result pages, ranking text chunks by relevance, and generating a **cited answer** using OpenAI, then running a **trust/quality** layer (Phase 6) and **search reliability** (Phase 7).
- **Inspiration:** Perplexity-style “search → sources → cited answer” flow.
- **Stack:** Python 3.12+, FastAPI, Uvicorn; OpenAI for answer generation; custom DuckDuckGo HTML scraping (with optional Brave/SearXNG fallback).

---

## 2. High-Level Pipeline (Order of Execution)

When a client calls `POST /ask` with `{"query": "...", "num_results": N}`:

1. **Validate** query (non-empty, length ≤ 400) and `num_results` (1–10).
2. **Search** (Phase 7): Single entry point is the search facade. It normalizes the query, runs DuckDuckGo with retries/backoff, optionally uses a configured fallback (Brave or SearXNG) if DDG fails. Returns a list of `{title, url, snippet}`. No “link dump”; zero results → explicit failure and 502 with a clear reason.
3. **Fetch:** For the first up to **5** search results, fetch each URL concurrently (semaphore-limited). Skip PDFs; accept only `text/html`, `text/plain`, `application/xhtml+xml`. Max body 2 MB; retries 2.
4. **Extract:** For each fetched HTML, extract main readable text (and title) using readability-lxml if available, else strip script/style/nav/footer/header and take body text. Truncate to 2500 chars per source for storage.
5. **Chunk:** For each source with extracted text, split into paragraph-aware chunks (target 150 words, max 250, min 30), filter boilerplate, dedupe by hash. Cap total chunks at 60 across all sources.
6. **Retrieve:** Rank chunks by keyword overlap with the query (frequency + repeat bonus). Enforce diversity: at least 2 distinct sources, at most 2 chunks per source, top 10 chunks total.
7. **Source map:** Assign labels S1, S2, … by unique source URL (order of first appearance). Build a context string (chunks with “[S1] title — url” headers) up to 12,000 characters.
8. **Answer:** Call OpenAI Chat Completions with a strict “only use provided sources, cite [S1]/[S2]” system prompt. If the model returns no citations, retry once with an extra instruction.
9. **Citation enforcement (Phase 6):** Parse the answer into claims; if citation coverage &lt; 100% or &lt; 2 distinct sources or one source dominates, call OpenAI again to repair citations (add/fix [S1], [S2], …) without changing meaning.
10. **Claim parsing:** Split the (repaired) answer into atomic claims (bullets or sentences). Extract citation IDs from each claim.
11. **Verification:** For each claim, check cited source text for keyword overlap (≥2 overlapping keywords + at least one “anchor” term ≥4 chars). Mark `supported` / `support_notes`.
12. **Contradiction detection:** Among claims from different sources, detect numeric mismatches or opposite polarity (positive vs negative). If any, append a disagreement note to the answer.
13. **Confidence:** Compute `high` / `medium` / `low` from distinct_sources_used, citation_coverage, unsupported_claims, contradictions.
14. **Response:** Return `AskResponse` with all of: query, results, sources, chunks, top_chunks, answer, source_map, answer_error (if any), answer_claims, quality.

If search fails (DDG + fallback both fail or fallback not configured), return **502** with a JSON `detail` like `"Search failed: ddg failed (HTTP 429) and fallback not configured"` (no raw HTML, no secrets).

---

## 3. Project Layout and Entry Points

- **`app/main.py`** — FastAPI app. Only endpoints: `GET /health`, `POST /ask`. Uses `config.APP_VERSION` for version. Imports search from `app.services.search` (the facade), never DDG directly.
- **`app/config.py`** — Single source of version (`APP_VERSION`) and all env-based config (OpenAI, search fallback). Loads `.env` via python-dotenv if present.
- **`app/schemas.py`** — Pydantic models: AskRequest, AskResponse, SearchResult, SourceDoc, Chunk, ScoredChunk, SourceRef, AnswerClaim, AnswerQuality.

**Services (all under `app/services/`):**

- **`search/`** — Search facade (only entry point for main), DDG parser, exceptions, fallback providers (Brave, SearXNG).
- **`fetch/`** — HTTP fetch (single URL → content_type, body_text).
- **`extract/`** — HTML → (title, main text).
- **`chunking/`** — Text → list of chunk dicts (Chunk schema).
- **`retrieval/`** — Query + chunks → ranked top_k dicts (ScoredChunk schema).
- **`answer/`** — Source map builder, context packer, OpenAI cited-answer generation (with retry if no citations).
- **`quality/`** — Claim parser, citation enforcer (OpenAI repair), source-text lookup, claim verifier, contradiction detection, disagreement note, confidence (AnswerQuality).

---

## 4. Configuration (Environment Variables)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_VERSION` | — | (in code: `"0.7.0"`) | Single source of version; set in `config.py`, used by FastAPI. |
| `OPENAI_API_KEY` | Yes (for answers) | — | OpenAI API key. Not committed; use env or `.env`. |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Model for answer and citation-repair calls. |
| `SEARCH_FALLBACK_PROVIDER` | No | `none` | `none` \| `brave` \| `searxng`. Invalid values reset to `none`. |
| `BRAVE_SEARCH_API_KEY` | If fallback=brave | — | Brave Search API key (header `X-Subscription-Token`). |
| `SEARXNG_BASE_URL` | If fallback=searxng (single instance) | — | e.g. `https://search.example.com`. |
| `SEARXNG_INSTANCES` | If fallback=searxng (multi) | — | Comma-separated URLs. User-provided only; no hardcoded public list in production. |
| `DEV_ALLOW_PUBLIC_SEARXNG` | No | — | Set `1`/`true`/`yes` to allow a hardcoded public SearXNG list; logs a warning on every search use. Not for production. |

Security: Do not hardcode API keys. `.env` is gitignored. Run a secrets scan (e.g. `git grep` for `sk-` and `OPENAI_API_KEY=`) on tracked files before commit.

---

## 5. API Contract

### GET /health

- Returns `{"status": "ok"}`.
- No auth, no side effects.

### POST /ask

- **Request body:** `AskRequest`: `query` (str), `num_results` (int, default 8).
- **Validation:**
  - `query`: non-empty after strip; length ≤ 400 → else 400.
  - `num_results`: between 1 and 10 (inclusive) → else 400.
- **Success:** 200, body = `AskResponse` (see schemas below).
- **Search failure:** 502, body `{"detail": "Search failed: <reason>"}`. Reason is safe (blocked/parse/timeout/not configured), no HTML, no secrets.
- **Other errors:** e.g. 400 for validation.

### AskResponse (response shape)

- `query` (str) — Echo of the query.
- `results` (list[SearchResult]) — Raw search results: `title`, `url`, `snippet`. May include results that were not fetched (only first 5 are fetched).
- `sources` (list[SourceDoc]) — One per fetched URL: `title`, `url`, `snippet`, `text` (extracted preview, max 2500 chars), `error` (set if fetch/extract failed).
- `chunks` (list[Chunk]) — All chunks from sources that had text (up to 60 total): `chunk_id`, `source_url`, `source_title`, `chunk_index`, `text`, optional `start_char`/`end_char`.
- `top_chunks` (list[ScoredChunk]) — Top 10 chunks used for the answer: same fields as Chunk plus `score`.
- `answer` (str | null) — Cited answer text. Null if OpenAI failed; else may be the “no relevant source text” message if top_chunks was empty.
- `source_map` (list[SourceRef]) — Citation refs: `id` (e.g. "S1"), `title`, `url`.
- `answer_error` (str | null) — Set if OpenAI/answer step raised (e.g. missing API key, HTTP error).
- `answer_claims` (list[AnswerClaim]) — After Phase 6: per-claim `text`, `citations`, `supported`, `support_notes`.
- `quality` (AnswerQuality | null) — After Phase 6: `confidence` (high/medium/low), `distinct_sources_used`, `citation_coverage`, `unsupported_claims`, `contradictions_detected`. Null if Phase 6 failed or no answer/source_map.

---

## 6. Search Layer (Phase 7) — Full Logic

### 6.1 Entry point

- **Only** entry point used by main: `app.services.search.search_facade.search(query, num_results, timeout=15.0)`.
- main.py does **not** import or call DuckDuckGo or fallback providers directly.

### 6.2 Query normalization (facade)

- Trim, collapse whitespace with `re.sub(r"\s+", " ", query.strip())`.
- If length &gt; 400, cap at 400 and rstrip.
- If empty after normalization → raise `SearchError(provider="unknown", reason="empty query", category="unknown")`.

### 6.3 DDG attempt (with retries)

- **Retries:** Up to 3 attempts. Between attempts: exponential backoff 1s, 2s (delay = 1.0 * 2^(attempt-1)).
- **Single attempt:** Call `_ddg_search(query, num_results, client)` from `duckduckgo.py`.
  - **Request:** GET `https://duckduckgo.com/html/?q={query}&kl=us-en`, with rotating User-Agent, Accept, Accept-Language, Referer, DNT.
  - **Block detection:** Before parsing, run `_detect_block(html, status)`: if status in (403, 429, 503) → reason `"HTTP {status}"`; else if HTML contains any of (duckduckgo.com/sorry, duckduckgo.com/abuse, "unusual traffic", "captcha", "verify you are human", "access denied", "checking your browser") → reason with that signal; else if len(html) &lt; 500 → "suspiciously short response". If block_reason → raise `SearchBlockedError("DDG blocked (...)", provider="ddg", reason=block_reason)`.
  - **Parsing:** `_parse_ddg_html(html, num_results)` tries up to three selector strategies in order (containers + link + snippet). If any strategy yields at least one valid result, return that list. **No link-dump fallback:** if no strategy returns results, raise `SearchParseError("DDG parse failed (no result containers matched)", provider="ddg", reason="DDG parse failed (no result containers matched)")`.
  - **URL validation (DDG):** Max URL length 2000; strip DDG redirects (query keys uddg, u2, u); drop links whose host contains "duckduckgo.com"; only append if `_is_valid_url(url)`.
- **Network errors:** Timeout/Connect/Transport/Proxy from httpx are **not** caught in DDG; they propagate to the facade. Facade maps them to `SearchNetworkError` (reason "timeout" or "connection error") and may retry (for timeout/connection) or break and try fallback.
- **After DDG success:** Deduplicate results by normalized URL (lower, strip trailing slash), then return. If DDG returns empty list (shouldn’t happen given parse raises), facade treats as parse failure and breaks to fallback path.

### 6.4 Fallback (when DDG fails)

- **When:** After all DDG retries failed (blocked, parse, or network). Facade has `ddg_failure_reason` and `ddg_failure_category` (blocked/parse/network).
- **Provider selection:** From config: `SEARCH_FALLBACK_PROVIDER`. If `none` → no fallback. If `brave` but `BRAVE_SEARCH_API_KEY` missing → no fallback (and later detail message says so). If `searxng` → build `SearXNGProvider(SEARXNG_BASE_URL, SEARXNG_INSTANCES, DEV_ALLOW_PUBLIC_SEARXNG)`. If that provider is SearXNG and `not is_configured()` (no URLs) → skip fallback (e.g. user set searxng but gave no URL/instances and no DEV flag).
- **SearXNG URL list:**
  - If `SEARXNG_BASE_URL` set → use that single instance.
  - Else if `SEARXNG_INSTANCES` non-empty → use that list.
  - Else if `DEV_ALLOW_PUBLIC_SEARXNG` true → use hardcoded `DEV_PUBLIC_SEARXNG_LIST` (e.g. searx.be, search.mdosch.de) and set `_using_public_list = True`. **Every time** `SearXNGProvider.search()` is called with `_using_public_list`, log a warning that public instances are not for production.
  - Else → `_urls = []`, `is_configured()` false, no fallback.
- **Brave:** GET `https://api.search.brave.com/res/v1/web/search`, params `q`, `count=min(num_results,20)`, header `X-Subscription-Token`. Parse `data["web"]["results"]` → {title, url, snippet}. Same URL validation as DDG (`_is_valid_url`). On 401/403/429 → SearchError category blocked; on other HTTP errors → SearchParseError; on timeout/connect → SearchNetworkError.
- **SearXNG:** GET `{base_url}/search`, params `q`, `format=json`, `engines=google,bing,duckduckgo`. Parse `data["results"]` → {title, url, snippet}. Try each instance in order; first success returns. Timeout 10s per request.
- **If fallback succeeds:** Dedupe by URL, return results.
- **If fallback fails:** Raise `SearchError` with reason combining DDG and fallback failure (e.g. "ddg failed (HTTP 429) and fallback brave failed (HTTP 401)").
- **If no fallback:** Raise a structured exception (SearchBlockedError / SearchParseError / SearchNetworkError / SearchError) with detail message that includes "fallback not configured" and, where applicable, why (missing key, missing SEARXNG URL/instances).

### 6.5 Search exceptions (all from `app.services.search.exceptions`)

- **SearchError** — Base; attributes: `provider`, `reason`, `category`. Used for generic and combined failures.
- **SearchBlockedError** — category `"blocked"` (e.g. HTTP 429, captcha).
- **SearchParseError** — category `"parse"` (200 but no parseable results).
- **SearchNetworkError** — category `"network"` (timeout, connection).

main.py catches these four and returns 502 with `detail="Search failed: " + e.reason` (if present).

---

## 7. Fetch Layer

- **Function:** `fetch_url(url)` → `(content_type, body_text)`.
- **PDF:** If URL path ends with `.pdf` or contains `.pdf?` → raise `NonHtmlError("PDF URLs are skipped")`. If Content-Type is `application/pdf` → same.
- **Allowed types:** `text/html`, `text/plain`, `application/xhtml+xml`. Else → `NonHtmlError`.
- **Size:** Reject if Content-Length &gt; 2 MB; if body (UTF-8 bytes) &gt; 2 MB, truncate to 2 MB.
- **Retries:** 2 retries (3 attempts total) on httpx HTTPError. NonHtmlError is not retried.
- **Client:** Follow redirects, User-Agent Chrome-like, timeout 15s.

---

## 8. Extract Layer

- **Function:** `extract_main_text(html)` → `(title, text)`.
- **Primary:** If `readability` (readability-lxml) is importable, use `Document(html)`: title from `doc.title()`, text from `doc.summary()` (HTML stripped to plain text, whitespace normalized). Fallback title from `<title>` if needed. On any exception, fall back to heuristic.
- **Fallback:** BeautifulSoup with lxml; remove tags: script, style, nav, footer, header, aside; title from `soup.title`; text from body (or whole soup), separator space, normalize whitespace. Default title `"Untitled"`.
- **Normalization:** `re.sub(r"\s+", " ", text).strip()`.

---

## 9. Chunking Layer

- **Function:** `chunk_source_text_v1(text, source_url, source_title, target_words=150, max_words=250, min_words=30, max_chunks=20)` → list of dicts with Chunk schema.
- **Pass 1 — Units:** Split text by `\n\s*\n`, trim, drop empty.
- **Pass 2 — Pack:** Pack units into chunks. If a unit exceeds `max_words`, split by sentences first, then by max_words-sized word groups if needed. When adding the next unit would exceed `target_words`, flush current chunk. Cap total chunks by `max_chunks`.
- **Pass 3 — Filter:** Drop chunks with word count &lt; min_words. Drop chunks that contain boilerplate phrases ("cookie", "subscribe", "newsletter", "sign up") and have &lt; 120 words. Deduplicate by SHA256 of normalized text (lower, collapse whitespace).
- **Output:** Each chunk dict: `chunk_id` (hash of source_url + index + text prefix), `source_url`, `source_title`, `chunk_index`, `text`, `start_char`, `end_char` (latter two None).

---

## 10. Retrieval Layer

- **Function:** `rank_chunks(query, chunks, top_k=10, per_source_cap=2, min_sources=2)` → list of dicts compatible with ScoredChunk.
- **Tokenize:** Lowercase, `re.findall(r"[a-z0-9]+", text)`, drop tokens length &lt; 2 and in STOPWORDS (a, an, the, is, are, …).
- **Scoring:** For each chunk, `score_text(query_tokens, chunk.text)`: for each query token, count occurrences in text; add `count * (1.0 + 0.2 * (count - 1))`. Chunks with score 0 are skipped. Only the first 300 chunks are scored.
- **Diversity:** Sort by score descending. First pass: fill distinct sources up to `target_min = min(min_sources, available_sources, top_k)` (one chunk per source, highest score per source). Second pass: fill remaining slots up to top_k, respecting per_source_cap (max 2 chunks per source). Result order: first the “one per source” set, then the rest by score.

---

## 11. Answer Layer

### 11.1 Source map and context

- **build_source_map(top_chunks):** Assign S1, S2, … by unique source URL (order of first appearance in top_chunks). Return `(list[SourceRef], chunk_id → source_id)`.
- **pack_context(top_chunks, chunk_id_to_sid, max_chars=12000):** Build string of blocks `"[Si] title — url\nchunk_text\n\n"`. Stop when adding next block would exceed max_chars; optionally add a truncated final block if remaining &gt; 80 chars.

### 11.2 OpenAI cited answer

- **System prompt:** Answer using ONLY provided sources; cite [S1], [S2] after relevant sentences; do not make up citations; if sources insufficient, say so.
- **User content:** "Context:\n{context}\n\nQuestion: {query}". max_tokens 1500, temperature 0.3.
- **Retry:** If response has no `[S\d+]`, call again with extra instruction: "Add citations [S1], [S2], etc. to every paragraph. Do not answer without citations."
- **Errors:** Missing API key or HTTP/empty choices → `OpenAIAnswerError`; main sets `answer` to None and `answer_error` to the message.

---

## 12. Quality Layer (Phase 6)

### 12.1 Citation enforcement

- **Input:** Draft answer, context, source_map, query.
- **Parse** draft into claims (bullets or sentences); extract citations per claim. Compute citation_coverage (fraction of claims with at least one citation), distinct source set, and per-source claim count.
- **Repair triggers:** coverage &lt; 1.0; or ≥2 sources available but claims use fewer than 2 distinct sources; or one source cited in more than 2 claims (or all claims cite a single source). If any → call OpenAI with REPAIR_SYSTEM_PROMPT (add/fix citations, don’t change meaning, spread across sources, return only revised text). Defaults: min_sources=2, min_coverage=1.0, max_claims_single_source=2.
- **Output:** Repaired answer string (or original if no repair).

### 12.2 Claim parsing

- **split_into_claims(answer):** If any line matches bullet pattern `[-*•]` or `\d+[.)]`, treat each non-empty line as a claim (strip bullet). Else split by sentence pattern `(?<=[.!?])\s+(?=[A-Z])`.
- **extract_citations(text):** Find all `[S\d+]` and `[..., S\d+, ...]` patterns; return ordered list of source IDs (e.g. ["S1", "S2"]).
- **remove_citation_markers(text):** Strip `[S1]`, `[S1, S2]` from text for verification.

### 12.3 Support verification

- **build_source_text_lookup(top_chunks, source_map, chunk_id_to_sid):** Map source id → concatenated chunk text for that source.
- **claim_supported_by_source(claim_text, source_text):** Extract up to 16 keywords (len ≥ 3, not in extended STOPWORDS) from claim and source. Require overlap ≥ 2 and at least one “anchor” (keyword len ≥ 4 present in source). Return (bool, note).
- **verify_claims(claims, source_lookup):** For each claim, remove citation markers; for each cited source, check support. If any citation supports → mark supported; else support_notes = concatenated reasons per source.

### 12.4 Contradiction detection

- **detect_contradictions(claims, source_lookup):** Only if ≥2 claims and ≥2 distinct cited sources. For each pair of claims from different source sets: require ≥2 common non-stopwords. If both have numbers and number sets differ → contradiction. If both have polarity (positive vs negative word sets) and polarities differ → contradiction. Return bool.
- **add_disagreement_note(answer, claims):** Build set of source IDs involved in claims; append "\n\n**Note:** Sources [S1], [S2], ... may present differing information...". Up to 3 source refs in the note.

### 12.5 Confidence

- **compute_confidence(claims, source_map, contradictions):** distinct_sources_used = number of unique cited source IDs; coverage = citation_coverage(claims); unsupported_claims = count of claims with supported=False.
  - **high:** distinct_sources_used ≥ 3, coverage == 1.0, unsupported_claims == 0, not contradictions.
  - **medium:** distinct_sources_used ≥ 2, coverage ≥ 0.8, unsupported_claims ≤ 1 (contradictions allowed).
  - **low:** else.
- Return AnswerQuality(confidence, distinct_sources_used, citation_coverage rounded 4 decimals, unsupported_claims, contradictions_detected).

---

## 13. Main.py Constants and Flow Details

- **MAX_QUERY_LENGTH** = 400  
- **MIN_NUM_RESULTS** = 1, **MAX_NUM_RESULTS** = 10  
- **MAX_SOURCES_TO_FETCH** = 5 (only first 5 search results are fetched)  
- **MAX_CONCURRENT_FETCHES** = 4 (semaphore for concurrent fetch_url)  
- **TEXT_PREVIEW_MAX_CHARS** = 2500 (per-source text truncation)  
- **MAX_CHUNKS_TOTAL** = 60 (chunks from all sources combined before retrieval)  
- **Retrieval call:** `rank_chunks(q, chunks_list, top_k=10, per_source_cap=2)` (min_sources default 2 in rank_chunks).  
- **Context:** `pack_context(..., max_chars=12000)`.  
- **Phase 6:** Wrapped in try/except; on exception log and leave answer_claims/quality as default (empty list / None); answer and source_map still returned.

---

## 14. Dependencies and Run

- **Single install method:** From repo root or backend: `pip install -r backend/requirements.txt`.  
- **requirements.txt:** fastapi, uvicorn[standard], httpx, beautifulsoup4, lxml, pydantic, readability-lxml. python-dotenv optional (config loads it if present).  
- **Run:** From `backend/`: `python -m uvicorn app.main:app --reload --port 8000`.  
- **Deploy:** Gunicorn with Uvicorn workers, bind 0.0.0.0:5000, chdir backend, app.main:app (see .replit deployment).

---

## 15. Git and Secrets

- **.gitignore:** .env, .venv/, __pycache__/, *.pyc, .DS_Store, etc.  
- **Secrets scan (before commit):**  
  `git grep -E 'sk-[a-zA-Z0-9]' -- '*.py' '*.env' '*.md'`  
  `git grep -E 'OPENAI_API_KEY=' -- '*.py' '*.env'`  
  No matches in tracked files.

---

## 16. Troubleshooting (502 Search Failures)

- **"ddg failed (HTTP 429) and fallback not configured"** — DDG rate-limited/blocked; set SEARCH_FALLBACK_PROVIDER and Brave or SearXNG config.  
- **"ddg failed (DDG parse failed (no result containers matched)) and fallback not configured"** — DDG HTML structure changed or empty; set fallback or retry later.  
- **"ddg failed (timeout) and fallback not configured"** — Network/timeout to DDG; set fallback or check network.  
- **"ddg failed (...) and fallback brave failed (HTTP 401)"** — Brave API key missing or invalid.  
- **"fallback not configured (SEARXNG_BASE_URL or SEARXNG_INSTANCES not set)"** — Provider is searxng but no URL/list and no DEV_ALLOW_PUBLIC_SEARXNG.

---

## 17. Summary Table: Where Everything Lives

| Concern | Location |
|--------|----------|
| App entry, /health, /ask orchestration | app/main.py |
| Version, env config | app/config.py |
| Request/response models | app/schemas.py |
| Search entry, normalization, retries, fallback orchestration | app/services/search/search_facade.py |
| DDG request, block detection, HTML parsing (no link dump) | app/services/search/duckduckgo.py |
| Search exception types | app/services/search/exceptions.py |
| Brave / SearXNG fallback | app/services/search/fallback_providers.py |
| HTTP fetch, PDF skip, content-type, size limit | app/services/fetch/http_fetcher.py |
| HTML → title + main text | app/services/extract/readability_extractor.py |
| Text → chunks (paragraph, filter, dedupe) | app/services/chunking/chunker_v1.py |
| Chunk ranking, diversity | app/services/retrieval/keyword_retriever_v1.py |
| Source map, context packing | app/services/answer/context_packer.py |
| OpenAI cited answer + retry | app/services/answer/openai_answerer.py |
| Claim split, citation extract, citation repair | app/services/quality/claim_parser.py, citation_enforcer.py |
| Claim verification (keyword support) | app/services/quality/support_verifier.py |
| Contradiction + disagreement note | app/services/quality/contradiction.py |
| Confidence (AnswerQuality) | app/services/quality/confidence.py |

This document is the single reference for understanding the whole project and all its logic and details.
