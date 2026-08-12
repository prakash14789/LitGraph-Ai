"""POST /ingest/upload, GET /ingest/status/{job_id}."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.ingest import JobStatusResponse, UploadResult
from src.config import settings
from src.models.extraction_job import JobStatus
from src.models.paper import IngestionStatus
from src.repositories import extraction_job_repository, paper_repository
from src.tasks.ingest_task import process_paper

router = APIRouter()

_PDF_MAGIC = b"%PDF-"


def _validate_pdf(filename: str, content: bytes) -> None:
    if not content.startswith(_PDF_MAGIC):
        raise ValueError(f"{filename}: not a valid PDF (missing %PDF- header)")
    max_bytes = settings.max_pdf_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        size_mb = len(content) / 1_048_576
        raise ValueError(
            f"{filename}: {size_mb:.1f}MB exceeds the {settings.max_pdf_size_mb}MB limit"
        )


@router.post("/ingest/upload", response_model=list[UploadResult])
async def upload_papers(
    files: list[UploadFile] = File(...),
    collection_id: uuid.UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> list[UploadResult]:
    if not files:
        raise HTTPException(400, "no files provided")
    if len(files) > settings.max_papers_per_upload:
        raise HTTPException(
            400, f"too many files: {len(files)} exceeds the {settings.max_papers_per_upload} limit"
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    results: list[UploadResult] = []
    for upload in files:
        filename = upload.filename or "unnamed"
        content = await upload.read()
        try:
            _validate_pdf(filename, content)
        except ValueError as exc:
            results.append(UploadResult(filename=filename, status="rejected", error=str(exc)))
            continue

        paper_id = uuid.uuid4()
        dest_path = upload_dir / f"{paper_id}.pdf"  # UUID name — never the user-provided filename
        dest_path.write_bytes(content)

        # Paper + ExtractionJob committed together right here, not left to
        # Depends(get_db)'s end-of-request commit — the task dispatched
        # right after must find a durable row; dispatching before commit
        # risks a worker racing ahead of the transaction. Still atomic: both
        # go through repository.create(), which only flushes, so if the
        # ExtractionJob insert fails the Paper row rolls back too (neither
        # is committed until both flushes succeed).
        try:
            paper = await paper_repository.create(
                db,
                id=paper_id,
                title=Path(filename).stem,
                authors=[],
                pdf_path=str(dest_path),
                collection_id=collection_id,
                ingestion_status=IngestionStatus.PENDING,
            )
            job = await extraction_job_repository.create(
                db, paper_id=paper.id, status=JobStatus.QUEUED
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        process_paper.delay(str(job.id))
        results.append(
            UploadResult(filename=filename, status="queued", paper_id=paper.id, job_id=job.id)
        )

    return results


@router.get("/ingest/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> JobStatusResponse:
    job = await extraction_job_repository.get_by_id(db, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return JobStatusResponse(
        job_id=job.id,
        paper_id=job.paper_id,
        status=job.status.value,
        entities_found=job.entities_found,
        relations_found=job.relations_found,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
