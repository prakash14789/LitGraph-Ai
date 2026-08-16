"""Integration tests for POST /ingest/arxiv (POLISH-004) — real HTTP via the
test_client fixture, with httpx.AsyncClient patched inside the route module
so the arXiv metadata/PDF fetches never hit the real network (same
MockTransport approach as test_seed_sample_papers.py). Celery dispatch is
mocked via ingest.py's own autouse fixture pattern, mirrored here."""

import uuid
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes import ingest as ingest_module
from src.models.extraction_job import ExtractionJob
from src.models.paper import Paper
from src.tasks.ingest_task import process_paper

pytestmark = pytest.mark.anyio

_ATTENTION_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<id>http://arxiv.org/abs/1706.03762v5</id>
<published>2017-06-12T17:57:34Z</published>
<title>  Attention Is All
  You Need  </title>
<summary>  We propose the Transformer.  </summary>
<author><name>Ashish Vaswani</name></author>
<author><name>Noam Shazeer</name></author>
</entry>
</feed>"""

_NOT_FOUND_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<id>http://arxiv.org/api/errors#incorrect_id_format_for_9999.99999</id>
<title>Error</title>
</entry>
</feed>"""

_FAKE_PDF = b"%PDF-1.4 fake pdf bytes"


@pytest.fixture(autouse=True)
def _no_real_dispatch(monkeypatch):
    monkeypatch.setattr(process_paper, "delay", MagicMock())


def _patch_arxiv_network(monkeypatch, *, metadata_xml: bytes, pdf_bytes: bytes | None):
    """Routes both the arXiv API call and the PDF download through a
    MockTransport, keyed on host — the route module always constructs a
    fresh httpx.AsyncClient() with no args, so patching the class itself is
    the only seam available."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if "export.arxiv.org" in str(request.url):
            return httpx.Response(200, content=metadata_xml)
        if "arxiv.org/pdf" in str(request.url):
            if pdf_bytes is None:
                return httpx.Response(404)
            return httpx.Response(200, content=pdf_bytes)
        raise AssertionError(f"unexpected request to {request.url}")

    transport = httpx.MockTransport(_handler)

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ingest_module.httpx, "AsyncClient", _PatchedAsyncClient)


async def _cleanup_paper(test_engine, paper_id: uuid.UUID) -> None:
    async with AsyncSession(bind=test_engine) as session:
        await session.execute(delete(ExtractionJob).where(ExtractionJob.paper_id == paper_id))
        await session.execute(delete(Paper).where(Paper.id == paper_id))
        await session.commit()


async def test_import_arxiv_queues_job_with_fetched_metadata(test_client, test_engine, monkeypatch):
    _patch_arxiv_network(monkeypatch, metadata_xml=_ATTENTION_ATOM, pdf_bytes=_FAKE_PDF)

    response = await test_client.post(
        "/api/v1/ingest/arxiv", json={"identifier": "https://arxiv.org/abs/1706.03762"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["filename"] == "1706.03762"  # resolved id, not the input URL
    paper_id = uuid.UUID(body["paper_id"])

    try:
        async with AsyncSession(bind=test_engine) as session:
            paper = await session.get(Paper, paper_id)
            assert paper is not None
            assert paper.title == "Attention Is All You Need"  # whitespace collapsed
            assert paper.authors == ["Ashish Vaswani", "Noam Shazeer"]
            assert paper.year == 2017
            assert paper.arxiv_id == "1706.03762"
    finally:
        await _cleanup_paper(test_engine, paper_id)


async def test_import_arxiv_rejects_unrecognized_identifier(test_client):
    response = await test_client.post("/api/v1/ingest/arxiv", json={"identifier": "not a url"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["paper_id"] is None


async def test_import_arxiv_rejects_when_arxiv_has_no_matching_paper(test_client, monkeypatch):
    _patch_arxiv_network(monkeypatch, metadata_xml=_NOT_FOUND_ATOM, pdf_bytes=None)

    response = await test_client.post("/api/v1/ingest/arxiv", json={"identifier": "9999.99999"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert "no arXiv paper found" in body["error"]


async def test_import_arxiv_returns_duplicate_for_existing_arxiv_id(test_client, test_engine):
    paper_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=paper_id,
                title="Attention Is All You Need",
                authors=[],
                pdf_path="x.pdf",
                arxiv_id="1706.03762",
            )
        )
        await session.commit()

    try:
        # No network patch applied — a real network call here would fail
        # the test with a connection error, structurally proving the
        # arxiv_id dedup check short-circuits before any fetch.
        response = await test_client.post("/api/v1/ingest/arxiv", json={"identifier": "1706.03762"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "duplicate"
        assert body["paper_id"] == str(paper_id)
    finally:
        await _cleanup_paper(test_engine, paper_id)
