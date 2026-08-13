"""Integration test for vector_retriever.py — real ChromaDB, real local
embedding model, no mocks. Proves retrieve_seeds() actually finds
semantically-similar entities/chunks against a real HNSW index, not just
that it parses a mocked Chroma response shape correctly (that's what the
unit tests already cover)."""

import uuid

import pytest

from src.config import settings
from src.services.retrieval import vector_retriever
from src.vectorstore.embedder import embed
from src.vectorstore.store import get_collection

pytestmark = pytest.mark.anyio


async def test_retrieve_seeds_finds_real_entity_and_chunk_matches():
    paper_id = f"VR-TEST-PAPER-{uuid.uuid4()}"
    node_id = f"VR-TEST-NODE-{uuid.uuid4()}"
    chroma_entity_id = f"entity_{node_id}"

    entity_text = "BERT: a bidirectional transformer language model for NLP pretraining"
    chunk_text = "This paper introduces a new bidirectional transformer for language understanding."

    entities = get_collection(settings.chroma_collection_entities)
    entities.add(
        ids=[chroma_entity_id],
        embeddings=embed([entity_text]),
        documents=[entity_text],
        metadatas=[{"entity_type": "Method", "canonical_name": "BERT", "source_papers": paper_id}],
    )

    chunks = get_collection(settings.chroma_collection_chunks)
    chunks.add(
        ids=[f"{paper_id}_0"],
        embeddings=embed([chunk_text]),
        documents=[chunk_text],
        metadatas=[{"paper_id": paper_id, "section_name": "abstract"}],
    )

    try:
        seeds = vector_retriever.retrieve_seeds("What is BERT?", entity_top_k=5, chunk_top_k=5)

        entity_ids = {e.node_id for e in seeds.entities}
        assert node_id in entity_ids
        match = next(e for e in seeds.entities if e.node_id == node_id)
        assert match.canonical_name == "BERT"
        assert match.entity_type == "Method"
        assert 0.0 < match.score <= 1.0

        chunk_paper_ids = {c.paper_id for c in seeds.chunks}
        assert paper_id in chunk_paper_ids

        assert paper_id in seeds.paper_ids
    finally:
        entities.delete(ids=[chroma_entity_id])
        chunks.delete(ids=[f"{paper_id}_0"])
