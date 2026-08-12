"""Request/response models for POST /ingest/upload and GET /ingest/status/{job_id}."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class UploadResult(BaseModel):
    """One per uploaded file — either queued (job dispatched) or rejected
    (validation failed, nothing was created)."""

    filename: str
    status: str  # "queued" | "rejected"
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
