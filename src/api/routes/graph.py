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
    WHOLE_GRAPH_EDGES,
    WHOLE_GRAPH_NODES,
)
from src.services.retrieval.graph_retriever import (
    resolve_collection_paper_seed_ids,
    retrieve_subgraph,
)
from src.services.retrieval.vector_retriever import EntitySeed, SeedResult

router = APIRouter()

# GRAPH-003: "full graph loads on page visit" cap — conservative relative to
# GRAPH-002's own "no overlap up to 200 / smooth up to 500" targets, since a
# whole-graph snapshot (no relevance ranking to trim by) is the one path
# most likely to actually hit the ceiling in practice.
_MAX_FULL_GRAPH_NODES = 150

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
async def graph_overview(
    collection_id: str | None = Query(
        None, description="POLISH-005b — scope counts to one collection"
    ),
) -> GraphOverview:
    if collection_id is not None:
        # Same seeded-traversal path /graph/subgraph uses when scoped — counts
        # what that endpoint would actually show, not a separate Cypher
        # aggregate that could drift out of sync with it.
        node_rows, edge_rows = await _collection_graph_rows(collection_id)
        node_counts: dict[str, int] = {}
        for row in node_rows:
            label = row["labels"][0] if row["labels"] else None
            if label:
                node_counts[label] = node_counts.get(label, 0) + 1
        edge_counts: dict[str, int] = {}
        for row in edge_rows:
            edge_counts[row["rel_type"]] = edge_counts.get(row["rel_type"], 0) + 1
        return GraphOverview(
            total_nodes=len(node_rows),
            total_edges=len(edge_rows),
            node_counts=node_counts,
            edge_counts=edge_counts,
        )

    driver = get_driver()
    async with driver.session() as session:
        node_result = await session.run(NODE_COUNTS_BY_LABEL)
        node_rows_raw = [r async for r in node_result]
        edge_result = await session.run(EDGE_COUNTS_BY_TYPE)
        edge_rows_raw = [r async for r in edge_result]

    node_counts = {r["label"]: r["count"] for r in node_rows_raw if r["label"]}
    edge_counts = {r["rel_type"]: r["count"] for r in edge_rows_raw}
    return GraphOverview(
        total_nodes=sum(node_counts.values()),
        total_edges=sum(edge_counts.values()),
        node_counts=node_counts,
        edge_counts=edge_counts,
    )


@router.get("/graph/subgraph", response_model=GraphSubgraphResponse)
async def graph_subgraph(
    entity_id: str | None = Query(
        None, description="Neo4j elementId to expand from; omit for a capped whole-graph snapshot"
    ),
    hops: int = Query(2, ge=1, le=4),
    collection_id: str | None = Query(None, description="POLISH-005b — scope to one collection"),
) -> GraphSubgraphResponse:
    if entity_id is None and collection_id is not None:
        # GRAPH-003's whole-graph snapshot, scoped: seed from every Paper in
        # the collection instead of an unscoped MATCH (n), same
        # retrieve_subgraph traversal + collection_id post-filter the
        # entity_id path below already uses (graph_retriever.py's own
        # docstring explains why the filter is post-traversal, not a Cypher
        # WHERE — entity seeds are collection-agnostic by design).
        node_rows, edge_rows = await _collection_graph_rows(collection_id)
    elif entity_id is None:
        # GRAPH-003: "full graph loads on page visit" — the Explorer's
        # default view, no seed entity to expand from.
        node_rows, edge_rows = await _whole_graph_rows()
    else:
        # Reuses RETRIEVAL-002's traversal/capping instead of a second
        # implementation — a single-entity seed is exactly retrieve_subgraph's
        # existing EntitySeed shape, entity_type/canonical_name/score unused
        # by its own seed-resolution path (only node_id is read).
        seeds = SeedResult(
            entities=[EntitySeed(node_id=entity_id, entity_type="", canonical_name="", score=1.0)],
            chunks=[],
            paper_ids=[],
        )
        subgraph = await retrieve_subgraph(seeds, hops=hops, collection_id=collection_id)
        if not subgraph.nodes:
            # Also hits for a real entity with zero relationships (a state
            # the write path never actually produces — every entity gets at
            # least one edge back to the paper that introduced it) — not
            # worth a second existence-check query for a case that
            # shouldn't occur.
            raise HTTPException(404, "entity not found")
        node_rows = [
            {"id": n.node_id, "labels": n.labels, "properties": n.properties}
            for n in subgraph.nodes
        ]
        edge_rows = [
            {
                "a_id": e.source_id,
                "b_id": e.target_id,
                "rel_type": e.rel_type,
                "rel_props": e.properties,
            }
            for e in subgraph.edges
        ]

    by_label: dict[str, list[str]] = {}
    for row in node_rows:
        by_label.setdefault(row["labels"][0], []).append(row["id"])
    counts = await _usage_counts(by_label)

    nodes = [
        GraphNodeSchema(
            id=row["id"],
            labels=row["labels"],
            properties=row["properties"],
            usage_count=counts.get(row["id"]),
        )
        for row in node_rows
    ]
    edges = [
        SubgraphEdgeSchema(
            source=row["a_id"],
            target=row["b_id"],
            rel_type=row["rel_type"],
            properties=row["rel_props"],
        )
        for row in edge_rows
    ]
    return GraphSubgraphResponse(nodes=nodes, edges=edges)


async def _whole_graph_rows() -> tuple[list[dict], list[dict]]:
    driver = get_driver()
    async with driver.session() as session:
        node_result = await session.run(WHOLE_GRAPH_NODES, limit=_MAX_FULL_GRAPH_NODES)
        node_rows_raw = [r async for r in node_result]
        ids = [r["id"] for r in node_rows_raw]
        edge_result = await session.run(WHOLE_GRAPH_EDGES, ids=ids)
        edge_rows_raw = [r async for r in edge_result]

    node_rows = [
        {
            "id": r["id"],
            "labels": r["labels"],
            "properties": {k: v for k, v in dict(r["properties"]).items() if k != "embedding"},
        }
        for r in node_rows_raw
    ]
    edge_rows = [
        {
            "a_id": r["a_id"],
            "b_id": r["b_id"],
            "rel_type": r["rel_type"],
            "rel_props": dict(r["rel_props"]),
        }
        for r in edge_rows_raw
    ]
    return node_rows, edge_rows


async def _collection_graph_rows(collection_id: str) -> tuple[list[dict], list[dict]]:
    """Same row shape as _whole_graph_rows() (plain dicts, not GraphNode/
    GraphEdge) so both feed the same downstream node/edge-building code in
    graph_subgraph(). Seeds from every Paper in the collection and reuses
    retrieve_subgraph's own 2-hop traversal + collection_id post-filter —
    embeddings are already stripped by graph_retriever.py's _clean_props,
    same as the unscoped whole-graph path strips them itself."""
    seed_ids = await resolve_collection_paper_seed_ids(collection_id)
    if not seed_ids:
        return [], []
    seeds = SeedResult(
        entities=[
            EntitySeed(node_id=sid, entity_type="", canonical_name="", score=1.0)
            for sid in seed_ids
        ],
        chunks=[],
        paper_ids=[],
    )
    subgraph = await retrieve_subgraph(
        seeds, hops=2, collection_id=collection_id, max_nodes=_MAX_FULL_GRAPH_NODES
    )
    node_rows = [
        {"id": n.node_id, "labels": n.labels, "properties": n.properties} for n in subgraph.nodes
    ]
    edge_rows = [
        {
            "a_id": e.source_id,
            "b_id": e.target_id,
            "rel_type": e.rel_type,
            "rel_props": e.properties,
        }
        for e in subgraph.edges
    ]
    return node_rows, edge_rows


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


# Takes pre-grouped {label: [ids]} rather than a list of node objects —
# GRAPH-003's whole-graph path has raw Cypher rows, not graph_retriever's
# GraphNode dataclass, so grouping is the call site's job, not this one's.
async def _usage_counts(ids_by_label: dict[str, list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    driver = get_driver()
    async with driver.session() as session:
        for label, ids in ids_by_label.items():
            query = _USAGE_COUNT_QUERY_BY_LABEL.get(label)
            if not query:
                continue
            result = await session.run(query, ids=ids)
            async for r in result:
                counts[r["id"]] = r["count"]
    return counts
