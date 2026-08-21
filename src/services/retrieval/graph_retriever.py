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
    "TRAINED_ON",
    "INTRODUCES",
    "DISTILLED_FROM",
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
_PAPER_ELEMENT_IDS_SCOPED = (
    "MATCH (p:Paper) WHERE p.paper_id IN $paper_ids AND p.collection_id = $collection_id "
    "RETURN elementId(p) AS id"
)


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
    seed_ids: list[str]  # resolved elementIds actually used to seed the traversal — RETRIEVAL-003
    # needs these back (as its BFS distance-0 anchors) without re-running the paper_id lookup itself


async def retrieve_subgraph(
    seeds: SeedResult,
    hops: int | None = None,
    relationship_types: list[str] | None = None,
    entity_types: list[str] | None = None,
    max_nodes: int = _MAX_NODES,
    collection_id: str | None = None,
) -> Subgraph:
    """collection_id (POLISH-005b) — post-filter, not a traversal-time Cypher
    clause: traversal starts from arbitrary entity seeds (Method/Dataset/...),
    which are collection-agnostic by design (see vector_retriever.py's own
    docstring), so there's no single collection to filter the MATCH by up
    front. Applied after the fact instead, see _filter_by_collection."""
    hops = max(1, min(4, hops or settings.graph_traversal_hops))
    seed_ids = await _resolve_seed_ids(seeds, collection_id)
    if not seed_ids:
        return Subgraph(nodes=[], edges=[], seed_ids=[])

    type_filter = ""
    if relationship_types is not None:
        valid_types = _KNOWN_REL_TYPES & set(relationship_types)
        if not valid_types:  # every requested type was unknown/invalid — match nothing
            return Subgraph(nodes=[], edges=[], seed_ids=seed_ids)
        type_filter = ":" + "|".join(sorted(valid_types))

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            _TRAVERSE.format(type_filter=type_filter, hops=hops),
            seed_ids=seed_ids,
            row_limit=_ROW_FETCH_LIMIT,
        )
        rows = [record async for record in result]

    # Live finding 2026-08-20: the 200-node cap used to apply BEFORE the
    # collection filter - out-of-collection nodes (reachable from a shared
    # entity, or from an out-of-collection paper_id that leaked into the
    # seed list, see vector_retriever.py's own fix) could consume cap
    # budget that genuinely in-collection nodes then lost out on, making a
    # scoped query's retrieval silently incomplete. Filter first, cap last,
    # so a trim only ever removes lower-confidence *in-scope* material.
    subgraph = _build_subgraph(rows, entity_types, seed_ids)
    if collection_id is not None:
        subgraph = _filter_by_collection(subgraph, collection_id)
    return _cap_nodes(subgraph, max_nodes)


async def resolve_collection_paper_seed_ids(collection_id: str) -> list[str]:
    """elementIds of every Paper node tagged with this collection_id — GRAPH-
    001/003's whole-graph snapshot uses these as traversal seeds instead of
    an unscoped MATCH (n) when a collection filter is active (see routes/
    graph.py), the same seed shape EntitySeed.node_id already is."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (p:Paper {collection_id: $collection_id}) RETURN elementId(p) AS id",
            collection_id=collection_id,
        )
        return [record["id"] async for record in result]


def _filter_by_collection(subgraph: Subgraph, collection_id: str) -> Subgraph:
    """Drops every Paper node whose collection_id doesn't match (untagged
    papers included — "scoped to collection A" means only A, not A-plus-
    ungrouped), then drops edges touching a dropped Paper, then drops any
    non-Paper node left with zero edges. A shared entity (Method/Dataset/...,
    deliberately never tagged — see this module's/vector_retriever.py's own
    docstrings) survives exactly when it still has at least one edge to an
    in-collection paper, which is POLISH-005b's own recommended shared-
    entity behavior (decision (a): collection-agnostic, provenance-scoped)
    falling out of a plain graph prune rather than needing its own rule.

    Claim nodes get the same treatment, explicitly — live finding
    2026-08-20: unlike Method/Dataset (only ever reachable *through* a
    Paper edge, so the connectivity prune above already catches them),
    a Claim can independently be a traversal seed in its own right (it's
    embedded in Chroma same as any named entity — see graph_writer.py's
    write_claim), so it can survive with an edge to some *other* node
    while its own source_paper_id points at an out-of-collection paper —
    a different collection's claim text leaking straight into a scoped
    query's context. Checked against the source_paper_id *property*
    (a Postgres paper_id, the Paper node's own MERGE key), not an
    elementId — the two id spaces are different and not interchangeable.
    Single pass, not iterative — Paper/Claim are the only labels this
    module ever writes with paper provenance, so nothing further
    downstream needs a second pass to notice a drop."""
    keep_paper_ids = {
        n.node_id
        for n in subgraph.nodes
        if "Paper" in n.labels and n.properties.get("collection_id") == collection_id
    }
    drop_paper_ids = {n.node_id for n in subgraph.nodes if "Paper" in n.labels} - keep_paper_ids
    in_collection_paper_ids = {
        n.properties.get("paper_id") for n in subgraph.nodes if n.node_id in keep_paper_ids
    }
    drop_claim_ids = {
        n.node_id
        for n in subgraph.nodes
        if "Claim" in n.labels
        and n.properties.get("source_paper_id") not in in_collection_paper_ids
    }
    drop_ids = drop_paper_ids | drop_claim_ids
    if not drop_ids:
        return subgraph

    edges = [
        e for e in subgraph.edges if e.source_id not in drop_ids and e.target_id not in drop_ids
    ]
    connected_ids = {e.source_id for e in edges} | {e.target_id for e in edges}
    nodes = [
        n
        for n in subgraph.nodes
        if n.node_id not in drop_ids and (n.node_id in connected_ids or n.node_id in keep_paper_ids)
    ]
    seed_ids = [s for s in subgraph.seed_ids if s not in drop_ids]
    return Subgraph(nodes=nodes, edges=edges, seed_ids=seed_ids)


async def _resolve_seed_ids(seeds: SeedResult, collection_id: str | None = None) -> list[str]:
    """Entity seeds already carry an elementId — left unscoped even when
    collection_id is set, matching vector_retriever.py's own documented
    tradeoff (a real shared entity is collection-agnostic by design).

    Paper seeds carry a Postgres paper_id and need one lookup to become the
    Paper node's elementId. Live finding 2026-08-20: SeedResult.paper_ids is
    a merge of chunk-derived ids (already collection-scoped — _search_chunks
    applies the Chroma where-filter) AND entity-derived ids from a shared
    entity's source_papers metadata (deliberately NOT collection-scoped,
    same tradeoff as above) — that second half could pull a genuinely
    out-of-collection paper in as a full traversal SEED, not just a leaf
    node one hop away, handing it the same standing as an in-collection one
    (seeds skip the entity_types filter entirely) and letting its whole
    local neighborhood compete for the node cap. Scoped here rather than
    where paper_ids is built (vector_retriever.py is deliberately DB-free,
    no way for it to know collection membership) — filtering the *merged*
    list against collection_id is safe either way, since the chunk-derived
    half is already in-collection by construction and this only ever
    narrows, never wrongly drops, that half."""
    seed_ids = [e.node_id for e in seeds.entities]
    if not seeds.paper_ids:
        return seed_ids

    driver = get_driver()
    async with driver.session() as session:
        if collection_id is not None:
            result = await session.run(
                _PAPER_ELEMENT_IDS_SCOPED,
                paper_ids=list(seeds.paper_ids),
                collection_id=collection_id,
            )
        else:
            result = await session.run(_PAPER_ELEMENT_IDS, paper_ids=list(seeds.paper_ids))
        seed_ids += [record["id"] async for record in result]
    return seed_ids


def _build_subgraph(rows, entity_types: list[str] | None, all_seed_ids: list[str]) -> Subgraph:
    """Builds the full subgraph from traversal rows — entity_types still
    applies (a cheap node-type filter, unrelated to node-count capping) but
    the 200-node cap does NOT happen here anymore (see _cap_nodes) so a
    collection filter gets a chance to run on the complete set first."""
    seed_ids = set(all_seed_ids)
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for row in rows:
        a_id, b_id = row["a_id"], row["b_id"]
        if entity_types is not None:
            if a_id not in seed_ids and not set(row["a_labels"]) & set(entity_types):
                continue
            if b_id not in seed_ids and not set(row["b_labels"]) & set(entity_types):
                continue

        nodes.setdefault(a_id, GraphNode(a_id, row["a_labels"], _clean_props(row["a_props"])))
        nodes.setdefault(b_id, GraphNode(b_id, row["b_labels"], _clean_props(row["b_props"])))
        edges.append(GraphEdge(a_id, b_id, row["rel_type"], dict(row["rel_props"])))

    return Subgraph(nodes=list(nodes.values()), edges=edges, seed_ids=all_seed_ids)


def _cap_nodes(subgraph: Subgraph, max_nodes: int) -> Subgraph:
    """Trims to max_nodes — same greedy "take highest-confidence edges
    first, an edge later in the list can still be admitted if it only
    touches already-admitted nodes" logic the old single-pass _cap_subgraph
    always used, just running over an already-collection-filtered edge list
    (still in its original confidence-sorted order) instead of raw rows."""
    if len(subgraph.nodes) <= max_nodes:
        return subgraph

    node_by_id = {n.node_id: n for n in subgraph.nodes}
    kept: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    for e in subgraph.edges:
        new_ids = {nid for nid in (e.source_id, e.target_id) if nid not in kept}
        if new_ids and len(kept) + len(new_ids) > max_nodes:
            continue  # would exceed the cap and doesn't already fit
        for nid in (e.source_id, e.target_id):
            kept.setdefault(nid, node_by_id[nid])
        edges.append(e)

    return Subgraph(nodes=list(kept.values()), edges=edges, seed_ids=subgraph.seed_ids)


def _clean_props(props: dict) -> dict:
    """Strips the embedding vector — dead weight in a subgraph result, never
    something a caller wants to see, unlike everything else on the node."""
    return {k: v for k, v in props.items() if k != "embedding"}
