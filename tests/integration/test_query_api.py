"""Integration test for POST /query/vanilla — real HTTP request, real
ChromaDB, mocked LLM (mock_llm_client) so no real API calls happen."""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.paper import IngestionStatus, Paper
from src.vectorstore.store import add_texts, get_collection

pytestmark = pytest.mark.anyio

_TEST_PAPER_ID = str(uuid.uuid4())
_CHUNK_ID = f"{_TEST_PAPER_ID}_0"


@pytest.fixture(autouse=True)
async def _seed_chunk_and_paper(test_engine):
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=uuid.UUID(_TEST_PAPER_ID),
                title="Widget Theory Paper",
                authors=[],
                pdf_path="/tmp/x.pdf",
                ingestion_status=IngestionStatus.COMPLETED,
            )
        )
        await session.commit()

    add_texts(
        settings.chroma_collection_chunks,
        ids=[_CHUNK_ID],
        texts=["Widgets are small mechanical devices used in many machines."],
        metadatas=[
            {
                "paper_id": _TEST_PAPER_ID,
                "section_name": "introduction",
                "chunk_index": 0,
                "page_number": 1,
            }
        ],
    )

    yield

    async with AsyncSession(bind=test_engine) as session:
        await session.execute(delete(Paper).where(Paper.id == uuid.UUID(_TEST_PAPER_ID)))
        await session.commit()
    get_collection(settings.chroma_collection_chunks).delete(ids=[_CHUNK_ID])


async def test_vanilla_query_returns_answer_with_sources(test_client, mock_llm_client):
    mock_llm_client.return_value = "Widgets are mechanical devices. [1]"

    response = await test_client.post(
        "/api/v1/query/vanilla", json={"query": "What are widgets?", "top_k": 5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Widgets are mechanical devices. [1]"
    assert len(body["sources"]) >= 1
    assert body["sources"][0]["paper_title"] == "Widget Theory Paper"
    assert body["latency_ms"] >= 0
    assert body["context_tokens"] > 0


async def test_vanilla_query_collection_id_never_returns_other_collections_chunks(
    test_client, mock_llm_client
):
    # POLISH-005b's own AC, literally: "Query in Collection A never returns
    # citations from papers only in Collection B". Second paper's chunk is
    # untagged (no collection_id at all) — proves "scoped to A" means only
    # A, not "A plus anything ungrouped" either.
    mock_llm_client.return_value = "some answer"
    other_paper_id = str(uuid.uuid4())
    other_chunk_id = f"{other_paper_id}_0"
    add_texts(
        settings.chroma_collection_chunks,
        ids=[other_chunk_id],
        texts=["Widgets are small mechanical devices used in many machines, definitely."],
        metadatas=[{"paper_id": other_paper_id, "section_name": "introduction", "chunk_index": 0}],
    )

    try:
        response = await test_client.post(
            "/api/v1/query/vanilla",
            json={"query": "What are widgets?", "top_k": 5, "collection_id": str(uuid.uuid4())},
        )
        assert response.status_code == 200
        paper_ids = {s["paper_id"] for s in response.json()["sources"]}
        assert other_paper_id not in paper_ids
        assert _TEST_PAPER_ID not in paper_ids  # untagged too — neither leaks in
    finally:
        get_collection(settings.chroma_collection_chunks).delete(ids=[other_chunk_id])
