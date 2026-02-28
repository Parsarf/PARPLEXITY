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


class AskResponse(BaseModel):
    query: str
    results: list[SearchResult]
    sources: list[SourceDoc]
    chunks: list[Chunk]
    top_chunks: list[ScoredChunk]
    answer: Optional[str] = None
    source_map: list[SourceRef] = []
    answer_error: Optional[str] = None
