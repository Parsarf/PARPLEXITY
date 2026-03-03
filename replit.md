# Perplexity-style Backend

## Overview

A Perplexity-style search and answer API built with FastAPI. It searches DuckDuckGo, fetches and extracts content from result pages, ranks chunks using keyword retrieval, and generates cited answers using OpenAI.

## Architecture

- **Language**: Python 3.12
- **Framework**: FastAPI + Uvicorn
- **Backend only** — no frontend

### Project Layout

```
backend/
  app/
    main.py          # FastAPI app, /ask, /upload, /export endpoints
    config.py        # Environment variable loading (OPENAI_API_KEY, OPENAI_MODEL)
    schemas.py       # Pydantic models (incl. CitationFormats, ExportResponse)
    services/
      search/        # DuckDuckGo HTML scraper + SearXNG fallback
      fetch/         # Async HTTP fetcher
      extract/       # Readability-based text extraction + PDF extraction
      chunking/      # Text chunking (paragraph-aware) + PDF chunker
      retrieval/     # Keyword-based chunk ranking with diversity
      answer/        # OpenAI answer generation with citations
      citation/      # Phase 11: Citation formatting (APA, MLA, Chicago, BibTeX)
        formatter.py          # Pure string formatting, no external deps
      quality/       # Phase 6: Trust + Quality
        claim_parser.py       # Split answer into claims, extract citations
        citation_enforcer.py  # Enforce multi-source + citation coverage (OpenAI repair)
        support_verifier.py   # Deterministic keyword-based claim verification
        contradiction.py      # Detect contradictions between sources
        confidence.py         # Compute confidence score (high/medium/low)
      metadata/      # Crossref DOI metadata client
      classification/ # Source type classifier
      scoring/       # Authority scorer
      evidence/      # Quote-exact evidence block builder
```

## Endpoints

- `GET /health` — returns `{"status": "ok"}`
- `POST /ask` — body: `{"query": "...", "num_results": 8}` — returns AskResponse with search results, sources, chunks, cited answer, citations, answer_claims (verified), quality metrics, and query_id
- `GET /export/{query_id}?format=bibtex|apa|mla|chicago|json` — export citations from a previous /ask query
- `POST /upload` — upload a PDF for analysis
- `GET /upload/{source_id}/chunks` — retrieve chunks from an uploaded PDF

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes (for answers) | None | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | OpenAI model to use |

## Development

Backend runs on **localhost:8000** in development.

## Key Parameters

### Chunking (chunker_v1.py)
- `target_words=150` — target chunk size for paragraph packing
- `max_words=250` — hard limit per chunk
- `min_words=30` — minimum to keep (filters boilerplate)

### Retrieval (keyword_retriever_v1.py)
- `top_k=10` — max chunks returned
- `per_source_cap=2` — max chunks per source URL
- `min_sources=2` — minimum distinct source URLs guaranteed in output

## Deployment

Configured for autoscale deployment using Gunicorn with Uvicorn workers on port 5000.
