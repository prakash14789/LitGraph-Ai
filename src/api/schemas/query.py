"""Request/response models for POST /query/vanilla and POST /query (GraphRAG,
RETRIEVAL-005)."""

import uuid

from pydantic import BaseModel

from src.models.query_log import CompareVerdict


class VanillaQueryRequest(BaseModel):
    query: str
    top_k: int | None = None  # defaults to settings.vector_top_k if omitted
    collection_id: uuid.UUID | None = None  # POLISH-005b — omit for global search


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
    context_tokens: int  # COMPARE-001 — same cl100k_base count QueryResponse's
    # retrieval_stats.context_tokens uses, so the two systems' stats are
    # actually comparable on the Compare page, not vanilla missing the field


class QueryRequest(BaseModel):
    query: str
    top_k: int | None = None  # ranked nodes to keep — defaults to settings.context_max_nodes
    hops: int | None = None  # graph traversal depth — defaults to settings.graph_traversal_hops
    collection_id: uuid.UUID | None = None  # POLISH-005b — omit for global search


class Citation(BaseModel):
    paper_id: str
    title: str | None
    year: int | None


class SubgraphNodeSchema(BaseModel):
    id: str
    labels: list[str]
    properties: dict
    score: float
    vector_similarity: float
    graph_distance: int | None
    avg_edge_confidence: float


class SubgraphEdgeSchema(BaseModel):
    source: str
    target: str
    rel_type: str
    properties: dict


class RetrievedSubgraphSchema(BaseModel):
    nodes: list[SubgraphNodeSchema]
    edges: list[SubgraphEdgeSchema]


class RetrievalStats(BaseModel):
    entity_seeds: int
    chunk_seeds: int
    graph_nodes: int  # size of the subgraph before RETRIEVAL-003's top_k ranking cut it down
    ranked_nodes: int  # == len(retrieved_subgraph.nodes)
    context_tokens: int
    context_truncated: bool
    latency_ms: int


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieved_subgraph: RetrievedSubgraphSchema
    retrieval_stats: RetrievalStats


class CompareQueryRequest(BaseModel):
    query: str
    top_k: int | None = None  # graphrag ranked-node top_k
    hops: int | None = None  # graphrag traversal depth
    vanilla_top_k: int | None = None  # vanilla chunk top_k
    collection_id: uuid.UUID | None = None  # POLISH-005b — scopes both sides identically


class CompareQueryResponse(BaseModel):
    graphrag: QueryResponse
    vanilla: VanillaQueryResponse
    total_latency_ms: int  # ~= max(graphrag.retrieval_stats.latency_ms, vanilla.latency_ms)
    # + small overhead, since both pipelines run concurrently via asyncio.gather
    query_log_id: str  # COMPARE-002 — id of the query_log row this comparison was
    # persisted to, so the frontend can attach a vote to it via POST
    # /query/compare/{query_log_id}/vote


class CompareVoteRequest(BaseModel):
    verdict: CompareVerdict
