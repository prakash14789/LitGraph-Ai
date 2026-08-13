"""Integration test for scripts/review_extraction.py (EXTRACT-006) — real
Postgres + real Neo4j (fetch_candidate_entities has no quota cost), mocked
LLM. This is a formatting/wiring check, not a prompt-quality one — the
script itself is the tool for that, meant to be run manually against real
LLM calls when iterating on prompts, same as every EXTRACT-00x module's own
live-testing was already done standalone."""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts import review_extraction
from src.models.paper import IngestionStatus, Paper

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("close_neo4j_driver_after_test")]


@pytest.fixture(autouse=True)
def _review_uses_test_db(monkeypatch, test_engine):
    """Same pattern as test_ingestion_pipeline.py's _pipeline_uses_test_db —
    review_extraction.py does `from src.db import AsyncSessionLocal`, binding
    its own module-local name; patch it there, not at the definition site."""
    test_sessionmaker = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, class_=AsyncSession
    )
    monkeypatch.setattr(review_extraction, "AsyncSessionLocal", test_sessionmaker)


async def test_review_reports_missing_paper(capsys):
    await review_extraction.review(str(uuid.uuid4()))
    assert "No paper found" in capsys.readouterr().out


async def test_review_reports_unparsed_paper(test_engine, capsys):
    paper_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=paper_id,
                title="Not yet parsed",
                authors=[],
                pdf_path="/tmp/x.pdf",
                ingestion_status=IngestionStatus.PENDING,
            )
        )
        await session.commit()
    try:
        await review_extraction.review(str(paper_id))
        assert "no parsed sections" in capsys.readouterr().out
    finally:
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(Paper).where(Paper.id == paper_id))
            await session.commit()


async def test_review_prints_entities_and_resolution_decisions(
    test_engine, mock_llm_client, capsys
):
    paper_id = uuid.uuid4()
    async with AsyncSession(bind=test_engine) as session:
        session.add(
            Paper(
                id=paper_id,
                title="Mock Paper About FooNet",
                authors=[],
                pdf_path="/tmp/x.pdf",
                ingestion_status=IngestionStatus.COMPLETED,
                sections={"abstract": "We propose FooNet, evaluated on FooBench."},
            )
        )
        await session.commit()

    # Same canned response for every call: entity_extractor parses it as
    # methods/datasets/etc (finds FooNet); relation_extractor parses the
    # same dict but finds no "relations" key, so correctly returns nothing
    # rather than crashing. FooNet is a fabricated name with no real
    # candidates to shortlist against, so resolve_entity never reaches the
    # LLM verification step — no risk of this non-"DECISION: YES" text
    # being misread as a resolution confirmation.
    mock_llm_client.return_value = (
        '{"methods": [{"name": "FooNet", "description": "a mock model", '
        '"category": "proposed", "confidence": 0.9}], "datasets": [], '
        '"metrics": [], "claims": []}'
    )
    try:
        await review_extraction.review(str(paper_id))
        out = capsys.readouterr().out
        assert "Mock Paper About FooNet" in out
        assert "FooNet" in out
        assert "Entity Resolution Decisions" in out
        assert "CREATED new node 'FooNet'" in out
    finally:
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(Paper).where(Paper.id == paper_id))
            await session.commit()
