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
    # EVAL-001 live finding: the currently-configured free OpenRouter model
    # (openai/gpt-oss-20b:free) runs ~90-130s per LLM call, and _write_graph
    # makes 3 calls/section (extract_entities + intra/cross relations) before
    # any Neo4j write happens — a ~7-section paper needs ~20+ calls, i.e.
    # 30-45 min, well past the old 600s (10 min) limit. That limit silently
    # SIGKILLed real ingestions mid-extraction (no exception, job stuck
    # forever at extracting_entities, no partial graph writes since Neo4j
    # writes only start after every section's entity extraction finishes).
    # Raised with real margin for the current slow model; lower this back
    # down once LLM_PROVIDER points at a faster/paid model.
    #
    # Raised again 3600s -> 7200s once running on local Ollama
    # (llama3.1:8b, CPU/AMD-GPU, no quota limit but genuinely unlimited
    # doesn't mean fast): most calls land in the same ~60-90s range as the
    # cloud models, but the local model occasionally doesn't stop cleanly
    # and fills its whole max_tokens budget instead — measured live at
    # ~9 min for one such call at the old 4096-token cap. GPT-2's real
    # ingestion had 3 of these in one run and still got SIGKILLed at the
    # old 3600s limit with real progress made (29/~35 calls done, no
    # partial graph writes since Neo4j writes only start after every
    # section's entities finish). EXTRACTION_MAX_TOKENS also lowered
    # 4096 -> 2048 alongside this (see .env) to cut each pathological
    # call's worst case roughly in half, not just widen the ceiling.
    task_time_limit=7200,  # 120 min hard limit per task
    task_soft_time_limit=7140,
)
