"""Celery app — Redis as both broker and result backend.

The real ingestion task lives in src/tasks/ingest_task.py (litgraph.process_paper),
dispatched by POST /ingest/upload. Worker/broker/backend wiring was proven with
a throwaway hello_world task during SETUP-007; removed now that a real task exists.
"""

from celery import Celery

from src.config import settings

celery_app = Celery(
    "litgraph",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # The worker process starts via `celery -A src.tasks.celery_app` and never
    # otherwise imports ingest_task.py — without `include`, it never registers
    # litgraph.process_paper and fails every dispatched task as "unregistered".
    include=["src.tasks.ingest_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_time_limit=600,  # 10 min hard limit per task
    task_soft_time_limit=570,
)
