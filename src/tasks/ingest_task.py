"""Celery task dispatched by POST /ingest/upload — parses, chunks, and
embeds one paper, updating its ExtractionJob status at each step.

This covers INGEST-004's "dispatch a task that does something real" need by
reusing INGEST-001/002/003 directly. Entity/relation extraction (Epic 2)
and the fuller orchestrator semantics INGEST-006 specifies (partial-state
cleanup guarantees, its own dedicated tests) extend this later — kept here
rather than pre-building src/services/ingestion/pipeline.py ahead of that
ticket existing.
"""

import asyncio
from datetime import UTC, datetime

import structlog

from src.db import AsyncSessionLocal
from src.models.extraction_job import ExtractionJob, JobStatus
from src.models.paper import IngestionStatus, Paper
from src.services.ingestion.chunker import chunk_paper
from src.services.ingestion.embedding_storage import store_chunks
from src.services.ingestion.pdf_parser import parse_pdf
from src.tasks.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="litgraph.process_paper")
def process_paper(job_id: str) -> None:
    """Sync entrypoint Celery calls — does the actual work in one asyncio.run,
    since Celery workers are sync but SQLAlchemy's engine here is async."""
    asyncio.run(_process_paper(job_id))


async def _process_paper(job_id: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(ExtractionJob, job_id)
        if job is None:
            logger.error("ingest_task.job_not_found", job_id=job_id)
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
            logger.error("ingest_task.failed", job_id=job_id, error=str(exc))
            job.status = JobStatus.FAILED
            job.error_message = str(exc)[:2000]
            paper.ingestion_status = IngestionStatus.FAILED
            await session.commit()
