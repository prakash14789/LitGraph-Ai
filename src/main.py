"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.router import api_router
from src.api.routes import health
from src.config import settings
from src.utils.logging import configure_logging

configure_logging(settings.log_level)

app = FastAPI(title="LitGraph API", version="0.1.0")

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
