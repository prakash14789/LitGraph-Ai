"""Celery app — Redis as both broker and result backend.

The real ingestion task (Epic 1) lives in src/tasks/ingest_task.py. The
`hello_world` task here only exists to prove worker/broker/backend wiring
works end to end (SETUP-007's acceptance criteria) — safe to delete once
INGEST-004 gives us a real task to dispatch instead.
"""

import structlog
from celery import Celery

from src.config import settings

logger = structlog.get_logger()

celery_app = Celery("litgraph", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_time_limit=600,  # 10 min hard limit per task
    task_soft_time_limit=570,
)


@celery_app.task(name="litgraph.hello_world")
def hello_world() -> str:
    logger.info("hello")
    return "hello"
