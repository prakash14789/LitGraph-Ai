"""Integration tests for src.services.ingestion.embedding_storage — talks to
the real ChromaDB container (docker-compose service), not a mock. That's
the actual thing worth verifying here: the add/get(where=)/duplicate-skip
contract against Chroma's real API, not our own assumptions about it.
"""

import pytest

from src.config import settings
from src.services.ingestion.chunker import Chunk
from src.services.ingestion.embedding_storage import store_chunks
from src.vectorstore.store import get_collection

_TEST_PAPER_ID = "test-embedding-storage-paper"


@pytest.fixture(autouse=True)
def cleanup():
    """Runs before AND after each test — a prior failed run shouldn't leave
    stale chunks that make the next run's assertions lie."""

    def _delete_all():
        collection = get_collection(settings.chroma_collection_chunks)
        existing = collection.get(where={"paper_id": _TEST_PAPER_ID})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

    _delete_all()
    yield
    _delete_all()


def _chunks(n: int) -> list[Chunk]:
    return [
        Chunk(
            text=f"This is test chunk number {i} about widgets and gadgets.",
            paper_id=_TEST_PAPER_ID,
            section_name="introduction",
            chunk_index=i,
            page_number=1,
        )
        for i in range(n)
    ]


def test_stores_chunks_with_metadata():
    stored = store_chunks(_TEST_PAPER_ID, _chunks(3))
    assert stored == 3

    collection = get_collection(settings.chroma_collection_chunks)
    result = collection.get(where={"paper_id": _TEST_PAPER_ID})
    assert len(result["ids"]) == 3
    assert result["metadatas"][0]["section_name"] == "introduction"
    assert result["metadatas"][0]["page_number"] == 1


def test_duplicate_paper_is_skipped():
    first = store_chunks(_TEST_PAPER_ID, _chunks(3))
    second = store_chunks(_TEST_PAPER_ID, _chunks(3))

    assert first == 3
    assert second == 0  # skipped — already ingested

    collection = get_collection(settings.chroma_collection_chunks)
    result = collection.get(where={"paper_id": _TEST_PAPER_ID})
    assert len(result["ids"]) == 3  # not 6 — no duplicates created


def test_empty_chunk_list_returns_zero():
    assert store_chunks(_TEST_PAPER_ID, []) == 0
