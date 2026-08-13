"""Request/response models for GET /papers, GET /papers/{id}, DELETE /papers/{id}."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class PaperListItem(BaseModel):
    id: uuid.UUID
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    ingestion_status: str
    collection_id: uuid.UUID | None
    created_at: datetime


class PaperEntity(BaseModel):
    """A Neo4j node connected to this paper — Method/Dataset/Claim/etc.
    Always empty today: EXTRACT-004 (graph writer) hasn't landed, so no
    paper has been written into the graph yet. Shape is ready for FE-002."""

    id: str  # Neo4j elementId
    type: str  # node label: Method, Dataset, Claim, ...
    name: str  # canonical_name / name / text, whichever the node has


class PaperRelationship(BaseModel):
    type: str  # USES_METHOD, EXTENDS, INTRODUCES, ...
    source: str  # paper_id or a connected entity's Neo4j elementId
    target: str
    properties: dict


class PaperDetail(PaperListItem):
    abstract: str | None
    doi: str | None
    arxiv_id: str | None
    sections: dict | None
    entities: list[PaperEntity]
    relationships: list[PaperRelationship]
