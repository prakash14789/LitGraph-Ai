"""Celery task dispatched by POST /ingest/upload. The actual orchestration
logic lives in src/services/ingestion/pipeline.py (INGEST-006) — kept
separate so it's testable without Celery. This module is just the sync
Celery entrypoint (Celery workers are sync, SQLAlchemy's engine here is
async, so asyncio.run bridges the two).

Live bug found running back-to-back real ingestions on the same forked
Celery worker (EVAL-001): src/db.py's async engine and
src/graph/connection.py's Neo4j driver are both process-lifetime
singletons whose pooled connections are tied to whichever asyncio event
loop created them. asyncio.run() gives each task its own fresh event
loop, so a 2nd task handed a pooled connection from the 1st task's
now-closed loop crashed with "Future attached to a different loop"
before the job even reached PARSING status — the exact same class of bug
already documented for pytest-anyio (see
close_neo4j_driver_after_test in tests/integration/conftest.py), just
never hit in production before two real ingestions ran back to back in
one session. Both are disposed/closed at the end of every task, inside
the same loop that used them, so the next task's fresh loop never gets
handed a stale connection."""

import asyncio

from src.db import engine
from src.graph.connection import close_driver
from src.services.ingestion.pipeline import run_pipeline
from src.tasks.celery_app import celery_app


@celery_app.task(name="litgraph.process_paper")
def process_paper(job_id: str) -> None:
    async def _run() -> None:
        try:
            await run_pipeline(job_id)
        finally:
            await engine.dispose()
            await close_driver()

    asyncio.run(_run())
