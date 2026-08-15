"""POST/GET/PATCH/DELETE /collections (POLISH-005, organizational only).

Deliberately does NOT touch Neo4j or ChromaDB — a collection here is a pure
Postgres grouping (name papers belong to), same MVP scope as INGEST-007's
`GET /papers?collection_id=` filter already covers. Chat/Graph retrieval
stays global; see vector_retriever.py/graph_retriever.py's own docstrings
for the POLISH-005b scoping decision this ticket explicitly does not make.

Deleting a collection does not delete its papers — `papers.collection_id`'s
`ondelete="SET NULL"` (src/models/paper.py) already un-assigns them back to
"no collection" at the DB level, no cascade logic needed here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.collections import CollectionCreate, CollectionResponse, CollectionUpdate
from src.models.collection import Collection
from src.models.paper import Paper
from src.repositories import collection_repository

router = APIRouter()


async def _paper_counts(db: AsyncSession, collection_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not collection_ids:
        return {}
    result = await db.execute(
        select(Paper.collection_id, func.count(Paper.id))
        .where(Paper.collection_id.in_(collection_ids))
        .group_by(Paper.collection_id)
    )
    return dict(result.all())


def _to_response(collection: Collection, paper_count: int) -> CollectionResponse:
    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        created_at=collection.created_at,
        paper_count=paper_count,
    )


@router.post("/collections", response_model=CollectionResponse, status_code=201)
async def create_collection(
    request: CollectionCreate, db: AsyncSession = Depends(get_db)
) -> CollectionResponse:
    collection = await collection_repository.create(
        db, name=request.name, description=request.description
    )
    return _to_response(collection, paper_count=0)


@router.get("/collections", response_model=list[CollectionResponse])
async def list_collections(db: AsyncSession = Depends(get_db)) -> list[CollectionResponse]:
    collections = await collection_repository.list(db, limit=1000)
    counts = await _paper_counts(db, [c.id for c in collections])
    return [_to_response(c, counts.get(c.id, 0)) for c in collections]


@router.patch("/collections/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: uuid.UUID, request: CollectionUpdate, db: AsyncSession = Depends(get_db)
) -> CollectionResponse:
    collection = await collection_repository.get_by_id(db, collection_id)
    if collection is None:
        raise HTTPException(404, "collection not found")

    if request.name is not None:
        collection.name = request.name
    if request.description is not None:
        collection.description = request.description
    await db.flush()

    counts = await _paper_counts(db, [collection_id])
    return _to_response(collection, counts.get(collection_id, 0))


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(collection_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await collection_repository.delete(db, collection_id)
    if not deleted:
        raise HTTPException(404, "collection not found")
