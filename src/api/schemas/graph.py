"""Request/response models for GET /graph/* (GRAPH-001)."""

from pydantic import BaseModel

from src.api.schemas.query import SubgraphEdgeSchema


class GraphOverview(BaseModel):
    total_nodes: int
    total_edges: int
    node_counts: dict[str, int]
    edge_counts: dict[str, int]


class GraphNodeSchema(BaseModel):
    id: str
    labels: list[str]
    properties: dict
    # Type-appropriate size metric for GRAPH-002's node sizing (04_FRONTEND_
    # SPECIFICATION.md §4.3's "size based on citation/usage/evaluation/paper
    # count"): Paper uses total relationship degree as a proxy — the spec's
    # literal "citation count" needs a CITES relationship that's never
    # actually written (relation_extractor.py extracts it as a candidate
    # type, pipeline.py never persists it — see graph_retriever.py's
    # _KNOWN_REL_TYPES). Method uses USES_METHOD count, Dataset uses
    # EVALUATES_ON count, Author uses AUTHORED_BY count. One generic field
    # name across all types (not 4 differently-named ones) — GRAPH-002 only
    # ever needs one number per node to size it, and Claim/Metric simply
    # get None (spec gives Claim a fixed size, doesn't define one for Metric).
    usage_count: int | None = None


class GraphSubgraphResponse(BaseModel):
    nodes: list[GraphNodeSchema]
    edges: list[SubgraphEdgeSchema]


class RelatedEntity(BaseModel):
    rel_type: str
    direction: str  # "outgoing" | "incoming", from this entity's own side
    id: str
    labels: list[str]
    name: str | None
    properties: dict


class EntityDetailResponse(BaseModel):
    id: str
    labels: list[str]
    properties: dict
    usage_count: int | None = None
    relationships: list[RelatedEntity]


class SearchResultItem(BaseModel):
    id: str
    labels: list[str]
    properties: dict
    name: str | None
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
