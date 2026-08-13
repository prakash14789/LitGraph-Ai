"""Integration tests for GET /papers, GET /papers/{id}, DELETE /papers/{id}
— real HTTP requests via httpx against the real FastAPI app, the real test
Postgres DB, the real ChromaDB container, and the real Neo4j container.

The shared-entity deletion test creates its own Method/Claim nodes by hand
instead of ingesting through the real pipeline — EXTRACT-004 (graph writer)
hasn't landed yet, so nothing in this codebase writes (:Paper) nodes to Neo4j
today. Nodes here are built to match the §4.2 schema exactly, so the
orphan-preserving cascade logic is proven against real Neo4j now rather than
left unbuilt/untested until EXTRACT-004 exists.
"""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.graph.connection import get_driver
from src.models.collection import Collection
from src.models.extraction_job import ExtractionJob
from src.models.paper import IngestionStatus, Paper
from src.vectorstore.store import add_texts, get_collection

pytestmark = pytest.mark.anyio


async def _create_paper(test_engine, pdf_path: str, **overrides) -> uuid.UUID:
    paper_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=paper_id,
                title=overrides.get("title", "placeholder"),
                authors=[],
                pdf_path=pdf_path,
                ingestion_status=IngestionStatus.COMPLETED,
                collection_id=overrides.get("collection_id"),
            )
        )
        await session.commit()
    return paper_id


async def _cleanup_paper(test_engine, paper_id: uuid.UUID) -> None:
    async with AsyncSession(bind=test_engine) as session:
        await session.execute(delete(ExtractionJob).where(ExtractionJob.paper_id == paper_id))
        await session.execute(delete(Paper).where(Paper.id == paper_id))
        await session.commit()


async def test_list_papers_filterable_by_collection(test_client, test_engine):
    collection_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(Collection(id=collection_id, name="test-collection"))
        await session.commit()

    in_collection = await _create_paper(test_engine, "/tmp/a.pdf", collection_id=collection_id)
    outside = await _create_paper(test_engine, "/tmp/b.pdf")

    try:
        response = await test_client.get("/api/v1/papers", params={"collection_id": collection_id})
        assert response.status_code == 200
        ids = {p["id"] for p in response.json()}
        assert ids == {str(in_collection)}

        response = await test_client.get("/api/v1/papers")
        ids = {p["id"] for p in response.json()}
        assert {str(in_collection), str(outside)} <= ids
    finally:
        await _cleanup_paper(test_engine, in_collection)
        await _cleanup_paper(test_engine, outside)
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(Collection).where(Collection.id == collection_id))
            await session.commit()


async def test_get_paper_detail_returns_sections_and_no_entities_yet(test_client, test_engine):
    paper_id = await _create_paper(test_engine, "/tmp/c.pdf", title="Detail Test Paper")

    try:
        response = await test_client.get(f"/api/v1/papers/{paper_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Detail Test Paper"
        # No (:Paper) node exists in Neo4j yet — EXTRACT-004 not built — so
        # these are correctly empty, not faked.
        assert body["entities"] == []
        assert body["relationships"] == []
    finally:
        await _cleanup_paper(test_engine, paper_id)


async def test_get_paper_detail_404_for_unknown_paper(test_client):
    response = await test_client.get(f"/api/v1/papers/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_nonexistent_paper_returns_404(test_client):
    response = await test_client.delete(f"/api/v1/papers/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_removes_pdf_postgres_row_and_chunks(test_client, test_engine, tmp_path):
    pdf_path = tmp_path / "delete-me.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    paper_id = await _create_paper(test_engine, str(pdf_path))

    add_texts(
        settings.chroma_collection_chunks,
        ids=[f"{paper_id}_0"],
        texts=["a chunk belonging to the paper being deleted"],
        metadatas=[{"paper_id": str(paper_id), "chunk_index": 0}],
    )

    response = await test_client.delete(f"/api/v1/papers/{paper_id}")
    assert response.status_code == 204

    assert not pdf_path.exists()
    async with AsyncSession(bind=test_engine) as session:
        assert await session.get(Paper, paper_id) is None

    chunks = get_collection(settings.chroma_collection_chunks)
    assert chunks.get(where={"paper_id": str(paper_id)})["ids"] == []


async def test_delete_paper_preserves_shared_entity_and_removes_orphan(
    test_client, test_engine, tmp_path
):
    pdf_a = tmp_path / "paper-a.pdf"
    pdf_a.write_bytes(b"%PDF-1.4 fake a")
    paper_a_id = await _create_paper(test_engine, str(pdf_a))
    paper_b_id = await _create_paper(test_engine, "/tmp/paper-b.pdf")

    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            """
            CREATE (pa:Paper {paper_id: $a})
            CREATE (pb:Paper {paper_id: $b})
            CREATE (m:Method {canonical_name: 'INGEST-007-TEST-METHOD', category: 'test'})
            CREATE (c:Claim {text: 'INGEST-007-TEST-ORPHAN-CLAIM', claim_type: 'RESULT'})
            CREATE (pa)-[:USES_METHOD {confidence: 0.9}]->(m)
            CREATE (pb)-[:USES_METHOD {confidence: 0.8}]->(m)
            CREATE (pa)-[:HAS_CLAIM]->(c)
            """,
            a=str(paper_a_id),
            b=str(paper_b_id),
        )

    try:
        response = await test_client.delete(f"/api/v1/papers/{paper_a_id}")
        assert response.status_code == 204

        async with driver.session() as session:
            result = await session.run(
                "MATCH (m:Method {canonical_name: 'INGEST-007-TEST-METHOD'}) RETURN count(m) AS c"
            )
            assert (await result.single())["c"] == 1  # shared entity survives

            result = await session.run(
                "MATCH (c:Claim {text: 'INGEST-007-TEST-ORPHAN-CLAIM'}) RETURN count(c) AS c"
            )
            assert (await result.single())["c"] == 0  # fully-orphaned entity removed

            result = await session.run(
                "MATCH (p:Paper {paper_id: $id}) RETURN count(p) AS c", id=str(paper_a_id)
            )
            assert (await result.single())["c"] == 0  # this paper's own node gone

            # still findable via the surviving paper
            result = await session.run(
                "MATCH (:Paper {paper_id: $id})-[:USES_METHOD]->(m:Method) "
                "RETURN m.canonical_name AS name",
                id=str(paper_b_id),
            )
            assert (await result.single())["name"] == "INGEST-007-TEST-METHOD"
    finally:
        async with driver.session() as session:
            await session.run(
                "MATCH (n) WHERE n.paper_id IN $ids "
                "OR n.canonical_name = 'INGEST-007-TEST-METHOD' "
                "OR n.text = 'INGEST-007-TEST-ORPHAN-CLAIM' "
                "DETACH DELETE n",
                ids=[str(paper_a_id), str(paper_b_id)],
            )
        await _cleanup_paper(test_engine, paper_a_id)
        await _cleanup_paper(test_engine, paper_b_id)
