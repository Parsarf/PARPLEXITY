import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.schemas import AskRequest, AskResponse, SearchResult, SourceDoc, Chunk, ScoredChunk, SourceRef
from app.services.search import duckduckgo_search
from app.services.search.duckduckgo import DuckDuckGoSearchError
from app.services.fetch import fetch_url, FetchError, NonHtmlError
from app.services.extract import extract_main_text
from app.services.chunking import chunk_source_text_v1
from app.services.retrieval import rank_chunks
from app.services.answer import (
    build_source_map,
    pack_context,
    generate_cited_answer_with_retry,
    OpenAIAnswerError,
)
from app import config

app = FastAPI(title="Perplexity-style Backend", version="0.2.0")

MAX_QUERY_LENGTH = 400
MIN_NUM_RESULTS = 1
MAX_NUM_RESULTS = 10
MAX_SOURCES_TO_FETCH = 5
MAX_CONCURRENT_FETCHES = 4
TEXT_PREVIEW_MAX_CHARS = 2500
MAX_CHUNKS_TOTAL = 60


@app.get("/health")
def health():
    return {"status": "ok"}


async def _build_source_doc(
    result: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> SourceDoc:
    """Fetch URL, extract text, return SourceDoc. On failure, return SourceDoc with error set."""
    title = result.get("title") or ""
    url = result["url"]
    snippet = result.get("snippet") or None
    try:
        async with semaphore:
            _ct, html = await fetch_url(url)
        ext_title, text = extract_main_text(html)
        if ext_title:
            title = ext_title
        if len(text) > TEXT_PREVIEW_MAX_CHARS:
            text = text[:TEXT_PREVIEW_MAX_CHARS] + "..."
        if not text.strip():
            return SourceDoc(title=title, url=url, snippet=snippet, text="", error="No content extracted")
        return SourceDoc(title=title, url=url, snippet=snippet, text=text, error=None)
    except NonHtmlError as e:
        return SourceDoc(title=title, url=url, snippet=snippet, text="", error=str(e))
    except FetchError as e:
        return SourceDoc(title=title, url=url, snippet=snippet, text="", error=str(e))
    except Exception as e:
        return SourceDoc(title=title, url=url, snippet=snippet, text="", error=str(e))


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query must be non-empty")
    if len(q) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"query must be at most {MAX_QUERY_LENGTH} characters",
        )
    num = request.num_results
    if num < MIN_NUM_RESULTS or num > MAX_NUM_RESULTS:
        raise HTTPException(
            status_code=400,
            detail=f"num_results must be between {MIN_NUM_RESULTS} and {MAX_NUM_RESULTS}",
        )
    try:
        raw = await duckduckgo_search(q, num)
    except DuckDuckGoSearchError:
        raise HTTPException(status_code=502, detail="Search failed")

    # Defensive: skip any malformed result so one bad URL cannot crash /ask
    results = []
    for r in raw:
        try:
            results.append(SearchResult(**r))
        except ValidationError:
            continue
    to_fetch = raw[:MAX_SOURCES_TO_FETCH]
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    source_tasks = [_build_source_doc(r, semaphore) for r in to_fetch]
    sources = await asyncio.gather(*source_tasks)
    sources_list = list(sources)

    # Phase 3: chunk good sources (error is None, non-empty text)
    all_chunk_dicts: list[dict[str, Any]] = []
    for src in sources_list:
        if src.error is not None or not (src.text or "").strip():
            continue
        chunk_dicts = chunk_source_text_v1(
            src.text,
            str(src.url),
            src.title,
        )
        all_chunk_dicts.extend(chunk_dicts)
    all_chunk_dicts = all_chunk_dicts[:MAX_CHUNKS_TOTAL]
    chunks_list = [Chunk(**d) for d in all_chunk_dicts]

    # Phase 4: keyword ranking + diversity cap -> top_chunks
    top_chunk_dicts = rank_chunks(q, chunks_list, top_k=10, per_source_cap=2)
    top_chunks_list = [ScoredChunk(**d) for d in top_chunk_dicts]

    # Phase 5: answer synthesis with citations (OpenAI)
    answer: str | None = None
    answer_error: str | None = None
    source_map_list: list[SourceRef] = []
    if not top_chunks_list:
        answer = "I couldn't find relevant source text for this query."
    else:
        source_refs, chunk_id_to_sid = build_source_map(top_chunks_list)
        source_map_list = source_refs
        context = pack_context(top_chunks_list, chunk_id_to_sid, max_chars=12000)
        try:
            answer = await generate_cited_answer_with_retry(
                q,
                context,
                model=config.OPENAI_MODEL,
                api_key=config.OPENAI_API_KEY or "",
            )
        except OpenAIAnswerError as e:
            answer = None
            answer_error = str(e)

    return AskResponse(
        query=q,
        results=results,
        sources=sources_list,
        chunks=chunks_list,
        top_chunks=top_chunks_list,
        answer=answer,
        source_map=source_map_list,
        answer_error=answer_error,
    )
