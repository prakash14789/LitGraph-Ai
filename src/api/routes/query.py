"""POST /query/vanilla — the vanilla RAG baseline endpoint (INGEST-005).
POST /query — the GraphRAG endpoint (RETRIEVAL-005), built on top of the
retrieve_seeds -> retrieve_subgraph -> score_subgraph -> build_context chain
RETRIEVAL-001 through -004 already built.
POST /query/compare — built RETRIEVAL-006, runs both of the above for the
same query and returns them side by side.
POST /query/compare/{query_log_id}/vote — COMPARE-002, records which of the
two compared answers the user thought was better.

Both query_graphrag and query_vanilla call their LLM generator through
`asyncio.to_thread` rather than directly — llm_client.complete() is a
blocking sync call (the OpenAI SDK's sync client), and calling it straight
from an `async def` blocks the whole event loop for the call's full
duration. That was invisible with one request in flight at a time, but
/query/compare runs both pipelines concurrently via asyncio.gather(), and
without to_thread the two LLM calls (each the dominant cost, seconds vs
tens of ms for the rest of the pipeline) would just serialize back-to-back
on the same thread — silently failing the ticket's own "latency =
max(graphrag_time, vanilla_time), not the sum" acceptance criterion. Only
the LLM call is wrapped, not the faster embed()/query_similar() calls —
those are fast enough that the extra thread-hop isn't worth it.
"""

import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.query import (
    Citation,
    CompareQueryRequest,
    CompareQueryResponse,
    CompareVoteRequest,
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
from src.db import AsyncSessionLocal
from src.models.paper import Paper
from src.models.query_log import QueryLog
from src.repositories import query_log_repository
from src.services.generation.generator import generate_answer as generate_graphrag_answer
from src.services.retrieval.context_builder import build_context
from src.services.retrieval.graph_retriever import retrieve_subgraph
from src.services.retrieval.hybrid_scorer import RankedSubgraph, score_subgraph
from src.services.retrieval.vector_retriever import SeedResult, retrieve_seeds
from src.services.vanilla_rag.generator import generate_answer
from src.services.vanilla_rag.retriever import retrieve

router = APIRouter()


@router.post("/query/compare", response_model=CompareQueryResponse)
async def query_compare(
    request: CompareQueryRequest, db: AsyncSession = Depends(get_db)
) -> CompareQueryResponse:
    """Each pipeline gets its own AsyncSession — SQLAlchemy's AsyncSession
    isn't safe for concurrent use from two tasks at once, and query_graphrag/
    query_vanilla are called directly as plain async functions here (not
    through FastAPI's routing), so a single Depends(get_db) session isn't
    available or appropriate anyway. The `db` session here is only used
    afterward, to persist the query_log row COMPARE-002's vote endpoint
    attaches to."""
    start = time.monotonic()
    async with AsyncSessionLocal() as graphrag_db, AsyncSessionLocal() as vanilla_db:
        graphrag_result, vanilla_result = await asyncio.gather(
            query_graphrag(
                QueryRequest(
                    query=request.query,
                    top_k=request.top_k,
                    hops=request.hops,
                    collection_id=request.collection_id,
                ),
                graphrag_db,
            ),
            query_vanilla(
                VanillaQueryRequest(
                    query=request.query,
                    top_k=request.vanilla_top_k,
                    collection_id=request.collection_id,
                ),
                vanilla_db,
            ),
        )
    total_latency_ms = int((time.monotonic() - start) * 1000)

    # Not query_log_repository.create() — its session.refresh() is a second
    # DB round-trip only needed for server-generated columns. `id` here is a
    # client-side uuid4 default, already set on the instance after flush(),
    # so skipping refresh halves the latency this persistence step adds to
    # the response (mattered enough to trip this file's own parallelism
    # timing test — see test_compare_runs_both_pipelines_in_parallel).
    log = QueryLog(
        query_text=request.query,
        graphrag_answer=graphrag_result.answer,
        vanilla_answer=vanilla_result.answer,
        latency_ms=total_latency_ms,
    )
    db.add(log)
    await db.flush()

    return CompareQueryResponse(
        graphrag=graphrag_result,
        vanilla=vanilla_result,
        total_latency_ms=total_latency_ms,
        query_log_id=str(log.id),
    )


@router.post("/query/compare/{query_log_id}/vote", status_code=204)
async def vote_compare(
    query_log_id: uuid.UUID, request: CompareVoteRequest, db: AsyncSession = Depends(get_db)
) -> None:
    """COMPARE-002. A plain UPDATE, not append-only — re-voting on the same
    query_log_id just overwrites the previous verdict, which is what "user
    can change vote within session" means: the frontend re-POSTs on click,
    there's no separate session/vote-id to track."""
    log = await query_log_repository.get_by_id(db, query_log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="query_log not found")
    log.compare_verdict = request.verdict


@router.post("/query", response_model=QueryResponse)
async def query_graphrag(
    request: QueryRequest, db: AsyncSession = Depends(get_db)
) -> QueryResponse:
    start = time.monotonic()

    collection_id = str(request.collection_id) if request.collection_id else None
    seeds = retrieve_seeds(request.query, collection_id=collection_id)
    subgraph = await retrieve_subgraph(seeds, hops=request.hops, collection_id=collection_id)
    ranked = score_subgraph(subgraph, seeds, top_k=request.top_k)
    context = build_context(ranked, seeds)
    answer = await asyncio.to_thread(generate_graphrag_answer, request.query, context)
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

    collection_id = str(request.collection_id) if request.collection_id else None
    chunks = retrieve(request.query, top_k=request.top_k, collection_id=collection_id)
    generated = await asyncio.to_thread(generate_answer, request.query, chunks)
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
        answer=generated.text,
        sources=sources,
        latency_ms=int((time.monotonic() - start) * 1000),
        context_tokens=generated.context_tokens,
    )


async def _paper_titles(db: AsyncSession, paper_ids: set[str]) -> dict[str, str]:
    valid_ids = [uuid.UUID(pid) for pid in paper_ids if pid]
    if not valid_ids:
        return {}
    result = await db.execute(select(Paper.id, Paper.title).where(Paper.id.in_(valid_ids)))
    return {str(pid): title for pid, title in result.all()}
