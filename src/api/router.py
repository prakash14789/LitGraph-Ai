"""Main router aggregator — mounted under /api/v1 in main.py.

Route modules are added here as they're built (ingest, query, graph, papers,
collections — Epics 1/3/4/5, 8). /health is intentionally NOT here since
it's an unprefixed infra endpoint (see main.py), not a versioned API route.
"""

from fastapi import APIRouter

from src.api.routes import collections, graph, ingest, papers, query

api_router = APIRouter()
api_router.include_router(ingest.router, tags=["ingest"])
api_router.include_router(query.router, tags=["query"])
api_router.include_router(papers.router, tags=["papers"])
api_router.include_router(graph.router, tags=["graph"])
api_router.include_router(collections.router, tags=["collections"])
