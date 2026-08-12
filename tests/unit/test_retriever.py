"""Unit tests for src.services.vanilla_rag.retriever — mocked Chroma
response, no real vector store needed."""

from unittest.mock import MagicMock

from src.services.vanilla_rag import retriever


def test_retrieve_maps_chroma_result_to_chunks(monkeypatch):
    fake_result = {
        "documents": [["chunk one text", "chunk two text"]],
        "metadatas": [
            [
                {"paper_id": "p1", "section_name": "intro", "page_number": 1},
                {"paper_id": "p1", "section_name": "results"},  # no page_number key
            ]
        ],
        "distances": [[0.1, 0.4]],
    }
    monkeypatch.setattr(retriever, "query_similar", MagicMock(return_value=fake_result))

    chunks = retriever.retrieve("what is a widget", top_k=2)

    assert len(chunks) == 2
    assert chunks[0].text == "chunk one text"
    assert chunks[0].paper_id == "p1"
    assert chunks[0].section_name == "intro"
    assert chunks[0].page_number == 1
    assert chunks[0].score == 0.9  # 1 - 0.1
    assert chunks[1].page_number is None
    assert chunks[1].score == 0.6  # 1 - 0.4


def test_retrieve_handles_empty_collection(monkeypatch):
    empty_result = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    monkeypatch.setattr(retriever, "query_similar", MagicMock(return_value=empty_result))

    assert retriever.retrieve("anything") == []
