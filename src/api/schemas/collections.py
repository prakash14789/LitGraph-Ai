"""Request/response models for POST/GET/PATCH/DELETE /collections (POLISH-005).
Organizational only — see collections.py route module docstring for the
explicit non-goal (this does NOT scope Chat/Graph retrieval)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None


class CollectionUpdate(BaseModel):
    """Both fields optional — PATCH semantics, only sent fields change.
    Same pattern as CompareVoteRequest-style partial updates elsewhere in
    this codebase (query_log.compare_verdict)."""

    name: str | None = None
    description: str | None = None


class CollectionResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    paper_count: int  # convenience for the frontend list view — avoids a
    # second GET /papers?collection_id= round-trip just to show "N papers"
