"""Main router aggregator — mounted under /api/v1 in main.py.

Route modules are added here as they're built (ingest, query, graph, papers,
collections — Epics 1/3/4/5). /health is intentionally NOT here since it's
an unprefixed infra endpoint (see main.py), not a versioned API route.
"""

from fastapi import APIRouter

from src.api.routes import ingest, papers, query

api_router = APIRouter()
api_router.include_router(ingest.router, tags=["ingest"])
api_router.include_router(query.router, tags=["query"])
api_router.include_router(papers.router, tags=["papers"])
