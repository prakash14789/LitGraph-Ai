"""One-time backfill (POLISH-005) — groups every paper ingested before
collections existed into a single "Transformer/BERT Family — Core Set"
collection, so the Papers page filter has something real to show on day one.

Additive only, matches graph_writer.py/embedding_storage.py's new
collection_id parameters exactly:
- Postgres: creates the collection row (idempotent — reuses it by name if
  already run), UPDATEs collection_id only for unassigned papers whose
  title matches one of eval_dataset.json's 9 (see _target_titles below).
- Neo4j: SET collection_id on those papers' existing (:Paper) nodes only —
  never on Method/Dataset/Author/Metric (POLISH-005b's shared-entity
  decision: entities stay collection-agnostic).
- Chroma: patches collection_id into paper_chunks metadata for those
  papers' existing chunks via .update() — metadata patch only, no
  re-embedding, no entity_embeddings touched (same entity-agnostic reason).

No re-processing, no LLM calls, no vector regeneration anywhere in this
script — every write is a label on data that already exists.

Matches papers by exact title against eval_dataset.json's own 9-paper list
— NOT "every unassigned paper". First cut of this script did the latter and
swept 6 unrelated pre-existing rows (N-BEATS, DeepAR, a kidney-disease
paper, a duplicate ResNet upload, a stray personal PDF) into this
collection alongside the real 9, since this project's Postgres has more
history in it than just the eval set. Caught and reverted live 2026-08-15;
title-matching is the actual fix, not a defensive afterthought.

Usage: python -m scripts.backfill_core_collection
"""

import asyncio
import json
from pathlib import Path

import structlog
from sqlalchemy import select

from src.config import settings
from src.db import AsyncSessionLocal
from src.graph.connection import get_driver
from src.models.collection import Collection
from src.models.paper import Paper
from src.vectorstore.store import get_collection

logger = structlog.get_logger()

_COLLECTION_NAME = "Transformer/BERT Family — Core Set"
_COLLECTION_DESCRIPTION = (
    "The 9 foundational transformer/BERT-family papers ingested before "
    "POLISH-005's collection support existed (EVAL-001's eval_dataset.json "
    "paper set) — backfilled into one collection so they're organized "
    "rather than left unassigned."
)
_EVAL_DATASET_PATH = Path(__file__).resolve().parent.parent / "tests" / "eval" / "eval_dataset.json"


def _target_titles() -> set[str]:
    """The eval set's own 9 paper titles — the actual source of truth for
    "which papers belong in this collection", not "whatever's unassigned
    in Postgres today" (see module docstring for why that was wrong)."""
    data = json.loads(_EVAL_DATASET_PATH.read_text(encoding="utf-8"))
    return {p["title"] for p in data["papers"]}


async def _get_or_create_collection(session) -> Collection:
    existing = await session.execute(select(Collection).where(Collection.name == _COLLECTION_NAME))
    collection = existing.scalar_one_or_none()
    if collection is not None:
        return collection
    collection = Collection(name=_COLLECTION_NAME, description=_COLLECTION_DESCRIPTION)
    session.add(collection)
    await session.flush()
    return collection


async def _tag_neo4j(paper_ids: list[str], collection_id: str) -> None:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (p:Paper) WHERE p.paper_id IN $paper_ids "
            "SET p.collection_id = $collection_id RETURN count(p) AS n",
            paper_ids=paper_ids,
            collection_id=collection_id,
        )
        record = await result.single()
        logger.info("backfill.neo4j_tagged", papers_tagged=record["n"] if record else 0)


def _tag_chroma(paper_ids: list[str], collection_id: str) -> None:
    chunks = get_collection(settings.chroma_collection_chunks)
    tagged = 0
    for paper_id in paper_ids:
        existing = chunks.get(where={"paper_id": paper_id})
        if not existing["ids"]:
            continue
        metadatas = [{**m, "collection_id": collection_id} for m in existing["metadatas"]]
        chunks.update(ids=existing["ids"], metadatas=metadatas)
        tagged += len(existing["ids"])
    logger.info("backfill.chroma_tagged", chunks_tagged=tagged)


async def main() -> None:
    titles = _target_titles()
    async with AsyncSessionLocal() as session:
        collection = await _get_or_create_collection(session)
        collection_id = str(collection.id)

        candidates = await session.execute(
            select(Paper).where(Paper.collection_id.is_(None), Paper.title.in_(titles))
        )
        papers = candidates.scalars().all()
        paper_ids = [str(p.id) for p in papers]

        if not paper_ids:
            logger.info("backfill.nothing_to_do", collection_id=collection_id)
            await session.commit()
            return

        for paper in papers:
            paper.collection_id = collection.id
        await session.commit()
        logger.info(
            "backfill.postgres_tagged", collection_id=collection_id, paper_count=len(paper_ids)
        )

    await _tag_neo4j(paper_ids, collection_id)
    _tag_chroma(paper_ids, collection_id)
    logger.info("backfill.done", collection_id=collection_id, paper_count=len(paper_ids))


if __name__ == "__main__":
    asyncio.run(main())
