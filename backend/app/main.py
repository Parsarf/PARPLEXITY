import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.schemas import (
    AskRequest, AskResponse, SearchResult, SourceDoc,
    Chunk, ScoredChunk, SourceRef, AnswerClaim, AnswerQuality,
)
from app.services.search import (
    search as web_search,
    SearchError,
    SearchBlockedError,
    SearchParseError,
    SearchNetworkError,
)
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
from app.services.quality import (
    split_into_claims,
    extract_citations,
    enforce_citations_and_multisource,
    build_source_text_lookup,
    verify_claims,
    detect_contradictions,
    add_disagreement_note,
    compute_confidence,
)
from app import config

logger = logging.getLogger(__name__)

app = FastAPI(title="Perplexity-style Backend", version=config.APP_VERSION)

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
        raw = await web_search(q, num)
    except (SearchError, SearchBlockedError, SearchParseError, SearchNetworkError) as e:
        # Clear failure reporting: safe reason, no secrets (Phase 7)
        detail = f"Search failed: {e.reason}" if getattr(e, "reason", None) else "Search failed"
        logger.warning("Search failed: %s", detail)
        raise HTTPException(status_code=502, detail=detail)

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

    top_chunk_dicts = rank_chunks(q, chunks_list, top_k=10, per_source_cap=2)
    top_chunks_list = [ScoredChunk(**d) for d in top_chunk_dicts]

    answer: str | None = None
    answer_error: str | None = None
    source_map_list: list[SourceRef] = []
    context: str = ""
    chunk_id_to_sid: dict[str, str] = {}
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

    answer_claims_list: list[AnswerClaim] = []
    quality: AnswerQuality | None = None

    if answer and source_map_list:
        try:
            answer = await enforce_citations_and_multisource(
                query=q,
                draft_answer=answer,
                context=context,
                source_map=source_map_list,
                model=config.OPENAI_MODEL,
                api_key=config.OPENAI_API_KEY or "",
            )
            logger.info("Citation enforcement complete")

            raw_claims = split_into_claims(answer)
            answer_claims_list = [
                AnswerClaim(
                    text=c,
                    citations=extract_citations(c),
                    supported=False,
                    support_notes=None,
                )
                for c in raw_claims
            ]

            source_lookup = build_source_text_lookup(top_chunks_list, source_map_list, chunk_id_to_sid)
            answer_claims_list = verify_claims(answer_claims_list, source_lookup)

            contradictions = detect_contradictions(answer_claims_list, source_lookup)
            if contradictions:
                answer = add_disagreement_note(answer, answer_claims_list)
                logger.info("Contradictions detected, disagreement note added")

            quality = compute_confidence(answer_claims_list, source_map_list, contradictions)

            logger.info(
                "Phase 6 quality: confidence=%s, distinct_sources=%d, coverage=%.2f, unsupported=%d, contradictions=%s",
                quality.confidence,
                quality.distinct_sources_used,
                quality.citation_coverage,
                quality.unsupported_claims,
                quality.contradictions_detected,
            )

        except Exception as e:
            logger.warning("Phase 6 quality analysis failed: %s", e, exc_info=True)

    return AskResponse(
        query=q,
        results=results,
        sources=sources_list,
        chunks=chunks_list,
        top_chunks=top_chunks_list,
        answer=answer,
        source_map=source_map_list,
        answer_error=answer_error,
        answer_claims=answer_claims_list,
        quality=quality,
    )
