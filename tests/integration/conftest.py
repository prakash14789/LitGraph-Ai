"""Fixtures shared by integration tests that touch Neo4j — not every
integration test does (test_embedding_storage.py, for instance, is sync and
Chroma-only), so this is opt-in via usefixtures, not autouse."""

import pytest


@pytest.fixture
async def close_neo4j_driver_after_test():
    """Neo4j's async driver pools connections tied to the event loop that
    created them, but pytest-anyio gives each test function its own loop —
    a connection pooled by one test can crash the next with 'got Future
    attached to a different loop' if it's reused there (found live while
    building EXTRACT-004's graph_writer tests, which hammer Neo4j back to
    back; test_papers_api.py's more spread-out Neo4j calls happened not to
    trigger it, but the bug is general to any test file touching Neo4j
    across multiple tests, not specific to either one). No-op (cheap) for a
    test that ends up not touching Neo4j, since close_driver() is a no-op
    when _driver is still None.

    Not autouse: an autouse *async* fixture requested by a *sync* test
    (test_embedding_storage.py, also under tests/integration/) isn't
    handled by any pytest plugin and warns it'll become a hard error in
    pytest 9 — found live making it autouse first. Opt in explicitly instead,
    via `pytestmark = [pytest.mark.anyio,
    pytest.mark.usefixtures("close_neo4j_driver_after_test")]` in whichever
    test file actually calls get_driver()."""
    yield
    from src.graph.connection import close_driver

    await close_driver()
