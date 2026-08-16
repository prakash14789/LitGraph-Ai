"""Paper deletion cascade (INGEST-007) — one function, not inlined in the
route, so it's independently testable and reusable by any future
account-deletion flow.

Order is leaf-data-first, Postgres row last: PDF file -> Neo4j entities (only
ones now orphaned) -> Chroma paper_chunks + orphaned entity_embeddings ->
Postgres row (left to the route's Depends(get_db) commit). This deliberately
differs from the ticket's literal 1-PDF/2-Postgres/3-Chroma/4-Neo4j listing
order: deleting the Postgres row first means a crash partway through leaves
orphaned files/vectors/graph data with no record anywhere that they still
need cleaning up. Doing it last means a failed/retried delete just finds the
same Paper row still there — everything else here is idempotent (deleting an
already-gone Chroma id, or matching an already-deleted Neo4j Paper node, is a
safe no-op).

Neo4j has nothing to actually delete yet — EXTRACT-004 (graph writer) hasn't
landed, so no paper has a (:Paper) node in the graph today. This still
implements the real cascade against the schema documented in
02_TECHNICAL_ARCHITECTURE.md §4.2, proven with hand-created graph nodes in
tests/integration/test_papers_api.py rather than left unbuilt/untested until
EXTRACT-004 exists.
"""

from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.graph.connection import get_driver
from src.graph.queries import DELETE_PAPER_CASCADE
from src.models.paper import Paper
from src.repositories import paper_repository
from src.vectorstore.store import get_collection

logger = structlog.get_logger()


async def delete_paper(db: AsyncSession, paper_id: UUID) -> Paper | None:
    """Returns the deleted Paper row, or None if no paper with that id exists."""
    paper = await paper_repository.get_by_id(db, paper_id)
    if paper is None:
        return None

    Path(paper.pdf_path).unlink(missing_ok=True)

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(DELETE_PAPER_CASCADE, paper_id=str(paper_id))
        record = await result.single()
    orphaned_ids: list[str] = record["orphaned_ids"] if record else []
    surviving_ids: list[str] = record["surviving_ids"] if record else []

    chunks = get_collection(settings.chroma_collection_chunks)
    existing = chunks.get(where={"paper_id": str(paper_id)})
    if existing["ids"]:
        chunks.delete(ids=existing["ids"])

    entities = get_collection(settings.chroma_collection_entities)
    if orphaned_ids:
        entities.delete(ids=[f"entity_{node_id}" for node_id in orphaned_ids])
    if surviving_ids:
        _remove_paper_from_source_papers(entities, surviving_ids, str(paper_id))

    await paper_repository.delete(db, paper_id)

    logger.info(
        "papers.deleted",
        paper_id=str(paper_id),
        title=paper.title,
        orphaned_entities=len(orphaned_ids),
        surviving_entities_updated=len(surviving_ids),
        chunks_removed=len(existing["ids"]),
    )
    return paper


def _remove_paper_from_source_papers(entities, node_ids: list[str], paper_id: str) -> None:
    """A shared entity's source_papers metadata (graph_writer.py's
    _upsert_chroma_entity) only ever grows — this is the other half of that
    write, run once here at delete time instead of on every write, since
    "which papers still reference this entity" only changes on deletion.
    Missing/never-embedded ids (e.g. Author, never in _EMBEDDED_LABELS) are
    silently skipped by Chroma's own .get() — nothing to update for those."""
    chroma_ids = [f"entity_{node_id}" for node_id in node_ids]
    existing = entities.get(ids=chroma_ids)
    if not existing["ids"]:
        return
    updated_metadatas = []
    for meta in existing["metadatas"]:
        source_papers = set((meta.get("source_papers") or "").split(","))
        source_papers.discard("")
        source_papers.discard(paper_id)
        updated_metadatas.append({**meta, "source_papers": ",".join(sorted(source_papers))})
    entities.update(ids=existing["ids"], metadatas=updated_metadatas)
