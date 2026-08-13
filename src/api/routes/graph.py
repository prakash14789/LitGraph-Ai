"""GET /graph/overview, GET /graph/subgraph, GET /graph/entity/{id},
GET /graph/search (GRAPH-001)."""

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas.graph import (
    EntityDetailResponse,
    GraphNodeSchema,
    GraphOverview,
    GraphSubgraphResponse,
    RelatedEntity,
    SearchResponse,
    SearchResultItem,
)
from src.api.schemas.query import SubgraphEdgeSchema
from src.graph.connection import get_driver
from src.graph.queries import (
    EDGE_COUNTS_BY_TYPE,
    ENTITY_BY_ID,
    ENTITY_RELATIONSHIPS,
    NODE_COUNTS_BY_LABEL,
)
from src.services.retrieval.graph_retriever import GraphNode, retrieve_subgraph
from src.services.retrieval.vector_retriever import EntitySeed, SeedResult

router = APIRouter()

# Fulltext index per searchable label (src/graph/schema.py) — Metric has
# none, same scope trim as usage_count's node-sizing (04_FRONTEND_
# SPECIFICATION.md §4.3 doesn't define a size rule for it either).
_FULLTEXT_INDEX_BY_LABEL = {
    "Paper": "paper_search",
    "Method": "method_search",
    "Dataset": "dataset_search",
    "Author": "author_search",
    "Claim": "claim_search",
}

# Per-label usage-count query — see GraphNodeSchema.usage_count's docstring
# for why Paper's is a degree proxy rather than a real citation count.
_USAGE_COUNT_QUERY_BY_LABEL = {
    "Method": (
        "MATCH (m:Method)<-[:USES_METHOD]-(p:Paper) WHERE elementId(m) IN $ids "
        "RETURN elementId(m) AS id, count(DISTINCT p) AS count"
    ),
    "Dataset": (
        "MATCH (d:Dataset)<-[:EVALUATES_ON]-(p:Paper) WHERE elementId(d) IN $ids "
        "RETURN elementId(d) AS id, count(DISTINCT p) AS count"
    ),
    "Author": (
        "MATCH (a:Author)<-[:AUTHORED_BY]-(p:Paper) WHERE elementId(a) IN $ids "
        "RETURN elementId(a) AS id, count(DISTINCT p) AS count"
    ),
    "Paper": (
        "MATCH (p:Paper) WHERE elementId(p) IN $ids "
        "OPTIONAL MATCH (p)-[r]-() RETURN elementId(p) AS id, count(r) AS count"
    ),
}


@router.get("/graph/overview", response_model=GraphOverview)
async def graph_overview() -> GraphOverview:
    driver = get_driver()
    async with driver.session() as session:
        node_result = await session.run(NODE_COUNTS_BY_LABEL)
        node_rows = [r async for r in node_result]
        edge_result = await session.run(EDGE_COUNTS_BY_TYPE)
        edge_rows = [r async for r in edge_result]

    node_counts = {r["label"]: r["count"] for r in node_rows if r["label"]}
    edge_counts = {r["rel_type"]: r["count"] for r in edge_rows}
    return GraphOverview(
        total_nodes=sum(node_counts.values()),
        total_edges=sum(edge_counts.values()),
        node_counts=node_counts,
        edge_counts=edge_counts,
    )


@router.get("/graph/subgraph", response_model=GraphSubgraphResponse)
async def graph_subgraph(
    entity_id: str = Query(..., description="Neo4j elementId to expand from"),
    hops: int = Query(2, ge=1, le=4),
) -> GraphSubgraphResponse:
    # Reuses RETRIEVAL-002's traversal/capping instead of a second
    # implementation — a single-entity seed is exactly retrieve_subgraph's
    # existing EntitySeed shape, entity_type/canonical_name/score unused by
    # its own seed-resolution path (only node_id is read).
    seeds = SeedResult(
        entities=[EntitySeed(node_id=entity_id, entity_type="", canonical_name="", score=1.0)],
        chunks=[],
        paper_ids=[],
    )
    subgraph = await retrieve_subgraph(seeds, hops=hops)
    if not subgraph.nodes:
        # Also hits for a real entity with zero relationships (a state the
        # write path never actually produces — every entity gets at least
        # one edge back to the paper that introduced it) — not worth a
        # second existence-check query for a case that shouldn't occur.
        raise HTTPException(404, "entity not found")

    counts = await _usage_counts(subgraph.nodes)
    nodes = [
        GraphNodeSchema(
            id=n.node_id,
            labels=n.labels,
            properties=n.properties,
            usage_count=counts.get(n.node_id),
        )
        for n in subgraph.nodes
    ]
    edges = [
        SubgraphEdgeSchema(
            source=e.source_id, target=e.target_id, rel_type=e.rel_type, properties=e.properties
        )
        for e in subgraph.edges
    ]
    return GraphSubgraphResponse(nodes=nodes, edges=edges)


@router.get("/graph/entity/{entity_id}", response_model=EntityDetailResponse)
async def graph_entity(entity_id: str) -> EntityDetailResponse:
    driver = get_driver()
    async with driver.session() as session:
        node_result = await session.run(ENTITY_BY_ID, id=entity_id)
        node_record = await node_result.single()
        if node_record is None:
            raise HTTPException(404, "entity not found")

        rel_result = await session.run(ENTITY_RELATIONSHIPS, id=entity_id)
        rel_rows = [r async for r in rel_result]

    label = node_record["labels"][0]
    query = _USAGE_COUNT_QUERY_BY_LABEL.get(label)
    usage_count = None
    if query:
        async with driver.session() as session:
            result = await session.run(query, ids=[entity_id])
            record = await result.single()
            usage_count = record["count"] if record else 0

    relationships = [
        RelatedEntity(
            rel_type=r["rel_type"],
            direction="outgoing" if r["from_self"] else "incoming",
            id=r["other_id"],
            labels=r["other_labels"],
            name=r["other_name"],
            properties={k: v for k, v in dict(r["properties"]).items() if k != "embedding"},
        )
        for r in rel_rows
    ]
    return EntityDetailResponse(
        id=node_record["id"],
        labels=node_record["labels"],
        properties={k: v for k, v in dict(node_record["properties"]).items() if k != "embedding"},
        usage_count=usage_count,
        relationships=relationships,
    )


@router.get("/graph/search", response_model=SearchResponse)
async def graph_search(
    q: str = Query(..., min_length=1),
    type: str | None = Query(None, description="Filter to one entity label"),
    limit: int = Query(20, ge=1, le=100),
) -> SearchResponse:
    if type is not None and type not in _FULLTEXT_INDEX_BY_LABEL:
        raise HTTPException(400, f"unknown entity type: {type}")
    labels = [type] if type else list(_FULLTEXT_INDEX_BY_LABEL)

    driver = get_driver()
    results: list[SearchResultItem] = []
    async with driver.session() as session:
        for label in labels:
            result = await session.run(
                "CALL db.index.fulltext.queryNodes($index_name, $q) YIELD node, score "
                "RETURN elementId(node) AS id, labels(node) AS labels, properties(node) AS properties, score "
                "LIMIT $limit",
                index_name=_FULLTEXT_INDEX_BY_LABEL[label],
                q=q,
                limit=limit,
            )
            async for r in result:
                props = {k: v for k, v in dict(r["properties"]).items() if k != "embedding"}
                results.append(
                    SearchResultItem(
                        id=r["id"],
                        labels=r["labels"],
                        properties=props,
                        name=props.get("canonical_name")
                        or props.get("name")
                        or props.get("title")
                        or props.get("text"),
                        score=r["score"],
                    )
                )

    results.sort(key=lambda r: r.score, reverse=True)
    return SearchResponse(results=results[:limit])


async def _usage_counts(nodes: list[GraphNode]) -> dict[str, int]:
    by_label: dict[str, list[str]] = {}
    for n in nodes:
        by_label.setdefault(n.labels[0], []).append(n.node_id)

    counts: dict[str, int] = {}
    driver = get_driver()
    async with driver.session() as session:
        for label, ids in by_label.items():
            query = _USAGE_COUNT_QUERY_BY_LABEL.get(label)
            if not query:
                continue
            result = await session.run(query, ids=ids)
            async for r in result:
                counts[r["id"]] = r["count"]
    return counts
