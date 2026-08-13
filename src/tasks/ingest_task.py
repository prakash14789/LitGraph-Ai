"""Celery task dispatched by POST /ingest/upload. The actual orchestration
logic lives in src/services/ingestion/pipeline.py (INGEST-006) — kept
separate so it's testable without Celery. This module is just the sync
Celery entrypoint (Celery workers are sync, SQLAlchemy's engine here is
async, so asyncio.run bridges the two)."""

import asyncio

from src.services.ingestion.pipeline import run_pipeline
from src.tasks.celery_app import celery_app


@celery_app.task(name="litgraph.process_paper")
def process_paper(job_id: str) -> None:
    asyncio.run(run_pipeline(job_id))
