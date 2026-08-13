"""Unit tests for hybrid_scorer.py — pure computation over hand-built
Subgraph/SeedResult fixtures, no I/O, so no real Neo4j/Chroma needed (unlike
graph_writer.py/graph_retriever.py, this module's only job is arithmetic
over data it's handed)."""

from src.services.retrieval.graph_retriever import GraphEdge, GraphNode, Subgraph
from src.services.retrieval.hybrid_scorer import score_subgraph
from src.services.retrieval.vector_retriever import ChunkSeed, EntitySeed, SeedResult


def _node(node_id: str, labels: list[str], **props) -> GraphNode:
    return GraphNode(node_id=node_id, labels=labels, properties=props)


def _edge(source: str, target: str, rel_type: str, confidence: float | None = None) -> GraphEdge:
    return GraphEdge(
        source, target, rel_type, {"confidence": confidence} if confidence is not None else {}
    )


def _seeds(
    entities: list[EntitySeed] | None = None, chunks: list[ChunkSeed] | None = None
) -> SeedResult:
    return SeedResult(entities=entities or [], chunks=chunks or [], paper_ids=[])


def test_score_combines_vector_similarity_graph_distance_and_confidence():
    a = _node("a", ["Method"])
    b = _node("b", ["Method"])
    subgraph = Subgraph(nodes=[a, b], edges=[_edge("a", "b", "EXTENDS", 0.8)], seed_ids=["a"])
    seeds = _seeds(entities=[EntitySeed("a", "Method", "A", score=0.9)])

    ranked = score_subgraph(subgraph, seeds, alpha=0.4, beta=0.4, gamma=0.2)

    scored_a = next(s for s in ranked.nodes if s.node.node_id == "a")
    scored_b = next(s for s in ranked.nodes if s.node.node_id == "b")
    # seed: vector_similarity=0.9, distance clamped to 1 -> graph_term=1, avg_confidence=0.8
    assert scored_a.score == 0.4 * 0.9 + 0.4 * 1 + 0.2 * 0.8
    # non-seed, 1 hop away: vector_similarity=0 (never searched directly), graph_term=1, avg_confidence=0.8
    assert scored_b.score == 0.4 * 0.0 + 0.4 * 1 + 0.2 * 0.8


def test_weights_configurable_via_explicit_override():
    a = _node("a", ["Method"])
    subgraph = Subgraph(nodes=[a], edges=[_edge("a", "a", "EXTENDS", 0.5)], seed_ids=["a"])
    seeds = _seeds(entities=[EntitySeed("a", "Method", "A", score=0.7)])

    ranked = score_subgraph(subgraph, seeds, alpha=1.0, beta=0.0, gamma=0.0)

    assert ranked.nodes[0].score == 0.7


def test_output_is_ranked_and_only_includes_edges_between_kept_nodes():
    a = _node("a", ["Method"])
    b = _node("b", ["Method"])  # a's only edge to b is high-confidence -> b outscores a
    c = _node("c", ["Method"])  # a's only edge to c is low-confidence -> c scores lowest
    subgraph = Subgraph(
        nodes=[a, b, c],
        edges=[_edge("a", "b", "EXTENDS", 0.9), _edge("a", "c", "EXTENDS", 0.1)],
        seed_ids=["a"],
    )
    seeds = _seeds()

    ranked = score_subgraph(subgraph, seeds, top_k=2, alpha=0.4, beta=0.4, gamma=0.2)

    # b (avg_confidence 0.9) > a (avg_confidence (0.9+0.1)/2=0.5) > c (avg_confidence 0.1, dropped)
    assert [s.node.node_id for s in ranked.nodes] == ["b", "a"]
    assert len(ranked.edges) == 1  # a-b kept; a-c dropped since c isn't in the top-2
    assert {ranked.edges[0].source_id, ranked.edges[0].target_id} == {"a", "b"}


def test_tied_scores_broken_by_entity_type_preference():
    # identical score inputs for all three, only labels differ
    method = _node("m", ["Method"])
    paper = _node("p", ["Paper"])
    dataset = _node("d", ["Dataset"])
    edges = [
        _edge("seed", "m", "EXTENDS", 0.5),
        _edge("seed", "p", "EXTENDS", 0.5),
        _edge("seed", "d", "EXTENDS", 0.5),
    ]
    subgraph = Subgraph(nodes=[method, paper, dataset], edges=edges, seed_ids=["seed"])

    ranked = score_subgraph(subgraph, _seeds(), alpha=0.4, beta=0.4, gamma=0.2)

    assert [s.node.node_id for s in ranked.nodes] == ["m", "p", "d"]


def test_paper_node_inherits_vector_similarity_from_best_matching_chunk():
    paper = _node("p", ["Paper"], paper_id="paper-123")
    subgraph = Subgraph(nodes=[paper], edges=[_edge("p", "p", "AUTHORED_BY")], seed_ids=["p"])
    seeds = _seeds(
        chunks=[
            ChunkSeed(paper_id="paper-123", text="a", section_name="intro", score=0.3),
            ChunkSeed(paper_id="paper-123", text="b", section_name="method", score=0.6),
        ]
    )

    ranked = score_subgraph(subgraph, seeds, alpha=1.0, beta=0.0, gamma=0.0)

    assert ranked.nodes[0].vector_similarity == 0.6  # best of the two chunk scores, not the first
