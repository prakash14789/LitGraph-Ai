"""Neo4j async driver — one shared, connection-pooled instance for the app."""

from neo4j import AsyncDriver, AsyncGraphDatabase

from src.config import settings

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=50,
            max_connection_lifetime=3600,  # seconds
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
