"""Integration test for POST /api/v1/query/compare (RETRIEVAL-006) — real
HTTP request, real Postgres/ChromaDB, mocked LLM. The one thing worth
proving for real here (that a mocked-response shape check alone wouldn't
catch) is the ticket's own acceptance criterion: both pipelines actually
run in parallel, so total latency is close to max(graphrag, vanilla), not
their sum — done by making the mocked LLM call sleep for a fixed duration
and asserting wall-clock time stays well under running it twice serially.
"""

import time
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.paper import IngestionStatus, Paper
from src.vectorstore.store import add_texts, get_collection

pytestmark = pytest.mark.anyio

_SLEEP_SECONDS = 0.3


async def test_compare_runs_both_pipelines_in_parallel(test_client, mock_llm_client, test_engine):
    def slow_answer(*args, **kwargs):
        time.sleep(_SLEEP_SECONDS)
        return "a compared answer"

    mock_llm_client.side_effect = slow_answer

    paper_id = str(uuid.uuid4())
    chunk_id = f"{paper_id}_0"
    chunks = get_collection(settings.chroma_collection_chunks)

    try:
        async with AsyncSession(bind=test_engine) as session:
            session.add(
                Paper(
                    id=uuid.UUID(paper_id),
                    title="Compare Test Paper",
                    authors=[],
                    pdf_path="/tmp/x.pdf",
                    ingestion_status=IngestionStatus.COMPLETED,
                )
            )
            await session.commit()

        add_texts(
            settings.chroma_collection_chunks,
            ids=[chunk_id],
            texts=["Widgets are small mechanical devices used across many machines."],
            metadatas=[{"paper_id": paper_id, "section_name": "introduction", "chunk_index": 0}],
        )

        started = time.monotonic()
        response = await test_client.post(
            "/api/v1/query/compare", json={"query": "What are widgets?"}
        )
        elapsed = time.monotonic() - started

        assert response.status_code == 200
        body = response.json()
        assert body["graphrag"]["answer"] == "a compared answer"
        assert body["vanilla"]["answer"] == "a compared answer"
        assert mock_llm_client.call_count == 2

        # serial would take >= 2 * _SLEEP_SECONDS plus each pipeline's own
        # real DB/Chroma/embedding overhead on top (measured ~0.9s+ for a
        # serial run); parallel measured ~0.48s. 1.8x the single sleep
        # (0.54s) sits well below a realistic serial total while leaving
        # comfortable margin above the ~1x-plus-overhead parallel case, so
        # it distinguishes the two without being flaky either direction.
        # The floor confirms the mocked sleep actually ran (not skipped).
        assert elapsed > _SLEEP_SECONDS * 0.9
        assert elapsed < _SLEEP_SECONDS * 1.8
        assert body["total_latency_ms"] >= int(_SLEEP_SECONDS * 1000)
    finally:
        chunks.delete(ids=[chunk_id])
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(Paper).where(Paper.id == uuid.UUID(paper_id)))
            await session.commit()
