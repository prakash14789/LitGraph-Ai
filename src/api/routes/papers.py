"""GET /papers, GET /papers/{id}, DELETE /papers/{id}."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.papers import (
    PaperDetail,
    PaperEntity,
    PaperListItem,
    PaperRelationship,
    PaperUpdate,
)
from src.graph.connection import get_driver
from src.graph.queries import PAPER_SUBGRAPH
from src.models.paper import Paper
from src.repositories import paper_repository
from src.services.papers.deletion import delete_paper as delete_paper_cascade

router = APIRouter()


def _list_item(paper: Paper) -> PaperListItem:
    return PaperListItem(
        id=paper.id,
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        venue=paper.venue,
        ingestion_status=paper.ingestion_status.value,
        collection_id=paper.collection_id,
        created_at=paper.created_at,
    )


@router.get("/papers", response_model=list[PaperListItem])
async def list_papers(
    collection_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[PaperListItem]:
    query = select(Paper).order_by(Paper.created_at.desc())
    if collection_id is not None:
        query = query.where(Paper.collection_id == collection_id)
    result = await db.execute(query)
    return [_list_item(p) for p in result.scalars().all()]


@router.get("/papers/{paper_id}", response_model=PaperDetail)
async def get_paper(paper_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> PaperDetail:
    paper = await paper_repository.get_by_id(db, paper_id)
    if paper is None:
        raise HTTPException(404, "paper not found")

    entities: dict[str, PaperEntity] = {}
    relationships: list[PaperRelationship] = []
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(PAPER_SUBGRAPH, paper_id=str(paper_id))
        async for record in result:
            entities[record["id"]] = PaperEntity(
                id=record["id"], type=record["labels"][0], name=record["name"]
            )
            relationships.append(
                PaperRelationship(
                    type=record["rel_type"],
                    source=str(paper_id) if record["from_paper"] else record["id"],
                    target=record["id"] if record["from_paper"] else str(paper_id),
                    properties=record["rel_props"],
                )
            )

    return PaperDetail(
        **_list_item(paper).model_dump(),
        abstract=paper.abstract,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        sections=paper.sections,
        entities=list(entities.values()),
        relationships=relationships,
    )


@router.patch("/papers/{paper_id}", response_model=PaperListItem)
async def update_paper(
    paper_id: uuid.UUID, request: PaperUpdate, db: AsyncSession = Depends(get_db)
) -> PaperListItem:
    """POLISH-005's "assigning papers to a collection" AC — the only way to
    move an already-ingested paper into/out of a collection after upload
    time (ingest.py's own collection_id form field only covers assignment
    at upload). collection_id=null unassigns (papers.collection_id is
    nullable — see src/models/paper.py)."""
    paper = await paper_repository.get_by_id(db, paper_id)
    if paper is None:
        raise HTTPException(404, "paper not found")
    paper.collection_id = request.collection_id
    await db.flush()
    return _list_item(paper)


@router.delete("/papers/{paper_id}", status_code=204)
async def delete_paper(paper_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await delete_paper_cascade(db, paper_id)
    if deleted is None:
        raise HTTPException(404, "paper not found")
