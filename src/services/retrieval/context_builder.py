"""Context builder (RETRIEVAL-004) — the last step of GraphRAG's own
retrieval pipeline. Turns RETRIEVAL-003's ranked subgraph, plus
RETRIEVAL-001's vector-similar chunks, into the structured text block
RETRIEVAL-005's generator hands the LLM, per the ticket's own format:

    ENTITIES:
    - [METHOD] BERT (introduced by Paper: 'BERT: Pre-training...', 2018)

    RELATIONSHIPS:
    - SpanBERT EXTENDS BERT (evidence: "SpanBERT builds on BERT by...")

    RELEVANT TEXT CHUNKS:
    - [section] chunk text...

Entities are grouped by type (Method/Dataset/Paper/Author/Metric/Claim,
ticket-listed types first, anything else after) and ranked-best-first
within a group, since RankedSubgraph.nodes already comes that way from
hybrid_scorer. A Method/Dataset's "introduced by Paper" annotation is read
straight off an INTRODUCES edge already in the ranked subgraph (Paper is
always the source per relation_extractor.py's own prompt contract) — folded
into the entity line, not repeated as its own RELATIONSHIPS line.
AUTHORED_BY is skipped from RELATIONSHIPS the same way: no evidence/
confidence, not useful QA signal on its own (Author nodes still appear
under ENTITIES if they made the ranked subgraph).

REPORTS_RESULT's target is a Claim node (pipeline.py synthesizes that edge
directly from entity_extractor's claims, not relation_extractor's own
text) — skips the generic "(evidence: ...)" suffix other relation types
get, since the Claim's own text already IS the evidence, and repeating it
would just duplicate the same sentence twice on one line.

Token budget (8K max, per the ticket's acceptance criterion): ENTITIES +
RELATIONSHIPS get first claim on it, but not the whole thing — capped to
leave at least _MIN_CHUNK_TOKENS for RELEVANT TEXT CHUNKS. EVAL-002 live
finding: a multi-hop/comparison question naturally pulls in more entities
(2+ papers), which used to eat the whole 8K before any raw text was added —
starving exactly the fallback a question needing a precise textual nuance
(a paper's specific wording, not a fact the graph captured) needs most,
right as vanilla RAG's own context (10 chunks, no competition for space)
keeps its full share. Lowest-ranked entities/relationships are dropped
first to make room — RETRIEVAL-003 already ranks both lists best-first, so
trimming from the end drops the least-relevant items. Chunks (already
ranked best-first by vector_retriever/Chroma) are then added one at a
time, checking the real token count of the whole candidate text each
time, stopping the moment one more would cross the limit — exact against
what actually gets sent, not an approximation from summed per-line costs.
"""

from dataclasses import dataclass

import tiktoken

from src.services.retrieval.graph_retriever import GraphEdge, GraphNode
from src.services.retrieval.hybrid_scorer import RankedSubgraph, ScoredNode
from src.services.retrieval.vector_retriever import SeedResult

_ENCODING = tiktoken.get_encoding("cl100k_base")  # same encoding chunker.py already uses
_MAX_CONTEXT_TOKENS = 8000  # ticket-literal cap
_MIN_CHUNK_TOKENS = 1500  # EVAL-002 finding — see module docstring

# Ticket-listed types first (Method/Dataset get the "introduced by" annotation,
# Paper/Author/Metric/Claim are the other node kinds graph_writer.py ever
# writes); anything else sorts after, alphabetically.
_ENTITY_ORDER = ["Method", "Dataset", "Paper", "Author", "Metric", "Claim"]
# INTRODUCES is folded into the entity line itself (see module docstring);
# AUTHORED_BY carries no evidence/confidence, not useful QA signal alone.
_SKIPPED_RELATIONSHIP_TYPES = {"INTRODUCES", "AUTHORED_BY"}


@dataclass
class BuiltContext:
    text: str
    token_count: int
    truncated: bool


def build_context(
    ranked: RankedSubgraph, seeds: SeedResult, max_tokens: int = _MAX_CONTEXT_TOKENS
) -> BuiltContext:
    node_by_id = {s.node.node_id: s.node for s in ranked.nodes}
    introduces_by = {
        edge.target_id: node_by_id[edge.source_id]
        for edge in ranked.edges
        if edge.rel_type == "INTRODUCES"
        and edge.source_id in node_by_id
        and edge.target_id in node_by_id
    }

    entity_lines = _grouped_entity_lines(ranked.nodes, introduces_by)
    relationship_lines = [
        line
        for edge in ranked.edges
        if (line := _format_relationship(edge, node_by_id)) is not None
    ]

    # Both lists are already ranked best-first (RETRIEVAL-003), so trimming
    # from the end drops the least-relevant items first. relationship_lines
    # goes first — an entity line is denser QA signal (name + type + intro)
    # per token than a relationship line, and there are usually more
    # relationships than entities once a subgraph spans 2+ papers.
    entities_budget = max_tokens - _MIN_CHUNK_TOKENS
    truncated = False
    while _count_tokens(
        "\n".join(entity_lines) + "\n".join(relationship_lines)
    ) > entities_budget and (relationship_lines or entity_lines):
        truncated = True
        if relationship_lines:
            relationship_lines.pop()
        else:
            entity_lines.pop()

    sections = []
    if entity_lines:
        sections.append("ENTITIES:\n" + "\n".join(entity_lines))
    if relationship_lines:
        sections.append("RELATIONSHIPS:\n" + "\n".join(relationship_lines))

    chunk_lines: list[str] = []
    for chunk in seeds.chunks:
        candidate_lines = [*chunk_lines, f"- [{chunk.section_name}] {chunk.text}"]
        candidate = "\n\n".join([*sections, "RELEVANT TEXT CHUNKS:\n" + "\n".join(candidate_lines)])
        if _count_tokens(candidate) > max_tokens:
            truncated = True
            break
        chunk_lines = candidate_lines

    if chunk_lines:
        sections.append("RELEVANT TEXT CHUNKS:\n" + "\n".join(chunk_lines))

    text = "\n\n".join(sections)
    return BuiltContext(text=text, token_count=_count_tokens(text), truncated=truncated)


def _grouped_entity_lines(
    scored_nodes: list[ScoredNode], introduces_by: dict[str, GraphNode]
) -> list[str]:
    by_label: dict[str, list[GraphNode]] = {}
    for scored in scored_nodes:  # already ranked best-first by hybrid_scorer
        label = scored.node.labels[0] if scored.node.labels else "Entity"
        by_label.setdefault(label, []).append(scored.node)

    ordered_labels = [label for label in _ENTITY_ORDER if label in by_label]
    ordered_labels += sorted(label for label in by_label if label not in _ENTITY_ORDER)

    return [
        _format_entity(node, introduces_by) for label in ordered_labels for node in by_label[label]
    ]


def _format_entity(node: GraphNode, introduces_by: dict[str, GraphNode]) -> str:
    label = node.labels[0] if node.labels else "Entity"
    props = node.properties

    if label in ("Method", "Dataset"):
        name = props.get("canonical_name", node.node_id)
        intro = introduces_by.get(node.node_id)
        suffix = ""
        if intro is not None:
            title = intro.properties.get("title", "")
            year = intro.properties.get("year")
            suffix = f" (introduced by Paper: '{title}'{f', {year}' if year else ''})"
        return f"- [{label.upper()}] {name}{suffix}"

    if label == "Paper":
        meta_parts = ([str(props["year"])] if props.get("year") else []) + (
            [props["venue"]] if props.get("venue") else []
        )
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
        return f"- [PAPER] '{props.get('title', node.node_id)}'{meta}"

    if label == "Claim":
        return f"- [CLAIM] {props.get('text', node.node_id)}"

    name = props.get("name") or props.get("canonical_name") or props.get("title") or node.node_id
    return f"- [{label.upper()}] {name}"


def _format_relationship(edge: GraphEdge, node_by_id: dict[str, GraphNode]) -> str | None:
    if edge.rel_type in _SKIPPED_RELATIONSHIP_TYPES:
        return None
    source, target = node_by_id.get(edge.source_id), node_by_id.get(edge.target_id)
    if source is None or target is None:
        return None
    source_name, target_name = _display_name(source), _display_name(target)
    props = edge.properties

    if edge.rel_type == "EVALUATES_ON":
        metric, value = props.get("metric"), props.get("value")
        detail = f" ({metric}: {value})" if metric and value else ""
        return f"- {source_name} EVALUATES_ON {target_name}{detail}"
    if edge.rel_type == "OUTPERFORMS":
        metric, dataset, margin = props.get("metric"), props.get("dataset"), props.get("margin")
        detail = (
            f" on {dataset} ({metric} margin: {margin})" if dataset and metric and margin else ""
        )
        return f"- {source_name} OUTPERFORMS {target_name}{detail}"
    if edge.rel_type == "REPORTS_RESULT":
        return f"- {source_name} REPORTS_RESULT: {target_name}"

    evidence = props.get("evidence_text")
    detail = f' (evidence: "{evidence}")' if evidence else ""
    return f"- {source_name} {edge.rel_type} {target_name}{detail}"


def _display_name(node: GraphNode) -> str:
    props = node.properties
    if node.labels and node.labels[0] == "Paper":
        return f"'{props.get('title', node.node_id)}'"
    return props.get("canonical_name") or props.get("name") or props.get("text") or node.node_id


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text)) if text else 0
