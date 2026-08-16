"""Request/response models for POST /ingest/upload, POST /ingest/arxiv, and
GET /ingest/status/{job_id}."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ArxivImportRequest(BaseModel):
    """POLISH-004. `identifier` accepts a bare arXiv id ("1706.03762"), a
    versioned one ("1706.03762v2"), or a full abs/pdf URL — see
    _parse_arxiv_id in ingest.py."""

    identifier: str
    collection_id: uuid.UUID | None = None


class UploadResult(BaseModel):
    """One per uploaded file (or, for POST /ingest/arxiv, one per import —
    `filename` holds the resolved arXiv id there): "queued" (job dispatched),
    "rejected" (validation failed, nothing was created), or "duplicate"
    (POLISH-001 — the exact same PDF content is already ingested as
    paper_id; nothing new was created, no job was queued)."""

    filename: str
    status: str  # "queued" | "rejected" | "duplicate"
    paper_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    error: str | None = None


class JobStatusResponse(BaseModel):
    job_id: uuid.UUID
    paper_id: uuid.UUID
    status: str
    entities_found: int
    relations_found: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
