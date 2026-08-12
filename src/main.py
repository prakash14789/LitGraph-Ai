"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.router import api_router
from src.api.routes import health
from src.config import settings
from celery.result import AsyncResult

from src.graph.connection import close_driver
from src.graph.schema import init_schema
from src.tasks.celery_app import celery_app, hello_world
from src.utils.logging import configure_logging
from src.vectorstore.store import init_collections

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_schema()  # Neo4j constraints/indexes — idempotent, safe on every startup
    init_collections()  # Chroma paper_chunks / entity_embeddings — idempotent
    yield
    await close_driver()


app = FastAPI(title="LitGraph API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /health is unprefixed (infra/monitoring convention) — everything else lives under /api/v1
app.include_router(health.router)
app.include_router(api_router, prefix="/api/v1")


# --- SETUP-007 wiring check only --------------------------------------------
# Proves the FastAPI process can dispatch a Celery task and read its result
# back from Redis. Delete both routes once INGEST-004 adds a real task to
# dispatch (paper upload -> ingestion job).
@app.post("/api/v1/_debug/test-task")
def dispatch_test_task() -> dict:
    result = hello_world.delay()
    return {"task_id": result.id}


@app.get("/api/v1/_debug/test-task/{task_id}")
def get_test_task_result(task_id: str) -> dict:
    result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
