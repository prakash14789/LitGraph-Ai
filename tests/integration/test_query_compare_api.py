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
        # POLISH-006 added a 3rd call: graphrag's own path now makes 2
        # sequential LLM calls (answer, then the faithfulness self-audit on
        # it) where it used to make 1; vanilla still makes 1.
        assert mock_llm_client.call_count == 3

        # graphrag's own path is now the dominant one — 2 sequential sleeps
        # (answer + faithfulness) vs vanilla's 1 — so a genuinely parallel
        # compare should track ~2x sleep, not grow further for vanilla
        # running alongside it. Serial (all 3 calls back-to-back) would be
        # >= 3x sleep plus overhead. Same empirical-margin approach as
        # before POLISH-006 (was 1.8x a single sleep for a 1-vs-1 setup);
        # scaled to the new 2-vs-1 dominant path.
        # The floor confirms both of graphrag's own sequential calls ran.
        #
        # COMPARE-002 added a real, permanent extra step after gather(): an
        # INSERT persisting the query_log row the vote endpoint attaches to.
        # That's sequential (can't run concurrently with the two pipelines —
        # it needs their finished answers), so it's a flat addition to
        # elapsed, not a multiple of _SLEEP_SECONDS — a fixed-ms buffer
        # models that better than bumping the multiplier would.
        _QUERY_LOG_INSERT_BUFFER = 0.2
        assert elapsed > _SLEEP_SECONDS * 2 * 0.9
        assert elapsed < _SLEEP_SECONDS * 2 * 1.8 + _QUERY_LOG_INSERT_BUFFER
        assert body["total_latency_ms"] >= int(_SLEEP_SECONDS * 2 * 1000)
        assert body["query_log_id"]
    finally:
        chunks.delete(ids=[chunk_id])
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(Paper).where(Paper.id == uuid.UUID(paper_id)))
            await session.commit()


async def test_vote_compare_stores_and_allows_changing_verdict(test_client, test_engine):
    """COMPARE-002. Doesn't need a real compare run — inserts a query_log
    row directly and hits the vote endpoint against it, since the thing
    under test is the vote endpoint's own persistence, not the compare
    pipeline (already covered above)."""
    from src.models.query_log import QueryLog

    log_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(QueryLog(id=log_id, query_text="does voting work?"))
        await session.commit()

    try:
        resp = await test_client.post(
            f"/api/v1/query/compare/{log_id}/vote", json={"verdict": "graphrag"}
        )
        assert resp.status_code == 204

        async with AsyncSession(bind=test_engine) as session:
            row = await session.get(QueryLog, log_id)
            assert row.compare_verdict.value == "graphrag"

        # user can change their vote within the session — re-POST overwrites
        resp = await test_client.post(
            f"/api/v1/query/compare/{log_id}/vote", json={"verdict": "tie_bad"}
        )
        assert resp.status_code == 204
        async with AsyncSession(bind=test_engine) as session:
            row = await session.get(QueryLog, log_id)
            assert row.compare_verdict.value == "tie_bad"
    finally:
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(QueryLog).where(QueryLog.id == log_id))
            await session.commit()


async def test_vote_compare_unknown_id_returns_404(test_client):
    resp = await test_client.post(
        f"/api/v1/query/compare/{uuid.uuid4()}/vote", json={"verdict": "vanilla"}
    )
    assert resp.status_code == 404
