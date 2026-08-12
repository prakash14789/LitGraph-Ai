"""POST /query/vanilla — the vanilla RAG baseline endpoint (INGEST-005).

POST /query and POST /query/compare (GraphRAG, and GraphRAG-vs-vanilla) land
with RETRIEVAL-005/006 — not built yet.
"""

import time
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.query import SourceChunk, VanillaQueryRequest, VanillaQueryResponse
from src.models.paper import Paper
from src.services.vanilla_rag.generator import generate_answer
from src.services.vanilla_rag.retriever import retrieve

router = APIRouter()


@router.post("/query/vanilla", response_model=VanillaQueryResponse)
async def query_vanilla(
    request: VanillaQueryRequest, db: AsyncSession = Depends(get_db)
) -> VanillaQueryResponse:
    start = time.monotonic()

    chunks = retrieve(request.query, top_k=request.top_k)
    answer = generate_answer(request.query, chunks)
    titles = await _paper_titles(db, {c.paper_id for c in chunks})

    sources = [
        SourceChunk(
            paper_id=c.paper_id,
            paper_title=titles.get(c.paper_id),
            section_name=c.section_name,
            page_number=c.page_number,
            score=c.score,
            text=c.text,
        )
        for c in chunks
    ]

    return VanillaQueryResponse(
        answer=answer,
        sources=sources,
        latency_ms=int((time.monotonic() - start) * 1000),
    )


async def _paper_titles(db: AsyncSession, paper_ids: set[str]) -> dict[str, str]:
    valid_ids = [uuid.UUID(pid) for pid in paper_ids if pid]
    if not valid_ids:
        return {}
    result = await db.execute(select(Paper.id, Paper.title).where(Paper.id.in_(valid_ids)))
    return {str(pid): title for pid, title in result.all()}
