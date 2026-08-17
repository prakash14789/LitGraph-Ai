"""GET /health — reports connectivity to each backing service.

Always returns 200 (per SETUP-003 acceptance criteria); the body carries
per-dependency status so callers/monitoring can see what's down without the
health check itself failing.
"""

import asyncio

import asyncpg
import structlog
from fastapi import APIRouter
from neo4j import AsyncGraphDatabase

from src.config import settings

router = APIRouter()
logger = structlog.get_logger()

CHECK_TIMEOUT_SECONDS = 3


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
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        async with driver.session() as session:
            await asyncio.wait_for(session.run("RETURN 1"), timeout=CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as exc:
        logger.warning("health_check_failed", service="neo4j", error=str(exc))
        return "unreachable"
    finally:
        await driver.close()


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
