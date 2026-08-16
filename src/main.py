"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware import install_error_handling
from src.api.router import api_router
from src.api.routes import health
from src.config import settings
from src.graph.connection import close_driver
from src.graph.schema import init_schema
from src.utils.logging import configure_logging
from src.vectorstore.embedder import warm_up
from src.vectorstore.store import init_collections

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_schema()  # Neo4j constraints/indexes — idempotent, safe on every startup
    init_collections()  # Chroma paper_chunks / entity_embeddings — idempotent
    warm_up()  # pre-load the local embedding model — see embedder.warm_up's docstring
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
install_error_handling(app)

# /health is unprefixed (infra/monitoring convention) — everything else lives under /api/v1
app.include_router(health.router)
app.include_router(api_router, prefix="/api/v1")
