"""Orchestrates the full per-paper ingestion pipeline: parse -> chunk ->
embed -> (Epic 2: extract entities -> extract relations -> resolve ->
write graph — not implemented yet). Dispatched by the Celery task in
src/tasks/ingest_task.py — kept as a plain async function here, not tied
to Celery, so it's directly testable.

On any step failure: marks the job/paper FAILED with the error captured,
and removes any chunks that already made it into ChromaDB before the
failure. Without that cleanup, a partially-embedded paper would look
"already ingested" to embedding_storage's duplicate check on retry
(since it only checks whether *any* chunks exist for a paper_id), so a
retry would silently keep the incomplete data forever instead of
re-embedding from scratch.
"""

from datetime import UTC, datetime

import structlog

from src.config import settings
from src.db import AsyncSessionLocal
from src.models.extraction_job import ExtractionJob, JobStatus
from src.models.paper import IngestionStatus, Paper
from src.services.ingestion.chunker import chunk_paper
from src.services.ingestion.embedding_storage import store_chunks
from src.services.ingestion.pdf_parser import parse_pdf
from src.vectorstore.store import get_collection

logger = structlog.get_logger()


async def run_pipeline(job_id: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(ExtractionJob, job_id)
        if job is None:
            logger.error("pipeline.job_not_found", job_id=job_id)
            return

        paper = await session.get(Paper, job.paper_id)
        if paper is None:
            job.status = JobStatus.FAILED
            job.error_message = "paper record not found"
            await session.commit()
            return

        try:
            job.status = JobStatus.PARSING
            job.started_at = datetime.now(UTC)
            await session.commit()

            parsed = parse_pdf(paper.pdf_path)
            if not parsed.ok:
                raise RuntimeError(f"PDF parse failed: {parsed.error}")

            paper.title = parsed.title or paper.title
            paper.authors = parsed.authors or paper.authors
            paper.raw_text = parsed.full_text
            paper.sections = parsed.sections
            await session.commit()

            job.status = JobStatus.CHUNKING
            await session.commit()
            chunks = chunk_paper(parsed, paper_id=str(paper.id))

            job.status = JobStatus.EMBEDDING
            await session.commit()
            store_chunks(str(paper.id), chunks)

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            paper.ingestion_status = IngestionStatus.COMPLETED
            await session.commit()
        except Exception as exc:
            logger.error("pipeline.failed", job_id=job_id, error=str(exc))
            _cleanup_partial_chunks(str(paper.id))
            job.status = JobStatus.FAILED
            job.error_message = str(exc)[:2000]
            paper.ingestion_status = IngestionStatus.FAILED
            await session.commit()


def _cleanup_partial_chunks(paper_id: str) -> None:
    collection = get_collection(settings.chroma_collection_chunks)
    existing = collection.get(where={"paper_id": paper_id})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
        logger.info(
            "pipeline.cleanup_partial_chunks", paper_id=paper_id, count=len(existing["ids"])
        )
