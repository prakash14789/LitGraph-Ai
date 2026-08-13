"""Graph writer (EXTRACT-004) — the module every prior "candidate list
stands in for a real Neo4j lookup" comment (INGEST-007, EXTRACT-002,
EXTRACT-003) has been waiting for. Takes entity_resolver's ResolutionResult
and relation_extractor's ExtractedRelation and actually writes them: MERGE
for nodes (idempotent — reprocessing a paper updates the same node, never
duplicates it), CREATE for relationships per the ticket.

Two node "families", matching what §4.2 actually gives each type:
- Named/resolved entities (Method, Dataset, Author, Metric) — MERGE key is
  canonical_name for Method/Dataset (matches their §4.2 uniqueness
  constraint) or name for Author/Metric — same key resolve_entity's own
  exact-match step already uses, so a fresh resolution and a re-processed
  one land on the same node. Method/Dataset also get an embedding (from
  description) written to the node AND upserted into Chroma's
  entity_embeddings collection — the ticket's "critical, do not skip"
  instruction. Author/Metric get neither: §4.2's own node-structure
  examples don't give them an embedding field, and §4.3's entity_embeddings
  comment explicitly scopes that collection to "method/dataset/claim".
- Claims — not run through entity_resolver (a claim isn't a named,
  cross-paper-shared entity — §4.2 gives it a singular `source_paper_id`,
  not the shared source_papers list Method/Dataset get). Deduped instead by
  a content hash of (paper_id, text), so reprocessing the same paper
  doesn't duplicate the same claim. Still gets an embedding + Chroma entry,
  per §4.3.

AUTHORED_BY isn't produced by relation_extractor.py (see its own comment:
pdf_parser already parses paper.authors as structured data — nothing for an
LLM to add there). write_authors() is this module's answer to that: MERGE
each Author node straight from paper.authors and CREATE the
Paper-[:AUTHORED_BY]->Author edges, no LLM/resolution step needed for a
field that's already structured.

fetch_candidate_entities() (EXTRACT-005) is this module's one read: every
existing Method/Dataset node, feeding entity_resolver's resolve_entity()
and relation_extractor's cross-paper candidate list — the real lookup both
modules were always designed to take a stand-in list for.

ponytail: no distributed transaction across Neo4j and Chroma — a crash
between the two writes can leave a node's Chroma record briefly stale.
Acceptable at this write volume; upgrade path is an outbox/retry if that
ever matters.

ponytail: CREATE (not MERGE) for relationships, per the ticket. Reprocessing
a paper can therefore create duplicate edges — the ticket's own acceptance
criteria only requires *entity* (node) idempotency, not relationship
idempotency, so this isn't a gap against spec. Upgrade path: EXTRACT-005
deletes a paper's existing relationships before re-writing on reprocess, if
that's ever needed.
"""

import hashlib

import structlog

from src.config import settings
from src.graph.connection import get_driver
from src.graph.queries import EXISTING_NAMED_ENTITIES
from src.services.ingestion.entity_resolver import ResolvableEntity, ResolutionResult
from src.vectorstore.embedder import embed
from src.vectorstore.store import get_collection

logger = structlog.get_logger()

# §4.2's uniqueness constraint (or, for Metric, the natural key) per label.
_MERGE_KEY_BY_LABEL = {
    "Method": "canonical_name",
    "Dataset": "canonical_name",
    "Author": "name",
    "Metric": "name",
}
# §4.2's node-structure examples only give these two an `embedding` field;
# §4.3 explicitly scopes entity_embeddings to "method/dataset/claim".
_EMBEDDED_LABELS = {"Method", "Dataset"}

_MERGE_NODE = "MERGE (n:{label} {{{key}: $key_value}}) SET n += $props RETURN elementId(n) AS id"
_CREATE_REL = (
    "MATCH (a) WHERE elementId(a) = $source_id "
    "MATCH (b) WHERE elementId(b) = $target_id "
    "CREATE (a)-[r:{rel_type}]->(b) SET r += $props RETURN elementId(r) AS id"
)


async def write_paper(
    paper_id: str,
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None,
    abstract: str | None,
) -> str:
    """MERGE keyed on paper_id (§4.2's uniqueness constraint) — reprocessing
    the same paper updates this node instead of duplicating it."""
    vector = embed([abstract or title])[0]
    props = {
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "abstract": abstract,
        "embedding": vector,
    }
    node_id = await _merge_node("Paper", "paper_id", paper_id, props)
    logger.info("graph_writer.paper_written", paper_id=paper_id, node_id=node_id)
    return node_id


async def write_authors(paper_node_id: str, authors: list[str]) -> list[str]:
    """MERGE each author by exact name (§4.2's author_name constraint),
    CREATE the Paper-[:AUTHORED_BY]->Author edge. No resolution/fuzzy
    matching — unlike Method/Dataset, author names come straight from
    pdf_parser's structured metadata, not an LLM guess."""
    author_ids = []
    for name in authors:
        author_id = await _merge_node("Author", "name", name.strip(), {})
        await write_relationship("AUTHORED_BY", paper_node_id, author_id, {})
        author_ids.append(author_id)
    return author_ids


async def write_named_entity(
    label: str,
    resolution: ResolutionResult,
    paper_id: str,
    extra_properties: dict | None = None,
) -> str:
    """label: "Method" | "Dataset" | "Author" | "Metric" — anything
    entity_resolver.resolve_entity() was run against. extra_properties
    carries type-specific fields entity_resolver doesn't know about
    (Method's `category`, Dataset's `domain`, ...)."""
    key = _MERGE_KEY_BY_LABEL[label]
    props = {
        key: resolution.canonical_name,
        "aliases": resolution.aliases,
        **(extra_properties or {}),
    }
    if resolution.description:
        props["description"] = resolution.description

    vector = None
    if label in _EMBEDDED_LABELS:
        vector = embed([resolution.description or resolution.canonical_name])[0]
        props["embedding"] = vector

    node_id = await _merge_node(label, key, resolution.canonical_name, props)

    if vector is not None:
        _upsert_chroma_entity(
            node_id, label, resolution.canonical_name, resolution.description, vector, paper_id
        )

    logger.info(
        "graph_writer.entity_written",
        label=label,
        canonical_name=resolution.canonical_name,
        node_id=node_id,
        decision=resolution.decision,
    )
    return node_id


async def write_claim(paper_id: str, text: str, claim_type: str, confidence: float) -> str:
    """Not run through entity_resolver — see module docstring. Deduped by a
    content hash of (paper_id, text) instead, so reprocessing the same
    paper doesn't duplicate the same claim."""
    claim_id = hashlib.sha256(f"{paper_id}:{text}".encode()).hexdigest()[:24]
    vector = embed([text])[0]
    props = {
        "claim_id": claim_id,
        "text": text,
        "claim_type": claim_type,
        "source_paper_id": paper_id,
        "confidence": confidence,
        "embedding": vector,
    }
    node_id = await _merge_node("Claim", "claim_id", claim_id, props)
    _upsert_chroma_entity(node_id, "Claim", text[:80], text, vector, paper_id)
    logger.info("graph_writer.claim_written", node_id=node_id, claim_type=claim_type)
    return node_id


async def fetch_candidate_entities() -> list[ResolvableEntity]:
    """Every existing Method/Dataset node, across all papers — the real
    Neo4j lookup entity_resolver.py's and relation_extractor.py's
    candidate-list interfaces were always designed around, wired in by
    EXTRACT-005 now that there's real data to look up. Lives here, not
    entity_resolver.py (which deliberately never touches Neo4j itself, per
    its own module docstring) — this is a read, but it's this module's
    Neo4j session machinery either way."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(EXISTING_NAMED_ENTITIES)
        records = [record async for record in result]
    return [
        ResolvableEntity(
            name=r["canonical_name"],
            entity_type=r["entity_type"],
            description=r["description"] or "",
            aliases=r["aliases"] or [],
            id=r["id"],
            embedding=r["embedding"],
        )
        for r in records
    ]


async def write_relationship(
    rel_type: str, source_id: str, target_id: str, properties: dict
) -> str:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            _CREATE_REL.format(rel_type=rel_type),
            source_id=source_id,
            target_id=target_id,
            props=properties,
        )
        record = await result.single()
    return record["id"]


async def _merge_node(label: str, key: str, key_value: str, props: dict) -> str:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            _MERGE_NODE.format(label=label, key=key), key_value=key_value, props=props
        )
        record = await result.single()
    return record["id"]


def _upsert_chroma_entity(
    node_id: str,
    entity_type: str,
    canonical_name: str,
    description: str,
    embedding: list[float],
    paper_id: str,
) -> None:
    """The ticket's 'critical - do not skip' instruction: RETRIEVAL-001
    queries Chroma's entity_embeddings collection directly, not Neo4j — a
    node with an embedding property but no Chroma row is invisible to it.
    upsert (not add) so a merged/updated entity overwrites its existing
    record instead of leaving a stale duplicate.

    source_papers tracked as a comma-joined string, not a list — Chroma
    metadata values must be str/int/float/bool, no lists (§4.3 shows it as
    a list in the doc's illustrative JSON, but that's not literally storable)."""
    collection = get_collection(settings.chroma_collection_entities)
    chroma_id = f"entity_{node_id}"
    existing = collection.get(ids=[chroma_id])
    source_papers = (
        set(existing["metadatas"][0].get("source_papers", "").split(","))
        if existing["ids"]
        else set()
    )
    source_papers.discard("")
    source_papers.add(paper_id)

    document = f"{canonical_name}: {description}" if description else canonical_name
    collection.upsert(
        ids=[chroma_id],
        embeddings=[embedding],
        documents=[document],
        metadatas=[
            {
                "entity_type": entity_type,
                "canonical_name": canonical_name,
                "source_papers": ",".join(sorted(source_papers)),
            }
        ],
    )
