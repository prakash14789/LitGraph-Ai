"""Integration tests for POST/GET/PATCH/DELETE /collections and PATCH
/papers/{id} (POLISH-005) — real HTTP requests against the real test
Postgres DB, same pattern as test_papers_api.py."""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.collection import Collection
from src.models.paper import IngestionStatus, Paper

pytestmark = pytest.mark.anyio


async def _cleanup(test_engine, collection_id: uuid.UUID, *paper_ids: uuid.UUID) -> None:
    async with AsyncSession(bind=test_engine) as session:
        for paper_id in paper_ids:
            await session.execute(delete(Paper).where(Paper.id == paper_id))
        await session.execute(delete(Collection).where(Collection.id == collection_id))
        await session.commit()


async def test_create_list_rename_delete_collection(test_client, test_engine):
    create = await test_client.post("/api/v1/collections", json={"name": "CT collection"})
    assert create.status_code == 201
    body = create.json()
    collection_id = uuid.UUID(body["id"])
    assert body["name"] == "CT collection"
    assert body["paper_count"] == 0

    try:
        listed = await test_client.get("/api/v1/collections")
        assert listed.status_code == 200
        assert any(c["id"] == str(collection_id) for c in listed.json())

        renamed = await test_client.patch(
            f"/api/v1/collections/{collection_id}", json={"name": "CT renamed"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "CT renamed"

        deleted = await test_client.delete(f"/api/v1/collections/{collection_id}")
        assert deleted.status_code == 204

        gone = await test_client.get("/api/v1/collections")
        assert not any(c["id"] == str(collection_id) for c in gone.json())
    finally:
        # Already deleted in the happy path — harmless no-op 404 if so, but
        # covers the case an assertion above failed before the delete call.
        await test_client.delete(f"/api/v1/collections/{collection_id}")


async def test_update_unknown_collection_returns_404(test_client):
    response = await test_client.patch(f"/api/v1/collections/{uuid.uuid4()}", json={"name": "nope"})
    assert response.status_code == 404


async def test_delete_unknown_collection_returns_404(test_client):
    response = await test_client.delete(f"/api/v1/collections/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_deleting_collection_unassigns_papers_not_deletes_them(test_client, test_engine):
    collection_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(Collection(id=collection_id, name="CT to-delete"))
        session.add(
            Paper(
                id=paper_id,
                title="CT paper",
                authors=[],
                pdf_path="/tmp/ct.pdf",
                ingestion_status=IngestionStatus.COMPLETED,
                collection_id=collection_id,
            )
        )
        await session.commit()

    try:
        response = await test_client.delete(f"/api/v1/collections/{collection_id}")
        assert response.status_code == 204

        async with AsyncSession(bind=test_engine) as session:
            paper = await session.get(Paper, paper_id)
            assert paper is not None  # not cascade-deleted
            assert paper.collection_id is None  # FK ondelete=SET NULL did its job
    finally:
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(Paper).where(Paper.id == paper_id))
            await session.commit()


async def test_patch_paper_assigns_and_unassigns_collection(test_client, test_engine):
    paper_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=paper_id,
                title="CT assign target",
                authors=[],
                pdf_path="/tmp/ct2.pdf",
                ingestion_status=IngestionStatus.COMPLETED,
            )
        )
        await session.commit()

    collection_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(Collection(id=collection_id, name="CT assign target collection"))
        await session.commit()

    try:
        assign = await test_client.patch(
            f"/api/v1/papers/{paper_id}", json={"collection_id": str(collection_id)}
        )
        assert assign.status_code == 200
        assert assign.json()["collection_id"] == str(collection_id)

        unassign = await test_client.patch(
            f"/api/v1/papers/{paper_id}", json={"collection_id": None}
        )
        assert unassign.status_code == 200
        assert unassign.json()["collection_id"] is None
    finally:
        await _cleanup(test_engine, collection_id, paper_id)


async def test_patch_unknown_paper_returns_404(test_client):
    response = await test_client.patch(
        f"/api/v1/papers/{uuid.uuid4()}", json={"collection_id": None}
    )
    assert response.status_code == 404
