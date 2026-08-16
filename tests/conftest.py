"""Shared pytest fixtures: dedicated test Postgres DB, mock LLM client, sample papers."""

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.config import settings
from src.models.base import Base

TEST_DB_NAME = f"{settings.postgres_db}_test"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """FastAPI/httpx already pull in anyio, which ships its own pytest plugin —
    no need for pytest-asyncio as a separate dependency."""
    return "asyncio"


async def _recreate_test_db() -> None:
    """Drop and recreate the test DB every session, rather than reusing
    whatever's left from a previous run. create_all() only creates
    tables/types that don't exist yet — it never alters an existing Postgres
    ENUM to add new values, so a test DB left over from before a model
    change (e.g. JobStatus gaining PARSING/CHUNKING/EMBEDDING) would silently
    keep the old enum forever and fail with 'invalid input value'. A fresh
    DB each session means create_all() always builds the current schema."""
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",  # maintenance DB — the one guaranteed to exist
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def test_engine():
    """One engine for the whole test session, pointed at a DB dedicated to
    tests (never the dev DB) so a test run can't touch real data."""
    await _recreate_test_db()
    url = settings.database_url.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """One connection + transaction per test, rolled back afterwards — tests
    never see each other's writes."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
async def test_client(test_engine):
    """httpx client wrapping the real FastAPI app, with get_db overridden to
    use the test engine instead of the dev database. Not built on db_session
    (which rolls back per test) — some handlers (POST /ingest/upload)
    deliberately commit mid-request so a dispatched Celery task can find a
    durable row, and a mid-handler commit would defeat db_session's
    rollback-based isolation. Tests here clean up their own rows instead."""
    from httpx import ASGITransport, AsyncClient

    from src.api.dependencies import get_db
    from src.api.rate_limit import limiter
    from src.main import app

    # POLISH-002: slowapi is backed by the real dev Redis instance (no
    # isolated test instance, same gap noted for Neo4j/Chroma). Without this,
    # tests that hit the same endpoint repeatedly (e.g. duplicate-upload
    # tests) would eventually start seeing real 429s instead of the
    # responses they're actually asserting on.
    limiter.enabled = False

    async def _override_get_db():
        async with AsyncSession(bind=test_engine, expire_on_commit=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_llm_client(monkeypatch) -> MagicMock:
    """Swap src.utils.llm_client.complete for a canned-response mock so tests
    never make real API calls. Override per test: mock_llm_client.return_value = "..." """
    from src.utils import llm_client

    mock = MagicMock(return_value="mock LLM response")
    monkeypatch.setattr(llm_client, "complete", mock)
    return mock


@pytest.fixture
def sample_papers() -> list[dict]:
    """A few minimal paper records for ingestion/extraction tests — plain
    dicts, not real PDFs (PDF fixtures land with INGEST-002)."""
    return [
        {
            "title": "Attention Is All You Need",
            "authors": ["Vaswani, A.", "Shazeer, N."],
            "abstract": "We propose a new network architecture, the Transformer, based "
            "solely on attention mechanisms.",
            "sections": {
                "introduction": "Recurrent models have long been the dominant approach "
                "to sequence modeling.",
                "method": "The Transformer uses stacked self-attention and "
                "point-wise, fully connected layers.",
            },
        },
        {
            "title": "Deep Residual Learning for Image Recognition",
            "authors": ["He, K.", "Zhang, X."],
            "abstract": "Deeper neural networks are more difficult to train. We present "
            "a residual learning framework.",
            "sections": {
                "introduction": "Is learning better networks as easy as stacking more layers?",
                "method": "We introduce a residual learning framework with shortcut connections.",
            },
        },
        {
            "title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "authors": ["Devlin, J.", "Chang, M."],
            "abstract": "We introduce a new language representation model called BERT.",
            "sections": {
                "introduction": "Language model pre-training has been shown effective "
                "for many NLP tasks.",
                "method": "BERT uses a masked language model pre-training objective.",
            },
        },
    ]
