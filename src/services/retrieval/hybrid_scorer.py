"""Hybrid scorer (RETRIEVAL-003) — the third step of GraphRAG's hybrid
retrieval. Combines RETRIEVAL-002's subgraph with RETRIEVAL-001's vector
similarity scores into one ranked node list, per the ticket's formula:

    score = alpha * vector_similarity + beta * (1 / graph_distance)
            + gamma * avg_edge_confidence

Three signals, computed per node:
- vector_similarity: an entity seed's own score (RETRIEVAL-001 already
  searched entity_embeddings against the query) if this node IS one, else
  the best-matching chunk's score for any Paper node whose paper_id
  property matches a ChunkSeed's paper_id (the paper was seeded because a
  chunk from it matched the query, so that chunk's score is the paper's
  best available similarity evidence). Anything reached purely by
  traversal — no direct vector match — gets 0.0; graph proximity and edge
  confidence are its only signals.
- graph_distance: BFS hop count from the nearest seed, over the subgraph's
  own edges treated as undirected (matches how graph_retriever's traversal
  pattern itself is direction-agnostic). Seeds are distance 0, which the
  ticket's literal `1/graph_distance` can't express — clamped to distance 1
  instead of dividing by zero, so a seed gets this term's max value (1)
  rather than crashing.
- avg_edge_confidence: mean `confidence` property (0.0 for edges that don't
  carry one, e.g. AUTHORED_BY — same coalesce graph_retriever's own query
  uses) over every edge in the subgraph incident to this node.

Every node in a Subgraph is reachable from some seed by construction
(graph_retriever only ever admits a node via an edge on the seeded
traversal), so an unreached node during BFS shouldn't happen — handled
defensively anyway (0.0 graph-distance term) rather than assumed away.

Tie-break: entity type preference (Methods > Papers > Datasets, per the
ticket; anything else — Author, Metric, Claim — sorts after all three).
"""

from collections import deque
from dataclasses import dataclass

from src.config import settings
from src.services.retrieval.graph_retriever import GraphEdge, GraphNode, Subgraph
from src.services.retrieval.vector_retriever import SeedResult

# Ticket-literal tie-break order. Labels not listed here (Author, Metric,
# Claim) sort after all three.
_TYPE_PREFERENCE = {"Method": 0, "Paper": 1, "Dataset": 2}
_TYPE_PREFERENCE_DEFAULT = len(_TYPE_PREFERENCE)


@dataclass
class ScoredNode:
    node: GraphNode
    score: float
    vector_similarity: float
    graph_distance: int | None  # None only if somehow unreached by BFS (see module docstring)
    avg_edge_confidence: float


@dataclass
class RankedSubgraph:
    nodes: list[ScoredNode]  # top-K, ranked by score descending
    edges: list[GraphEdge]  # only edges connecting two nodes both in `nodes`


def score_subgraph(
    subgraph: Subgraph,
    seeds: SeedResult,
    top_k: int | None = None,
    alpha: float | None = None,
    beta: float | None = None,
    gamma: float | None = None,
) -> RankedSubgraph:
    alpha = settings.hybrid_alpha if alpha is None else alpha
    beta = settings.hybrid_beta if beta is None else beta
    gamma = settings.hybrid_gamma if gamma is None else gamma
    top_k = top_k or settings.context_max_nodes

    distances = _bfs_distances(subgraph.edges, set(subgraph.seed_ids))
    similarities = _vector_similarities(subgraph.nodes, seeds)

    scored = []
    for node in subgraph.nodes:
        distance = distances.get(node.node_id)
        graph_term = 1 / max(distance, 1) if distance is not None else 0.0
        scored.append(
            ScoredNode(
                node=node,
                score=(
                    alpha * similarities.get(node.node_id, 0.0)
                    + beta * graph_term
                    + gamma * _avg_confidence(node.node_id, subgraph.edges)
                ),
                vector_similarity=similarities.get(node.node_id, 0.0),
                graph_distance=distance,
                avg_edge_confidence=_avg_confidence(node.node_id, subgraph.edges),
            )
        )

    scored.sort(key=lambda s: (-s.score, _type_rank(s.node.labels)))
    top = scored[:top_k]

    kept_ids = {s.node.node_id for s in top}
    kept_edges = [e for e in subgraph.edges if e.source_id in kept_ids and e.target_id in kept_ids]
    return RankedSubgraph(nodes=top, edges=kept_edges)


def _bfs_distances(edges: list[GraphEdge], seed_ids: set[str]) -> dict[str, int]:
    adjacency: dict[str, set[str]] = {}
    for e in edges:
        adjacency.setdefault(e.source_id, set()).add(e.target_id)
        adjacency.setdefault(e.target_id, set()).add(e.source_id)

    distances = {sid: 0 for sid in seed_ids if sid in adjacency}
    queue = deque(distances.keys())
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, ()):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def _avg_confidence(node_id: str, edges: list[GraphEdge]) -> float:
    incident = [
        e.properties.get("confidence", 0.0)
        for e in edges
        if e.source_id == node_id or e.target_id == node_id
    ]
    return sum(incident) / len(incident) if incident else 0.0


def _vector_similarities(nodes: list[GraphNode], seeds: SeedResult) -> dict[str, float]:
    similarities = {e.node_id: e.score for e in seeds.entities}

    best_chunk_score_by_paper: dict[str, float] = {}
    for c in seeds.chunks:
        if c.paper_id:
            best_chunk_score_by_paper[c.paper_id] = max(
                best_chunk_score_by_paper.get(c.paper_id, 0.0), c.score
            )

    for node in nodes:
        if "Paper" in node.labels:
            paper_id = node.properties.get("paper_id")
            if paper_id in best_chunk_score_by_paper:
                similarities.setdefault(node.node_id, best_chunk_score_by_paper[paper_id])

    return similarities


def _type_rank(labels: list[str]) -> int:
    ranks = [_TYPE_PREFERENCE.get(label, _TYPE_PREFERENCE_DEFAULT) for label in labels]
    return min(ranks) if ranks else _TYPE_PREFERENCE_DEFAULT
