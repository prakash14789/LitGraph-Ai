"""Main router aggregator — mounted under /api/v1 in main.py.

Route modules are added here as they're built (ingest, query, graph, papers,
collections — Epics 1/3/4/5). Empty for now; /health is intentionally NOT
here since it's an unprefixed infra endpoint (see main.py), not a versioned
API route.
"""

from fastapi import APIRouter

api_router = APIRouter()
