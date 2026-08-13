"""Unit tests for src.services.retrieval.vector_retriever — mocked Chroma
responses (both collections), no real vector store needed."""

from unittest.mock import MagicMock

from src.services.retrieval import vector_retriever


def _entity_result(ids, metadatas, distances):
    return {"ids": [ids], "metadatas": [metadatas], "distances": [distances]}


def _chunk_result(documents, metadatas, distances):
    return {"documents": [documents], "metadatas": [metadatas], "distances": [distances]}


def test_retrieve_seeds_combines_entities_and_chunks(monkeypatch):
    entity_result = _entity_result(
        ids=["entity_4:abc:1"],
        metadatas=[{"entity_type": "Method", "canonical_name": "BERT", "source_papers": "p1,p2"}],
        distances=[0.1],
    )
    chunk_result = _chunk_result(
        documents=["a chunk of text"],
        metadatas=[{"paper_id": "p3", "section_name": "intro"}],
        distances=[0.3],
    )
    mock = MagicMock(side_effect=[entity_result, chunk_result])
    monkeypatch.setattr(vector_retriever, "query_similar", mock)

    seeds = vector_retriever.retrieve_seeds("what is BERT")

    assert len(seeds.entities) == 1
    assert seeds.entities[0].node_id == "4:abc:1"  # "entity_" prefix stripped
    assert seeds.entities[0].entity_type == "Method"
    assert seeds.entities[0].canonical_name == "BERT"
    assert seeds.entities[0].score == 0.9  # 1 - 0.1

    assert len(seeds.chunks) == 1
    assert seeds.chunks[0].paper_id == "p3"
    assert seeds.chunks[0].score == 0.7  # 1 - 0.3

    # p1/p2 from the entity's source_papers, p3 from the chunk — all three, deduplicated & sorted
    assert seeds.paper_ids == ["p1", "p2", "p3"]


def test_retrieve_seeds_falls_back_to_chunks_only_when_graph_is_empty(monkeypatch):
    empty_entities = _entity_result(ids=[], metadatas=[], distances=[])
    chunk_result = _chunk_result(
        documents=["some text"],
        metadatas=[{"paper_id": "p1", "section_name": "intro"}],
        distances=[0.2],
    )
    mock = MagicMock(side_effect=[empty_entities, chunk_result])
    monkeypatch.setattr(vector_retriever, "query_similar", mock)

    seeds = vector_retriever.retrieve_seeds("anything")

    assert seeds.entities == []
    assert len(seeds.chunks) == 1
    assert seeds.paper_ids == ["p1"]


def test_retrieve_seeds_dedupes_paper_shared_by_entity_and_chunk(monkeypatch):
    entity_result = _entity_result(
        ids=["entity_1"],
        metadatas=[
            {"entity_type": "Method", "canonical_name": "BERT", "source_papers": "shared-paper"}
        ],
        distances=[0.1],
    )
    chunk_result = _chunk_result(
        documents=["text"],
        metadatas=[{"paper_id": "shared-paper", "section_name": "intro"}],
        distances=[0.1],
    )
    mock = MagicMock(side_effect=[entity_result, chunk_result])
    monkeypatch.setattr(vector_retriever, "query_similar", mock)

    seeds = vector_retriever.retrieve_seeds("query")

    assert seeds.paper_ids == ["shared-paper"]  # counted once, not twice


def test_retrieve_seeds_handles_fully_empty_corpus(monkeypatch):
    empty_entities = _entity_result(ids=[], metadatas=[], distances=[])
    empty_chunks = _chunk_result(documents=[], metadatas=[], distances=[])
    mock = MagicMock(side_effect=[empty_entities, empty_chunks])
    monkeypatch.setattr(vector_retriever, "query_similar", mock)

    seeds = vector_retriever.retrieve_seeds("anything")

    assert seeds.entities == []
    assert seeds.chunks == []
    assert seeds.paper_ids == []
