from typing import Optional

from pydantic import BaseModel, HttpUrl


class AskRequest(BaseModel):
    query: str
    num_results: int = 8


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: Optional[str] = None


class SourceDoc(BaseModel):
    """A source with fetched and extracted main text (or error)."""

    title: str
    url: HttpUrl
    snippet: Optional[str] = None
    text: str = ""
    error: Optional[str] = None


class Chunk(BaseModel):
    """A chunk of text from a source, for retrieval/context."""

    chunk_id: str
    source_url: HttpUrl
    source_title: str
    chunk_index: int
    text: str
    start_char: Optional[int] = None
    end_char: Optional[int] = None


class ScoredChunk(BaseModel):
    """A chunk with a retrieval score (top evidence for answer generation)."""

    chunk_id: str
    source_url: HttpUrl
    source_title: str
    chunk_index: int
    text: str
    score: float


class SourceRef(BaseModel):
    """Citation reference: id (e.g. S1), title, url for rendering."""

    id: str
    title: str
    url: HttpUrl


class AnswerClaim(BaseModel):
    """One atomic claim with citations and verification."""

    text: str
    citations: list[str] = []
    supported: bool = False
    support_notes: Optional[str] = None


class AnswerQuality(BaseModel):
    """Quality metrics for the generated answer."""

    confidence: str
    distinct_sources_used: int
    citation_coverage: float
    unsupported_claims: int
    contradictions_detected: bool


class AskResponse(BaseModel):
    query: str
    results: list[SearchResult]
    sources: list[SourceDoc]
    chunks: list[Chunk]
    top_chunks: list[ScoredChunk]
    answer: Optional[str] = None
    source_map: list[SourceRef] = []
    answer_error: Optional[str] = None
    answer_claims: list[AnswerClaim] = []
    quality: Optional[AnswerQuality] = None
