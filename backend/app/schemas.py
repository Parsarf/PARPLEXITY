from typing import Optional

from pydantic import BaseModel, HttpUrl


class AskRequest(BaseModel):
    query: str
    num_results: int = 8


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: Optional[str] = None


class CitationFormats(BaseModel):
    """Formatted citations in multiple academic styles."""

    apa: str = ""
    mla: str = ""
    chicago: str = ""
    bibtex: str = ""
    missing_fields: list[str] = []


class SourceDoc(BaseModel):
    """A source with fetched and extracted main text (or error)."""

    title: str
    url: HttpUrl
    snippet: Optional[str] = None
    text: str = ""
    error: Optional[str] = None
    is_pdf: bool = False
    pdf_metadata: Optional[dict] = None
    source_type: str = "unknown"
    source_type_confidence: str = "low"
    source_type_signals: list[str] = []
    authority_score: float = 1.0
    authority_breakdown: Optional[dict] = None
    citations: Optional["CitationFormats"] = None


class Chunk(BaseModel):
    """A chunk of text from a source, for retrieval/context."""

    chunk_id: str
    source_url: HttpUrl
    source_title: str
    chunk_index: int
    text: str
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    section_heading: Optional[str] = None
    page_number: Optional[int] = None


class ScoredChunk(BaseModel):
    """A chunk with a retrieval score (top evidence for answer generation)."""

    chunk_id: str
    source_url: HttpUrl
    source_title: str
    chunk_index: int
    text: str
    score: float
    authority_score: float = 1.0


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


class EvidenceBlock(BaseModel):
    """One evidence block: claim, exact quote from source, verification and page (PDF)."""

    claim: str
    source_id: str
    quote: Optional[str] = None
    quote_context: Optional[str] = None
    quote_verified: bool = False
    quote_match_score: float = 0.0
    quote_match_type: str = "no_quote"
    page_number: Optional[int] = None


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
    evidence_blocks: list[EvidenceBlock] = []
    query_id: Optional[str] = None


class ExportResponse(BaseModel):
    """Export response for citations from a previous query."""

    query_id: str
    query: str
    format: str
    sources_count: int
    content: str
    missing_metadata_sources: list[str]


class UploadResponse(BaseModel):
    filename: str
    title: str
    authors: list[str]
    doi: Optional[str] = None
    abstract: str
    sections_found: list[str]
    page_count: int
    chunks_generated: int
    source_id: str
