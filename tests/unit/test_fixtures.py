"""Proves the SETUP-009 fixtures actually work — not just that they exist."""

import pytest
from sqlalchemy import select

from src.models.collection import Collection
from src.utils import llm_client


@pytest.mark.anyio
async def test_db_session_can_read_write_and_isolates_between_tests(db_session):
    db_session.add(Collection(name="fixture-smoke-test"))
    await db_session.flush()
    result = await db_session.execute(
        select(Collection).where(Collection.name == "fixture-smoke-test")
    )
    assert result.scalar_one().name == "fixture-smoke-test"


@pytest.mark.anyio
async def test_db_session_rollback_leaves_no_trace(db_session):
    """Runs after the test above — if rollback didn't work, this row would
    still be visible here since it's the same test DB."""
    result = await db_session.execute(
        select(Collection).where(Collection.name == "fixture-smoke-test")
    )
    assert result.scalar_one_or_none() is None


def test_mock_llm_client_replaces_real_call(mock_llm_client):
    # Call via the module (llm_client.complete), not `from ... import complete` —
    # monkeypatch rewrites the module attribute, so a name already bound by a
    # direct import would skip the patch and hit the real API. Same rule
    # applies to any future caller (EXTRACT-001 etc.) that wants this fixture
    # to actually intercept its calls.
    mock_llm_client.return_value = "canned"
    assert llm_client.complete("sys", "user", model="whatever") == "canned"
    mock_llm_client.assert_called_once()


def test_sample_papers_shape(sample_papers):
    assert len(sample_papers) >= 2
    assert all({"title", "authors", "abstract", "sections"} <= p.keys() for p in sample_papers)
