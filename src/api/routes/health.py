"""GET /health — reports connectivity to each backing service.

Always returns 200 (per SETUP-003 acceptance criteria); the body carries
per-dependency status so callers/monitoring can see what's down without the
health check itself failing.
"""

import asyncio

import asyncpg
import structlog
from fastapi import APIRouter

from src.config import settings
from src.graph.connection import get_driver

router = APIRouter()
logger = structlog.get_logger()

CHECK_TIMEOUT_SECONDS = 8  # was 3 - live finding 2026-08-20: a genuinely
# healthy AuraDB cold handshake alone measured ~4s, so 3s was flagging a
# working database as "unreachable" on nothing but its own tight budget.


async def _check_postgres() -> str:
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(settings.postgres_dsn), timeout=CHECK_TIMEOUT_SECONDS
        )
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return "ok"
    except Exception as exc:
        logger.warning("health_check_failed", service="postgresql", error=str(exc))
        return "unreachable"


async def _check_neo4j() -> str:
    # Reuse the app's shared, pooled driver (src.graph.connection) instead
    # of standing up a disposable one per call - a fresh driver pays a full
    # cold TLS/routing-table handshake every single time, which is what
    # made a healthy AuraDB look "unreachable" against the old 3s budget.
    driver = get_driver()
    try:
        async with driver.session() as session:
            await asyncio.wait_for(session.run("RETURN 1"), timeout=CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as exc:
        logger.warning("health_check_failed", service="neo4j", error=str(exc))
        return "unreachable"


async def _check_qdrant() -> str:
    try:
        from src.vectorstore.store import get_client

        client = get_client()
        client.get_collections()
        return "ok"
    except Exception as exc:
        logger.warning("health_check_failed", service="qdrant", error=str(exc))
        return "unreachable"


@router.get("/health")
async def health_check() -> dict:
    postgres_status, neo4j_status, qdrant_status = await asyncio.gather(
        _check_postgres(), _check_neo4j(), _check_qdrant()
    )
    dependencies = {
        "postgresql": postgres_status,
        "neo4j": neo4j_status,
        "qdrant": qdrant_status,
    }
    return {
        "status": "ok" if all(v == "ok" for v in dependencies.values()) else "degraded",
        "dependencies": dependencies,
    }
