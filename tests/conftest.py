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


async def _ensure_test_db_exists() -> None:
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",  # maintenance DB — the one guaranteed to exist
    )
    try:
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    except asyncpg.DuplicateDatabaseError:
        pass
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def test_engine():
    """One engine for the whole test session, pointed at a DB dedicated to
    tests (never the dev DB) so a test run can't touch real data."""
    await _ensure_test_db_exists()
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
