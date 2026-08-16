"""Integration test for scripts/seed_sample_papers.py (EVAL-003) — real
Postgres for the idempotency check, mocked httpx for the download-error
acceptance criterion ("handles network errors"). Not a live-network test —
this script's actual downloads are meant to be exercised by running it for
real, same as review_extraction.py's own tests only check wiring."""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts import seed_sample_papers
from src.models.paper import IngestionStatus, Paper

pytestmark = pytest.mark.anyio


async def test_already_ingested_true_for_existing_source_id(test_engine):
    # Keyed on arxiv_id, not title — pipeline.py overwrites paper.title with
    # the PDF's own parsed title once a job runs ("BERT" -> "BERT:
    # Pre-training of Deep..."), so a title-based check would only work
    # once, breaking a second run's idempotency the moment the first job
    # actually completes.
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=uuid.uuid4(),
                title="BERT: Pre-training of Deep Bidirectional Transformers",
                authors=[],
                pdf_path="x.pdf",
                arxiv_id="1810.04805",
                ingestion_status=IngestionStatus.COMPLETED,
            )
        )
        await session.commit()

        assert await seed_sample_papers._already_ingested(session, "1810.04805") is True
        assert await seed_sample_papers._already_ingested(session, "1907.11692") is False


async def test_download_returns_none_on_http_error():
    def _raise(request):
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(_raise)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await seed_sample_papers._download(client, "BERT", "https://example.invalid/x.pdf")

    assert result is None


async def test_download_returns_none_for_non_pdf_response():
    def _respond(request):
        return httpx.Response(200, content=b"<html>not a pdf</html>")

    transport = httpx.MockTransport(_respond)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await seed_sample_papers._download(client, "BERT", "https://example.invalid/x.pdf")

    assert result is None


async def test_download_returns_content_for_valid_pdf():
    def _respond(request):
        return httpx.Response(200, content=b"%PDF-1.4 fake pdf bytes")

    transport = httpx.MockTransport(_respond)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await seed_sample_papers._download(client, "BERT", "https://example.invalid/x.pdf")

    assert result == b"%PDF-1.4 fake pdf bytes"
