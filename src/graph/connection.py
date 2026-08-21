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
            # Live finding: the extraction pipeline spends 20-40+ minutes on
            # LLM calls between opening the driver and ever touching Neo4j
            # (all the entity/relation extraction happens first; the graph
            # write is the last step). By then, network middleware (this
            # machine's NAT/router) had silently dropped the idle pooled
            # connection twice in a row — "Failed to read from defunct
            # connection" right at the write step, losing the whole run.
            # Three complementary layers against that, not one:
            # - max_connection_lifetime=300 (was 3600): force-recycle a
            #   connection well before a NAT/firewall's own idle-kill window,
            #   instead of trusting it to survive up to an hour unused.
            # - liveness_check_timeout=60: any pooled connection idle longer
            #   than this gets a cheap ping-and-replace before being handed
            #   to a real query, instead of being trusted blind.
            # - keep_alive=True: TCP keepalive packets on the connection
            #   itself, so it looks "active" to NAT/firewalls in the first
            #   place and is less likely to need recycling/replacing at all.
            # Even with all three, a write can still transiently fail (the
            # keepalive/recycle isn't instant) — graph_writer.py's
            # execute_write/execute_read (not raw session.run()) is what
            # actually retries that transparently rather than failing the
            # whole run.
            max_connection_lifetime=300,  # seconds
            liveness_check_timeout=60,  # seconds
            connection_acquisition_timeout=60,  # seconds
            keep_alive=True,
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
