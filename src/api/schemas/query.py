"""Request/response models for POST /query/vanilla."""

from pydantic import BaseModel


class VanillaQueryRequest(BaseModel):
    query: str
    top_k: int | None = None  # defaults to settings.vector_top_k if omitted


class SourceChunk(BaseModel):
    paper_id: str
    paper_title: str | None
    section_name: str
    page_number: int | None
    score: float
    text: str


class VanillaQueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]  # index+1 matches the [n] citations in `answer`
    latency_ms: int
