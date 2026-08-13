"""Graph traversal retriever (RETRIEVAL-002) — the second step of GraphRAG's
hybrid retrieval. Takes RETRIEVAL-001's SeedResult and expands it N hops
outward in Neo4j, returning the raw subgraph RETRIEVAL-003's hybrid scorer
will rank.

Seed resolution: EntitySeed.node_id is already a Neo4j elementId (see
vector_retriever.py), used directly. ChunkSeed/SeedResult.paper_ids are
Postgres paper_id strings (the Paper node's MERGE key, not its elementId —
graph_writer.write_paper), so those need one lookup to become elementIds
before they can seed a traversal. Both seed types land in the same elementId
space, so the actual traversal query doesn't need to care which kind a given
seed came from.

Relationship-type filtering is done the same way label filtering is done
elsewhere in this codebase (queries.py's own docstring, graph_writer.py's
_MERGE_NODE/_CREATE_REL templates): Cypher can't parameterize a type/label
inside a pattern, so it's interpolated — safe here because relationship_types
is checked against _KNOWN_REL_TYPES (the fixed set graph_writer.py/
pipeline.py ever actually write) before it touches the query string, same as
those templates only ever interpolate our own fixed label set, never
caller-controlled text.

Node-type filtering, by contrast, is done in Python after the fetch, not in
Cypher: it only prunes newly-discovered nodes (seeds always survive the
filter — they were already judged relevant by RETRIEVAL-001's vector
search), which is simpler to express as a post-filter than as another
interpolated clause stacked on top of the hop/type one.

Capping at max_nodes: the Cypher query already orders rows by edge
confidence (AUTHORED_BY has none, so it naturally sorts last) and caps the
row count fetched (_ROW_FETCH_LIMIT) so a pathological graph can't make the
query itself slow. The final 200-node cap is then applied greedily in
Python over that pre-sorted list: keep an edge if both its endpoints are
already in or it still fits under the budget, skip it otherwise — an edge
later in the (lower-confidence) list can still be kept if it only touches
nodes already admitted, which is exactly "take highest-confidence edges
first" without needing a second Cypher round-trip.
"""

from dataclasses import dataclass

from src.config import settings
from src.graph.connection import get_driver
from src.services.retrieval.vector_retriever import SeedResult

# The only relationship types graph_writer.py/pipeline.py ever actually
# write (AUTHORED_BY: write_authors; REPORTS_RESULT: synthesized from claims;
# the rest: relation_extractor's kept _INTRA_TYPES/_CROSS_TYPES, minus
# pipeline.py's _SKIPPED_RELATION_TYPES which are never written). Used to
# validate relationship_types before it's interpolated into a query string.
_KNOWN_REL_TYPES = {
    "AUTHORED_BY",
    "USES_METHOD",
    "EVALUATES_ON",
    "INTRODUCES",
    "REPORTS_RESULT",
    "EXTENDS",
    "OUTPERFORMS",
}
_MAX_NODES = 200  # ticket-literal cap
_ROW_FETCH_LIMIT = 2000  # bounds query cost on a pathologically dense graph

_TRAVERSE = """
MATCH (seed)-[rel{type_filter}*1..{hops}]-(n)
WHERE elementId(seed) IN $seed_ids
UNWIND rel AS r
WITH DISTINCT r, startNode(r) AS a, endNode(r) AS b
RETURN elementId(a) AS a_id, labels(a) AS a_labels, properties(a) AS a_props,
       elementId(b) AS b_id, labels(b) AS b_labels, properties(b) AS b_props,
       type(r) AS rel_type, properties(r) AS rel_props
ORDER BY coalesce(r.confidence, 0.0) DESC
LIMIT $row_limit
"""
_PAPER_ELEMENT_IDS = "MATCH (p:Paper) WHERE p.paper_id IN $paper_ids RETURN elementId(p) AS id"


@dataclass
class GraphNode:
    node_id: str  # elementId
    labels: list[str]
    properties: dict


@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    rel_type: str
    properties: dict


@dataclass
class Subgraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


async def retrieve_subgraph(
    seeds: SeedResult,
    hops: int | None = None,
    relationship_types: list[str] | None = None,
    entity_types: list[str] | None = None,
    max_nodes: int = _MAX_NODES,
) -> Subgraph:
    hops = max(1, min(4, hops or settings.graph_traversal_hops))

    type_filter = ""
    if relationship_types is not None:
        valid_types = _KNOWN_REL_TYPES & set(relationship_types)
        if not valid_types:  # every requested type was unknown/invalid — match nothing
            return Subgraph(nodes=[], edges=[])
        type_filter = ":" + "|".join(sorted(valid_types))

    seed_ids = await _resolve_seed_ids(seeds)
    if not seed_ids:
        return Subgraph(nodes=[], edges=[])

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            _TRAVERSE.format(type_filter=type_filter, hops=hops),
            seed_ids=seed_ids,
            row_limit=_ROW_FETCH_LIMIT,
        )
        rows = [record async for record in result]

    return _cap_subgraph(rows, set(seed_ids), entity_types, max_nodes)


async def _resolve_seed_ids(seeds: SeedResult) -> list[str]:
    """Entity seeds already carry an elementId. Paper seeds carry a
    Postgres paper_id and need one lookup to become the Paper node's
    elementId."""
    seed_ids = [e.node_id for e in seeds.entities]
    if not seeds.paper_ids:
        return seed_ids

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(_PAPER_ELEMENT_IDS, paper_ids=list(seeds.paper_ids))
        seed_ids += [record["id"] async for record in result]
    return seed_ids


def _cap_subgraph(
    rows, seed_ids: set[str], entity_types: list[str] | None, max_nodes: int
) -> Subgraph:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for row in rows:
        a_id, b_id = row["a_id"], row["b_id"]
        if entity_types is not None:
            if a_id not in seed_ids and not set(row["a_labels"]) & set(entity_types):
                continue
            if b_id not in seed_ids and not set(row["b_labels"]) & set(entity_types):
                continue

        new_ids = {nid for nid in (a_id, b_id) if nid not in nodes}
        if new_ids and len(nodes) + len(new_ids) > max_nodes:
            continue  # would exceed the cap and doesn't already fit

        nodes.setdefault(a_id, GraphNode(a_id, row["a_labels"], _clean_props(row["a_props"])))
        nodes.setdefault(b_id, GraphNode(b_id, row["b_labels"], _clean_props(row["b_props"])))
        edges.append(GraphEdge(a_id, b_id, row["rel_type"], dict(row["rel_props"])))

    return Subgraph(nodes=list(nodes.values()), edges=edges)


def _clean_props(props: dict) -> dict:
    """Strips the embedding vector — dead weight in a subgraph result, never
    something a caller wants to see, unlike everything else on the node."""
    return {k: v for k, v in props.items() if k != "embedding"}
