"""Vector seed retriever (RETRIEVAL-001) — the first step of GraphRAG's
hybrid retrieval. Embeds the query once, searches both Chroma collections,
and returns the combined "seed" identifiers RETRIEVAL-002's graph traversal
will start from.

Two independent seed types, kept separate rather than merged into one list
— RETRIEVAL-002 needs to treat them differently:
- Entity seeds carry a Neo4j elementId directly: graph_writer.py writes
  Chroma's entity_embeddings id as f"entity_{elementId}" (EXTRACT-004), so
  stripping that prefix is enough to seed a Cypher traversal — no second
  Neo4j round-trip needed just to resolve an id.
- Chunk seeds carry a Postgres paper_id, which is also the Neo4j Paper
  node's MERGE key (graph_writer.write_paper, §4.2) — equally
  directly seedable.

paper_ids is the deduplicated union of every paper touched by either seed
type: chunk seeds' own paper_id, plus each entity seed's source_papers
metadata (graph_writer.py tracks which papers reference a shared entity) —
satisfies the ticket's "same paper in both entity and chunk results counts
once" requirement without the caller having to do that bookkeeping itself.

Handles an empty graph (no entities extracted yet) with no special-casing:
Chroma's query() against an empty/missing-match collection returns empty
result lists, not an error, so entities naturally comes back `[]` and the
seed set silently falls back to chunks only — exactly the ticket's
acceptance criterion.

POLISH-005b — collection_id scoping, added 2026-08-15: chunk search takes a
direct Chroma `where` filter (embedding_storage.py stamps collection_id
into chunk metadata at write time). Entity search deliberately stays
unscoped here — entity_embeddings metadata never carries collection_id
(entity resolution merges the same shared entity across every paper/
collection, so tagging one node with a single collection_id would be
wrong), matching POLISH-005b's own recommended decision: entities stay
collection-agnostic, only paper/chunk provenance is scoped. An
out-of-collection entity seed isn't a correctness problem even though it's
not pre-filtered here — graph_retriever.py's own collection_id filter
prunes it downstream (as an orphan, once its edges to out-of-collection
papers are cut), the same way a real collection-agnostic shared entity
survives if it has even one in-collection connection.
"""

from dataclasses import dataclass

from src.config import settings
from src.vectorstore.store import query_similar


@dataclass
class EntitySeed:
    node_id: str  # Neo4j elementId, parsed from the Chroma id
    entity_type: str
    canonical_name: str
    score: float  # cosine similarity (1 - Chroma's cosine distance) — higher is better


@dataclass
class ChunkSeed:
    paper_id: str
    text: str
    section_name: str
    score: float


@dataclass
class SeedResult:
    entities: list[EntitySeed]
    chunks: list[ChunkSeed]
    paper_ids: list[str]  # deduplicated — every paper touched by either seed type


def retrieve_seeds(
    query: str,
    entity_top_k: int | None = None,
    chunk_top_k: int | None = None,
    collection_id: str | None = None,
) -> SeedResult:
    entities, entity_source_papers = _search_entities(query, entity_top_k or settings.entity_top_k)
    chunks = _search_chunks(query, chunk_top_k or settings.vector_top_k, collection_id)

    paper_ids = {c.paper_id for c in chunks if c.paper_id} | entity_source_papers
    return SeedResult(entities=entities, chunks=chunks, paper_ids=sorted(paper_ids))


def _search_entities(query: str, top_k: int) -> tuple[list[EntitySeed], set[str]]:
    """Returns the entity seeds, plus the union of every entity's
    source_papers metadata (graph_writer.py tracks which papers reference a
    shared entity) — feeds retrieve_seeds' deduplicated paper_ids without
    EntitySeed itself needing to carry that list."""
    result = query_similar(settings.chroma_collection_entities, query, top_k=top_k)

    ids = result["ids"][0] if result.get("ids") else []
    metadatas = result["metadatas"][0] if result.get("metadatas") else []
    distances = result["distances"][0] if result.get("distances") else []

    entities = [
        EntitySeed(
            node_id=chroma_id.removeprefix("entity_"),
            entity_type=meta.get("entity_type", ""),
            canonical_name=meta.get("canonical_name", ""),
            score=1 - dist,
        )
        for chroma_id, meta, dist in zip(ids, metadatas, distances, strict=True)
    ]
    source_papers = {p for meta in metadatas for p in meta.get("source_papers", "").split(",") if p}
    return entities, source_papers


def _search_chunks(query: str, top_k: int, collection_id: str | None = None) -> list[ChunkSeed]:
    where = {"collection_id": collection_id} if collection_id else None
    result = query_similar(settings.chroma_collection_chunks, query, top_k=top_k, where=where)

    documents = result["documents"][0] if result.get("documents") else []
    metadatas = result["metadatas"][0] if result.get("metadatas") else []
    distances = result["distances"][0] if result.get("distances") else []

    return [
        ChunkSeed(
            paper_id=meta.get("paper_id", ""),
            text=doc,
            section_name=meta.get("section_name", ""),
            score=1 - dist,
        )
        for doc, meta, dist in zip(documents, metadatas, distances, strict=True)
    ]
