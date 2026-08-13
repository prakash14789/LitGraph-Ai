"""POST /query/vanilla — the vanilla RAG baseline endpoint (INGEST-005).
POST /query — the GraphRAG endpoint (RETRIEVAL-005), built on top of the
retrieve_seeds -> retrieve_subgraph -> score_subgraph -> build_context chain
RETRIEVAL-001 through -004 already built.

POST /query/compare (GraphRAG vs vanilla, side by side) lands with
RETRIEVAL-006 — not built yet.
"""

import time
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.query import (
    Citation,
    QueryRequest,
    QueryResponse,
    RetrievalStats,
    RetrievedSubgraphSchema,
    SourceChunk,
    SubgraphEdgeSchema,
    SubgraphNodeSchema,
    VanillaQueryRequest,
    VanillaQueryResponse,
)
from src.models.paper import Paper
from src.services.generation.generator import generate_answer as generate_graphrag_answer
from src.services.retrieval.context_builder import build_context
from src.services.retrieval.graph_retriever import retrieve_subgraph
from src.services.retrieval.hybrid_scorer import RankedSubgraph, score_subgraph
from src.services.retrieval.vector_retriever import SeedResult, retrieve_seeds
from src.services.vanilla_rag.generator import generate_answer
from src.services.vanilla_rag.retriever import retrieve

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query_graphrag(
    request: QueryRequest, db: AsyncSession = Depends(get_db)
) -> QueryResponse:
    start = time.monotonic()

    seeds = retrieve_seeds(request.query)
    subgraph = await retrieve_subgraph(seeds, hops=request.hops)
    ranked = score_subgraph(subgraph, seeds, top_k=request.top_k)
    context = build_context(ranked, seeds)
    answer = generate_graphrag_answer(request.query, context)
    citations = await _build_citations(db, ranked, seeds)

    return QueryResponse(
        answer=answer,
        citations=citations,
        retrieved_subgraph=_to_subgraph_schema(ranked),
        retrieval_stats=RetrievalStats(
            entity_seeds=len(seeds.entities),
            chunk_seeds=len(seeds.chunks),
            graph_nodes=len(subgraph.nodes),
            ranked_nodes=len(ranked.nodes),
            context_tokens=context.token_count,
            context_truncated=context.truncated,
            latency_ms=int((time.monotonic() - start) * 1000),
        ),
    )


def _to_subgraph_schema(ranked: RankedSubgraph) -> RetrievedSubgraphSchema:
    return RetrievedSubgraphSchema(
        nodes=[
            SubgraphNodeSchema(
                id=s.node.node_id,
                labels=s.node.labels,
                properties=s.node.properties,
                score=s.score,
                vector_similarity=s.vector_similarity,
                graph_distance=s.graph_distance,
                avg_edge_confidence=s.avg_edge_confidence,
            )
            for s in ranked.nodes
        ],
        edges=[
            SubgraphEdgeSchema(
                source=e.source_id, target=e.target_id, rel_type=e.rel_type, properties=e.properties
            )
            for e in ranked.edges
        ],
    )


async def _build_citations(
    db: AsyncSession, ranked: RankedSubgraph, seeds: SeedResult
) -> list[Citation]:
    """Citations come from the graph data itself — every Paper node that made
    the ranked subgraph, plus (title resolved via Postgres) any paper that
    only surfaced through a chunk match and never made the ranked top-K —
    not parsed out of the LLM's free-form answer, which would be fragile and
    can't guarantee "citations match actual papers in the collection"."""
    citations: dict[str, Citation] = {}
    for scored in ranked.nodes:
        if "Paper" in scored.node.labels:
            paper_id = scored.node.properties.get("paper_id")
            if paper_id:
                citations[paper_id] = Citation(
                    paper_id=paper_id,
                    title=scored.node.properties.get("title"),
                    year=scored.node.properties.get("year"),
                )

    missing = [pid for pid in seeds.paper_ids if pid and pid not in citations]
    if missing:
        titles = await _paper_titles(db, set(missing))
        for paper_id in missing:
            citations[paper_id] = Citation(paper_id=paper_id, title=titles.get(paper_id), year=None)

    return list(citations.values())


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
