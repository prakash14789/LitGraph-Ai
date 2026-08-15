"""Unit tests for graph_retriever._filter_by_collection — pure computation
over hand-built Subgraph/GraphNode/GraphEdge, no Neo4j needed (same
rationale as test_context_builder.py/test_hybrid_scorer.py). The real
Cypher traversal this filters is covered separately by
tests/integration/test_graph_retriever.py."""

from src.services.retrieval.graph_retriever import (
    GraphEdge,
    GraphNode,
    Subgraph,
    _filter_by_collection,
)


def _paper(node_id: str, collection_id: str | None) -> GraphNode:
    return GraphNode(node_id=node_id, labels=["Paper"], properties={"collection_id": collection_id})


def _method(node_id: str, name: str) -> GraphNode:
    return GraphNode(node_id=node_id, labels=["Method"], properties={"canonical_name": name})


def test_drops_out_of_collection_paper_and_its_private_entity():
    # P1 (collection A) -> shared Method M, P1 -> private Method X
    # P2 (collection B) -> shared Method M, P2 -> private Method Y
    subgraph = Subgraph(
        nodes=[
            _paper("p1", "A"),
            _paper("p2", "B"),
            _method("m", "shared"),
            _method("x", "private-to-p1"),
            _method("y", "private-to-p2"),
        ],
        edges=[
            GraphEdge("p1", "m", "USES_METHOD", {}),
            GraphEdge("p2", "m", "USES_METHOD", {}),
            GraphEdge("p1", "x", "USES_METHOD", {}),
            GraphEdge("p2", "y", "USES_METHOD", {}),
        ],
        seed_ids=["m"],
    )

    filtered = _filter_by_collection(subgraph, "A")

    kept_ids = {n.node_id for n in filtered.nodes}
    assert kept_ids == {
        "p1",
        "m",
        "x",
    }  # p2 dropped, its private entity y orphaned+dropped, m survives (still connected to p1)
    assert all(e.source_id != "p2" and e.target_id != "p2" for e in filtered.edges)


def test_untagged_paper_dropped_too_not_treated_as_wildcard():
    # A paper with no collection_id at all (legacy/ungrouped) shouldn't leak
    # into a specific-collection view — "scoped to A" means only A.
    subgraph = Subgraph(
        nodes=[_paper("p1", "A"), _paper("p2", None), _method("m", "shared")],
        edges=[GraphEdge("p1", "m", "USES_METHOD", {}), GraphEdge("p2", "m", "USES_METHOD", {})],
        seed_ids=["m"],
    )

    filtered = _filter_by_collection(subgraph, "A")

    assert {n.node_id for n in filtered.nodes} == {"p1", "m"}


def test_no_filtering_needed_returns_subgraph_unchanged():
    subgraph = Subgraph(
        nodes=[_paper("p1", "A"), _method("m", "shared")],
        edges=[GraphEdge("p1", "m", "USES_METHOD", {})],
        seed_ids=["p1"],
    )

    filtered = _filter_by_collection(subgraph, "A")

    assert filtered is subgraph  # early-returned, not just equal


def test_empty_subgraph_stays_empty():
    subgraph = Subgraph(nodes=[], edges=[], seed_ids=[])

    filtered = _filter_by_collection(subgraph, "A")

    assert filtered.nodes == []
    assert filtered.edges == []
