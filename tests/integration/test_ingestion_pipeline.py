"""Integration test for src.services.ingestion.pipeline.run_pipeline — the
real parse->chunk->embed logic, against the real test Postgres DB and the
real ChromaDB container (not mocked — that's the point of this test)."""

import uuid

import fitz
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.models.extraction_job import ExtractionJob, JobStatus
from src.models.paper import IngestionStatus, Paper
from src.services.ingestion import pipeline
from src.vectorstore.store import add_texts, get_collection

pytestmark = pytest.mark.anyio


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
