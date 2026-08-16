"""Integration tests for POST /ingest/upload and GET /ingest/status/{job_id}
— real HTTP requests via httpx against the real FastAPI app and the real
test Postgres DB. Celery dispatch (process_paper.delay) is mocked — this
ticket's scope is "dispatch correctly", not "the task ran"; see
test_ingest_task.py for that."""

import uuid
from unittest.mock import MagicMock

import fitz
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.extraction_job import ExtractionJob
from src.models.paper import Paper
from src.repositories import extraction_job_repository
from src.tasks.ingest_task import process_paper

pytestmark = pytest.mark.anyio


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Test Paper Title", fontsize=16)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(autouse=True)
def _no_real_dispatch(monkeypatch):
    # process_paper is a shared Celery Task singleton — patching .delay on it
    # affects every import of it, no "where to patch" gotcha (this is
    # attribute mutation on a shared object, not rebinding a module name).
    monkeypatch.setattr(process_paper, "delay", MagicMock())


async def _cleanup_paper(test_engine, paper_id: uuid.UUID) -> None:
    async with AsyncSession(bind=test_engine) as session:
        await session.execute(delete(ExtractionJob).where(ExtractionJob.paper_id == paper_id))
        await session.execute(delete(Paper).where(Paper.id == paper_id))
        await session.commit()


async def test_upload_valid_pdf_returns_queued_job(test_client, test_engine):
    response = await test_client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("my special paper.pdf", _pdf_bytes(), "application/pdf"))],
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "queued"
    paper_id = uuid.UUID(body[0]["paper_id"])
    assert body[0]["job_id"]

    try:
        async with AsyncSession(bind=test_engine) as session:
            paper = await session.get(Paper, paper_id)
            assert paper is not None
            assert "my special paper" not in paper.pdf_path  # UUID filename, not user-provided
            assert paper.pdf_path.endswith(f"{paper_id}.pdf")
    finally:
        await _cleanup_paper(test_engine, paper_id)


async def test_upload_rejects_non_pdf(test_client):
    response = await test_client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("notes.txt", b"just some plain text", "text/plain"))],
    )
    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "rejected"
    assert body[0]["paper_id"] is None
    assert "not a valid PDF" in body[0]["error"]


async def test_upload_too_many_files_rejected(test_client, monkeypatch):
    monkeypatch.setattr(settings, "max_papers_per_upload", 1)
    files = [("files", (f"p{i}.pdf", _pdf_bytes(), "application/pdf")) for i in range(2)]
    response = await test_client.post("/api/v1/ingest/upload", files=files)
    assert response.status_code == 400


async def test_status_endpoint_returns_job(test_client, test_engine):
    upload = await test_client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("p.pdf", _pdf_bytes(), "application/pdf"))],
    )
    paper_id = uuid.UUID(upload.json()[0]["paper_id"])
    job_id = upload.json()[0]["job_id"]

    try:
        response = await test_client.get(f"/api/v1/ingest/status/{job_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == job_id
        assert body["status"] == "queued"
        assert body["entities_found"] == 0
    finally:
        await _cleanup_paper(test_engine, paper_id)


async def test_status_endpoint_404_for_unknown_job(test_client):
    response = await test_client.get(f"/api/v1/ingest/status/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_upload_same_content_twice_returns_duplicate(test_client, test_engine):
    # POLISH-001 live finding: the same PDF re-uploaded (different filename,
    # identical bytes) used to silently create a second Paper row and queue
    # a second full extraction run.
    content = _pdf_bytes()
    first = await test_client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("original-name.pdf", content, "application/pdf"))],
    )
    paper_id = uuid.UUID(first.json()[0]["paper_id"])

    try:
        assert first.json()[0]["status"] == "queued"

        second = await test_client.post(
            "/api/v1/ingest/upload",
            files=[("files", ("a-completely-different-name.pdf", content, "application/pdf"))],
        )
        assert second.status_code == 200
        body = second.json()[0]
        assert body["status"] == "duplicate"
        assert body["paper_id"] == str(paper_id)
        assert body["job_id"] is None  # no second job was queued

        async with AsyncSession(bind=test_engine) as session:
            result = await session.execute(select(Paper).where(Paper.content_hash.isnot(None)))
            matching = [p for p in result.scalars().all() if p.id == paper_id]
            assert len(matching) == 1  # exactly one Paper row for this content, not two
    finally:
        await _cleanup_paper(test_engine, paper_id)


async def test_atomicity_failed_job_insert_rolls_back_paper(test_client, test_engine, monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated ExtractionJob insert failure")

    monkeypatch.setattr(extraction_job_repository, "create", _boom)

    # POLISH-001's catch-all handler (src/api/middleware.py) now converts
    # this into a clean 500 instead of letting the raw exception reach the
    # caller — the atomicity guarantee this test actually checks (the Paper
    # row rolling back) is unaffected either way, since that rollback
    # happens inside the route's own try/except, before the exception ever
    # reaches the middleware.
    response = await test_client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("atomicity-test.pdf", _pdf_bytes(), "application/pdf"))],
    )
    assert response.status_code == 500

    async with AsyncSession(bind=test_engine) as session:
        result = await session.execute(select(Paper).where(Paper.title == "atomicity-test"))
        assert (
            result.scalar_one_or_none() is None
        )  # Paper must not survive the ExtractionJob failure
