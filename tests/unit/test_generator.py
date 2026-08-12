"""Unit tests for src.services.vanilla_rag.generator — mock_llm_client
fixture, no real LLM calls."""

from src.services.vanilla_rag.generator import generate_answer
from src.services.vanilla_rag.retriever import RetrievedChunk


def test_generate_answer_calls_llm_with_context(mock_llm_client):
    mock_llm_client.return_value = "Widgets are useful. [1]"
    chunks = [
        RetrievedChunk(
            text="Widgets are useful tools.",
            paper_id="p1",
            section_name="intro",
            page_number=1,
            score=0.9,
        )
    ]

    answer = generate_answer("What are widgets?", chunks)

    assert answer == "Widgets are useful. [1]"
    mock_llm_client.assert_called_once()
    _, kwargs = mock_llm_client.call_args
    assert "Widgets are useful tools." in kwargs["user_prompt"]
    assert "What are widgets?" in kwargs["user_prompt"]


def test_generate_answer_no_chunks_skips_llm(mock_llm_client):
    answer = generate_answer("anything", [])
    assert "No relevant content" in answer
    mock_llm_client.assert_not_called()
