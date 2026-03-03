import asyncio
import logging
import uuid
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import ValidationError

from app.schemas import (
    AskRequest, AskResponse, SearchResult, SourceDoc,
    Chunk, ScoredChunk, SourceRef, AnswerClaim, AnswerQuality, EvidenceBlock, UploadResponse,
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
from app.services.extract.pdf_extractor import extract_pdf
from app.services.chunking import chunk_source_text_v1
from app.services.chunking.pdf_chunker import chunk_pdf_sections
from app.services.metadata.crossref_client import fetch_crossref_metadata
from app.services.retrieval import rank_chunks
from app.services.classification.source_classifier import classify_source
from app.services.scoring.authority_scorer import compute_authority_score
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
from app.services.evidence.evidence_builder import build_evidence_blocks
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
) -> tuple[SourceDoc, list[dict[str, Any]] | None]:
    """Returns (SourceDoc, PDF chunk dicts or None). If None, caller chunks from source.text (HTML)."""
    title = result.get("title") or ""
    url = result["url"]
    snippet = result.get("snippet") or None
    try:
        async with semaphore:
            content_type, body_text, pdf_bytes = await fetch_url(url)
        if pdf_bytes is not None:
            pdf_data = extract_pdf(pdf_bytes)
            pdf_meta = {
                "authors": pdf_data.get("authors") or [],
                "doi": pdf_data.get("doi"),
                "year": None,
                "journal": None,
                "volume": None,
                "issue": None,
                "publisher": None,
                "source_type": None,
                "page_count": pdf_data.get("page_count", 0),
                "abstract": (pdf_data.get("abstract") or "")[:500],
                "sections_found": [s.get("heading", "") for s in pdf_data.get("sections", [])],
            }
            if pdf_data.get("doi"):
                try:
                    crossref = await fetch_crossref_metadata(pdf_data["doi"])
                    if crossref:
                        pdf_meta["year"] = crossref.get("year")
                        pdf_meta["journal"] = crossref.get("journal")
                        pdf_meta["volume"] = crossref.get("volume")
                        pdf_meta["issue"] = crossref.get("issue")
                        pdf_meta["publisher"] = crossref.get("publisher")
                        pdf_meta["source_type"] = crossref.get("source_type")
                        if crossref.get("authors"):
                            pdf_meta["authors"] = crossref["authors"]
                except Exception:
                    pass
            pdf_title = pdf_data["title"] if (pdf_data.get("title") or "") != "Untitled" else title
            full_text_preview = (pdf_data.get("full_text") or "")[:TEXT_PREVIEW_MAX_CHARS]
            if len(pdf_data.get("full_text") or "") > TEXT_PREVIEW_MAX_CHARS:
                full_text_preview += "..."
            source = SourceDoc(
                title=pdf_title,
                url=url,
                snippet=snippet,
                text=full_text_preview,
                error=None,
                is_pdf=True,
                pdf_metadata=pdf_meta,
            )
            pdf_chunks = chunk_pdf_sections(
                pdf_data=pdf_data,
                source_url=str(url),
                source_title=pdf_title,
            )
            return (source, pdf_chunks)
        ext_title, text = extract_main_text(body_text or "")
        if ext_title:
            title = ext_title
        if len(text) > TEXT_PREVIEW_MAX_CHARS:
            text = text[:TEXT_PREVIEW_MAX_CHARS] + "..."
        if not text.strip():
            return (SourceDoc(title=title, url=url, snippet=snippet, text="", error="No content extracted"), None)
        return (SourceDoc(title=title, url=url, snippet=snippet, text=text, error=None), None)
    except NonHtmlError as e:
        return (SourceDoc(title=title, url=url, snippet=snippet, text="", error=str(e)), None)
    except FetchError as e:
        return (SourceDoc(title=title, url=url, snippet=snippet, text="", error=str(e)), None)
    except Exception as e:
        return (SourceDoc(title=title, url=url, snippet=snippet, text="", error=str(e)), None)


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
    gathered = await asyncio.gather(*source_tasks)
    sources_list = [g[0] for g in gathered]
    for src in sources_list:
        try:
            classification = classify_source(
                url=str(src.url),
                text=src.text or "",
                title=src.title or "",
                is_pdf=src.is_pdf,
                pdf_metadata=src.pdf_metadata,
            )
            src.source_type = classification["source_type"]
            src.source_type_confidence = classification["confidence"]
            src.source_type_signals = classification["signals"]
        except Exception as e:
            logger.warning("Classification failed for %s: %s", src.url, e)
        try:
            scoring = compute_authority_score(
                source_type=src.source_type,
                confidence=src.source_type_confidence,
                is_pdf=src.is_pdf,
                pdf_metadata=src.pdf_metadata,
                source_url=str(src.url),
            )
            src.authority_score = scoring["authority_score"]
            src.authority_breakdown = scoring["score_breakdown"]
        except Exception as e:
            logger.warning("Authority scoring failed for %s: %s", src.url, e)

    all_chunk_dicts = []
    for g in gathered:
        if g[1] is not None:
            all_chunk_dicts.extend(g[1])
    for src in sources_list:
        if src.is_pdf:
            continue
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

    source_authority = {}
    for src in sources_list:
        if src.url is not None and getattr(src, "authority_score", None) is not None:
            source_authority[str(src.url)] = src.authority_score

    top_chunk_dicts = rank_chunks(
        q,
        chunks_list,
        top_k=10,
        per_source_cap=2,
        source_authority=source_authority,
    )
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
    evidence_blocks_raw: list[dict] = []

    if answer and source_map_list:
        source_lookup: dict[str, str] = {}
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

        # Phase 10: Build evidence blocks (quote extraction + verification + page numbers)
        try:
            top_chunk_ids = {sc.chunk_id for sc in top_chunks_list}
            top_chunks_with_page = [c for c in chunks_list if c.chunk_id in top_chunk_ids]
            evidence_blocks_raw = await build_evidence_blocks(
                answer=answer,
                context=context,
                source_map=source_map_list,
                query=q,
                top_chunks=top_chunks_with_page,
                chunk_id_to_sid=chunk_id_to_sid,
                source_text_lookup=source_lookup,
            )
        except Exception as e:
            logger.warning("Evidence blocks failed: %s", e)
            evidence_blocks_raw = []

    evidence_blocks = [EvidenceBlock(**eb) for eb in evidence_blocks_raw] if evidence_blocks_raw else []

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
        evidence_blocks=evidence_blocks,
    )


# In-memory store for uploaded document chunks (simple dict, replaced by DB later)
_upload_store: dict[str, list[dict]] = {}


@app.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """
    Upload a PDF for use in research queries.
    Returns metadata and a source_id that can be referenced later.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()

    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20 MB)")

    if not pdf_bytes[:5] == b"%PDF-":
        raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF")

    pdf_data = extract_pdf(pdf_bytes)

    source_id = f"upload_{uuid.uuid4().hex[:12]}"

    chunks = chunk_pdf_sections(
        pdf_data=pdf_data,
        source_url=f"upload://{source_id}/{file.filename}",
        source_title=pdf_data.get("title") or "Untitled",
    )

    _upload_store[source_id] = chunks

    year = None
    if pdf_data.get("doi"):
        try:
            crossref = await fetch_crossref_metadata(pdf_data["doi"])
            if crossref:
                year = crossref.get("year")
        except Exception:
            pass

    return UploadResponse(
        filename=file.filename or "document.pdf",
        title=pdf_data.get("title") or "Untitled",
        authors=pdf_data.get("authors") or [],
        doi=pdf_data.get("doi"),
        abstract=(pdf_data.get("abstract") or "")[:1000],
        sections_found=[s.get("heading", "") for s in pdf_data.get("sections", [])],
        page_count=pdf_data.get("page_count", 0),
        chunks_generated=len(chunks),
        source_id=source_id,
    )


@app.get("/upload/{source_id}/chunks")
async def get_upload_chunks(source_id: str):
    """Retrieve chunks from a previously uploaded PDF."""
    if source_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Upload not found")
    return {"source_id": source_id, "chunks": _upload_store[source_id]}
