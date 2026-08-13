"""Integration test for src.services.ingestion.pipeline.run_pipeline — the
real parse->chunk->embed logic, against the real test Postgres DB and the
real ChromaDB container (not mocked — that's the point of this test).

test_pipeline_extracts_and_writes_real_graph (EXTRACT-005) goes further:
real LLM calls too, real Neo4j writes — no mocks anywhere in that one test,
proving the full parse->chunk->embed->extract->relate->resolve->write chain
actually connects end to end, not just that each piece works in isolation
(every other piece already had its own live-tested proof — EXTRACT-001
through 004 — but nothing had run them back to back through the real
pipeline until this ticket)."""

import time
import uuid

import fitz
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.graph.connection import get_driver
from src.models.extraction_job import ExtractionJob, JobStatus
from src.models.paper import IngestionStatus, Paper
from src.services.ingestion import pipeline
from src.vectorstore.store import add_texts, get_collection

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("close_neo4j_driver_after_test")]


def _build_pdf(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("A Test Paper About Widgets", 18, 30),
        ("Abstract", 13, 20),
        ("This paper studies widgets extensively across many use cases.", 10, 30),
        ("Introduction", 13, 20),
        ("Widgets have been studied for decades by many researchers worldwide today.", 10, 30),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(path)
    doc.close()


@pytest.fixture(autouse=True)
def _pipeline_uses_test_db(monkeypatch, test_engine):
    """run_pipeline opens its own session via AsyncSessionLocal (module-
    level, bound to the real dev DB by default) — point that at the test
    engine instead. Patched where it's USED (src.services.ingestion.pipeline),
    not where it's defined (src.db): `from x import y` binds pipeline's own
    name, so patching src.db wouldn't reach it — same lesson as SETUP-009's
    mock_llm_client bug."""
    test_sessionmaker = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, class_=AsyncSession
    )
    monkeypatch.setattr(pipeline, "AsyncSessionLocal", test_sessionmaker)


async def _create_paper_and_job(test_engine, pdf_path: str) -> tuple[uuid.UUID, uuid.UUID]:
    paper_id, job_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=paper_id,
                title="placeholder",
                authors=[],
                pdf_path=pdf_path,
                ingestion_status=IngestionStatus.PENDING,
            )
        )
        await session.flush()
        session.add(ExtractionJob(id=job_id, paper_id=paper_id, status=JobStatus.QUEUED))
        await session.commit()
    return paper_id, job_id


async def _cleanup(test_engine, paper_id: uuid.UUID, job_id: uuid.UUID) -> None:
    async with AsyncSession(bind=test_engine) as session:
        await session.execute(delete(ExtractionJob).where(ExtractionJob.id == job_id))
        await session.execute(delete(Paper).where(Paper.id == paper_id))
        await session.commit()
    collection = get_collection(settings.chroma_collection_chunks)
    existing = collection.get(where={"paper_id": str(paper_id)})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])


async def test_pipeline_completes_and_stores_chunks(test_engine, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    _build_pdf(str(pdf_path))
    paper_id, job_id = await _create_paper_and_job(test_engine, str(pdf_path))

    try:
        await pipeline.run_pipeline(str(job_id))

        async with AsyncSession(bind=test_engine) as session:
            job = await session.get(ExtractionJob, job_id)
            paper = await session.get(Paper, paper_id)

            assert job.status == JobStatus.COMPLETED
            assert job.started_at is not None
            assert job.completed_at is not None
            assert paper.ingestion_status == IngestionStatus.COMPLETED
            assert paper.title == "A Test Paper About Widgets"
            assert paper.raw_text
            assert paper.sections

        collection = get_collection(settings.chroma_collection_chunks)
        stored = collection.get(where={"paper_id": str(paper_id)})
        assert len(stored["ids"]) > 0
    finally:
        await _cleanup(test_engine, paper_id, job_id)


async def test_pipeline_marks_failed_on_bad_pdf_path(test_engine):
    paper_id, job_id = await _create_paper_and_job(test_engine, "/does/not/exist.pdf")

    try:
        await pipeline.run_pipeline(str(job_id))

        async with AsyncSession(bind=test_engine) as session:
            job = await session.get(ExtractionJob, job_id)
            paper = await session.get(Paper, paper_id)
            assert job.status == JobStatus.FAILED
            assert job.error_message
            assert paper.ingestion_status == IngestionStatus.FAILED
    finally:
        await _cleanup(test_engine, paper_id, job_id)


async def test_pipeline_unknown_job_id_is_a_noop(test_engine):
    # Shouldn't raise — just logs and returns.
    await pipeline.run_pipeline(str(uuid.uuid4()))


async def test_pipeline_cleans_up_partial_chunks_on_failure(test_engine, tmp_path, monkeypatch):
    """Simulates embedding partially succeeding (one chunk actually written
    to Chroma) before a later batch blows up — the acceptance criterion this
    ticket adds: no orphaned chunks survive a failed job."""
    pdf_path = tmp_path / "sample.pdf"
    _build_pdf(str(pdf_path))
    paper_id, job_id = await _create_paper_and_job(test_engine, str(pdf_path))

    def _fake_store_chunks(pid: str, chunks) -> int:
        add_texts(
            settings.chroma_collection_chunks,
            ids=[f"{pid}_0"],
            texts=["a chunk that made it in before things broke"],
            metadatas=[{"paper_id": pid, "section_name": "introduction", "chunk_index": 0}],
        )
        raise RuntimeError("simulated embedding failure mid-batch")

    monkeypatch.setattr(pipeline, "store_chunks", _fake_store_chunks)

    try:
        await pipeline.run_pipeline(str(job_id))

        async with AsyncSession(bind=test_engine) as session:
            job = await session.get(ExtractionJob, job_id)
            assert job.status == JobStatus.FAILED
            assert "simulated embedding failure" in job.error_message

        collection = get_collection(settings.chroma_collection_chunks)
        remaining = collection.get(where={"paper_id": str(paper_id)})
        assert remaining["ids"] == []  # the partially-embedded chunk was cleaned up
    finally:
        await _cleanup(test_engine, paper_id, job_id)


def _build_widgetnet_pdf(path: str) -> None:
    """Content shaped to reliably elicit one clear Method + one clear
    Dataset + an INTRODUCES/EVALUATES_ON relation — a made-up name
    (WidgetNet-9000) so this can't collide with a real paper the LLM
    already knows about from training data."""
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for text, size, step in [
        ("WidgetNet: A Study of Widget Classification", 18, 30),
        ("Abstract", 13, 20),
        (
            "We propose WidgetNet-9000, a novel transformer-based architecture for "
            "widget classification. We evaluate WidgetNet-9000 on the WidgetBench-2024 "
            "benchmark dataset and achieve 95.2% accuracy, outperforming prior baselines.",
            10,
            50,
        ),
        ("Method", 13, 20),
        (
            "WidgetNet-9000 uses a transformer encoder followed by a classification "
            "head to categorize widgets into their respective classes.",
            10,
            40,
        ),
    ]:
        page.insert_text((72, y), text, fontsize=size)
        y += step
    doc.save(path)
    doc.close()


async def test_pipeline_extracts_and_writes_real_graph(test_engine, tmp_path):
    """EXTRACT-005's own acceptance criterion, proven live: real LLM calls
    (no mock_llm_client), real Neo4j writes, real Chroma entity_embeddings —
    the full chain, not a single module in isolation. Cleans up its own
    Neo4j nodes and Chroma entity rows; a WIDGETNET-TEST- prefixed name
    keeps this from colliding with anything real."""
    pdf_path = tmp_path / "widgetnet.pdf"
    _build_widgetnet_pdf(str(pdf_path))
    paper_id, job_id = await _create_paper_and_job(test_engine, str(pdf_path))

    try:
        started = time.monotonic()
        await pipeline.run_pipeline(str(job_id))
        elapsed = time.monotonic() - started
        assert elapsed < 90  # ticket's own end-to-end budget, excluding queue wait

        async with AsyncSession(bind=test_engine) as session:
            job = await session.get(ExtractionJob, job_id)
            assert job.status == JobStatus.COMPLETED
            assert job.entities_found > 0  # real extraction found something, not a no-op

        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (p:Paper {paper_id: $id})-[r]->(m:Method) "
                "WHERE toLower(m.canonical_name) CONTAINS 'widgetnet' "
                "RETURN elementId(m) AS method_id, type(r) AS rel_type, "
                "       m.embedding IS NOT NULL AS has_embedding "
                "LIMIT 1",
                id=str(paper_id),
            )
            # LIMIT 1, not a bare single(): extraction can legitimately
            # produce more than one WidgetNet-ish Method node (e.g. "WidgetNet"
            # and "WidgetNet-9000" both extracted, resolution shortlisted them
            # via the suffix-variant heuristic but the LLM verification call
            # didn't confirm the merge that run — real, observed live; the
            # resolver's designed-safe fallback is to keep them separate
            # rather than merge on an inconclusive answer) — any one of them
            # is sufficient proof the graph write happened.
            record = await result.single()
        assert record is not None, "no WidgetNet-9000 Method node/relation found in Neo4j"
        assert record["has_embedding"]
        method_id = record["method_id"]

        entities = get_collection(settings.chroma_collection_entities)
        chroma_record = entities.get(ids=[f"entity_{method_id}"], include=["metadatas"])
        assert chroma_record["ids"] == [f"entity_{method_id}"]  # graph_writer's Chroma write landed
        assert chroma_record["metadatas"][0]["entity_type"] == "Method"
    finally:
        # Scoped deletes only, never a blanket "delete every neighbor" —
        # this runs against the same dev Neo4j real data lives in (no
        # separate test instance). Same orphan-safety logic as
        # DELETE_PAPER_CASCADE (INGEST-007): only deletes a Method/Dataset
        # connected to THIS test's paper if it has no connection to any
        # OTHER paper, so a genuinely shared/real entity is never at risk
        # even if cross-paper relation extraction linked to one. Earlier
        # version of this cleanup matched by name substring
        # ("widgetnet"/"widgetbench") and missed entities the LLM extracted
        # under other names (e.g. "transformer", "classification head" from
        # the Method section text) — found live, those leaked into the dev
        # graph across repeated runs and were cleaned up by hand once.
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (p:Paper {paper_id: $id})-[]->(n) "
                "WHERE (n:Method OR n:Dataset) AND NOT EXISTS { "
                "  MATCH (other:Paper)-[]->(n) WHERE other.paper_id <> $id "
                "} "
                "RETURN DISTINCT elementId(n) AS id",
                id=str(paper_id),
            )
            entity_ids = [r["id"] async for r in result]

            await session.run("MATCH (p:Paper {paper_id: $id}) DETACH DELETE p", id=str(paper_id))
            await session.run(
                "MATCH (n:Claim {source_paper_id: $id}) DETACH DELETE n", id=str(paper_id)
            )
            if entity_ids:
                await session.run(
                    "MATCH (n) WHERE elementId(n) IN $ids DETACH DELETE n", ids=entity_ids
                )

        if entity_ids:
            get_collection(settings.chroma_collection_entities).delete(
                ids=[f"entity_{i}" for i in entity_ids]
            )
        await _cleanup(test_engine, paper_id, job_id)
