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
    main.py          # FastAPI app and /ask endpoint orchestration
    config.py        # Environment variable loading (OPENAI_API_KEY, OPENAI_MODEL)
    schemas.py       # Pydantic models
    services/
      search/        # DuckDuckGo HTML scraper
      fetch/         # Async HTTP fetcher
      extract/       # Readability-based text extraction
      chunking/      # Text chunking
      retrieval/     # Keyword-based chunk ranking
      answer/        # OpenAI answer generation with citations
```

## Endpoints

- `GET /health` — returns `{"status": "ok"}`
- `POST /ask` — body: `{"query": "...", "num_results": 8}` — returns full AskResponse with search results, sources, chunks, and a cited answer

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
