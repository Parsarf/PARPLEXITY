# Perplexity-style Backend (Phase 1 + 2)

## Run

From this directory (`backend/`):

```bash
# Create venv and install dependencies (optional)
python3 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Start server
python -m uvicorn app.main:app --reload --port 8000
```

- **GET /health** — returns `{"status":"ok"}`
- **POST /ask** — body: `{"query": "what is retrieval augmented generation", "num_results": 5}`  
  Returns `AskResponse` with `query`, `results` (list of `SearchResult`: title, url, snippet), and `sources` (list of `SourceDoc`: title, url, snippet, text preview, optional error). Phase 2 fetches each result URL and extracts main text; PDFs are skipped.

## Definition of done (Phase 1)

1. Server starts without errors.
2. GET /health returns `{"status":"ok"}`.
3. POST /ask with the example body returns HTTP 200 with 1–5 results, each with valid title and url.
4. Search logic lives in `app/services/search/duckduckgo.py`; `main.py` only wires the endpoint.

## Definition of done (Phase 2)

1. Server runs; /ask returns HTTP 200 with `sources` containing extracted text previews for 1–3+ URLs.
2. PDFs are skipped (no crash).
3. Fetch logic in `app/services/fetch/`, extraction in `app/services/extract/`; `main.py` orchestrates only.
4. Timeouts and error handling in place; failed URLs yield `SourceDoc` with `error` set and `text=""`.
