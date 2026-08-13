"""Unit tests for context_builder.py — pure computation over hand-built
RankedSubgraph/SeedResult fixtures, no I/O (same rationale as
test_hybrid_scorer.py)."""

from src.services.retrieval.context_builder import build_context
from src.services.retrieval.graph_retriever import GraphEdge, GraphNode
from src.services.retrieval.hybrid_scorer import RankedSubgraph, ScoredNode
from src.services.retrieval.vector_retriever import ChunkSeed, SeedResult


def _scored(node_id: str, labels: list[str], **props) -> ScoredNode:
    node = GraphNode(node_id=node_id, labels=labels, properties=props)
    return ScoredNode(
        node=node, score=1.0, vector_similarity=1.0, graph_distance=0, avg_edge_confidence=1.0
    )


def _edge(source: str, target: str, rel_type: str, **props) -> GraphEdge:
    return GraphEdge(source, target, rel_type, props)


def _seeds(chunks: list[ChunkSeed] | None = None) -> SeedResult:
    return SeedResult(entities=[], chunks=chunks or [], paper_ids=[])


def test_method_entity_shows_introduced_by_and_relationship_includes_evidence():
    paper = _scored("p", ["Paper"], title="BERT: Pre-training", year=2018)
    method = _scored("m", ["Method"], canonical_name="BERT")
    ranked = RankedSubgraph(
        nodes=[method, paper],
        edges=[
            _edge("p", "m", "INTRODUCES", confidence=0.9),
            _edge("p", "m", "USES_METHOD", confidence=0.8, evidence_text="the paper uses BERT"),
        ],
    )

    ctx = build_context(ranked, _seeds())

    assert "ENTITIES:" in ctx.text
    assert "- [METHOD] BERT (introduced by Paper: 'BERT: Pre-training', 2018)" in ctx.text
    assert "- [PAPER] 'BERT: Pre-training' (2018)" in ctx.text
    assert "USES_METHOD" in ctx.text and 'evidence: "the paper uses BERT"' in ctx.text
    # INTRODUCES folded into the entity line, not repeated as its own relationship line
    assert "INTRODUCES" not in ctx.text.split("RELATIONSHIPS:")[1]


def test_evaluates_on_and_outperforms_formatting():
    paper = _scored("p", ["Paper"], title="SpanBERT")
    dataset = _scored("d", ["Dataset"], canonical_name="SQuAD 2.0")
    bert = _scored("b", ["Method"], canonical_name="BERT")
    spanbert = _scored("s", ["Method"], canonical_name="SpanBERT")
    ranked = RankedSubgraph(
        nodes=[paper, dataset, bert, spanbert],
        edges=[
            _edge("p", "d", "EVALUATES_ON", metric="F1", value="88.7"),
            _edge("s", "b", "OUTPERFORMS", metric="F1", dataset="SQuAD 2.0", margin="+2.3"),
        ],
    )

    ctx = build_context(ranked, _seeds())

    assert "- 'SpanBERT' EVALUATES_ON SQuAD 2.0 (F1: 88.7)" in ctx.text
    assert "- SpanBERT OUTPERFORMS BERT on SQuAD 2.0 (F1 margin: +2.3)" in ctx.text


def test_reports_result_uses_claim_text_without_duplicate_evidence():
    paper = _scored("p", ["Paper"], title="Some Paper")
    claim = _scored("c", ["Claim"], text="Our method improves F1 by 2 points")
    ranked = RankedSubgraph(
        nodes=[paper, claim],
        edges=[
            _edge(
                "p",
                "c",
                "REPORTS_RESULT",
                confidence=0.9,
                evidence_text="Our method improves F1 by 2 points",
            )
        ],
    )

    ctx = build_context(ranked, _seeds())

    relationships_section = ctx.text.split("RELATIONSHIPS:")[1]
    assert (
        "- 'Some Paper' REPORTS_RESULT: Our method improves F1 by 2 points" in relationships_section
    )
    assert "evidence:" not in relationships_section  # claim text IS the evidence, not repeated


def test_authored_by_excluded_from_relationships():
    paper = _scored("p", ["Paper"], title="T")
    author = _scored("a", ["Author"], name="A. Author")
    ranked = RankedSubgraph(nodes=[paper, author], edges=[_edge("p", "a", "AUTHORED_BY")])

    ctx = build_context(ranked, _seeds())

    assert "- [AUTHOR] A. Author" in ctx.text  # still listed as an entity
    assert "RELATIONSHIPS:" not in ctx.text  # only edge was AUTHORED_BY, filtered out entirely


def test_chunks_included_and_graceful_truncation_under_tight_budget():
    ranked = RankedSubgraph(nodes=[], edges=[])
    chunks = [
        ChunkSeed(paper_id="p1", text="a" * 50, section_name="intro", score=0.9),
        ChunkSeed(paper_id="p1", text="b" * 50, section_name="method", score=0.8),
    ]

    full = build_context(ranked, _seeds(chunks), max_tokens=8000)
    assert "RELEVANT TEXT CHUNKS:" in full.text
    assert "aaa" in full.text and "bbb" in full.text
    assert full.truncated is False

    tight = build_context(ranked, _seeds(chunks), max_tokens=15)
    assert tight.truncated is True
    assert tight.token_count <= 15


def test_empty_graph_falls_back_to_chunks_only():
    ranked = RankedSubgraph(nodes=[], edges=[])
    chunks = [ChunkSeed(paper_id="p1", text="fallback text", section_name="abstract", score=0.5)]

    ctx = build_context(ranked, _seeds(chunks))

    assert "ENTITIES:" not in ctx.text
    assert "RELATIONSHIPS:" not in ctx.text
    assert "RELEVANT TEXT CHUNKS:" in ctx.text
