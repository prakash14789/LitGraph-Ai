"""Unit tests for src.services.generation.generator (RETRIEVAL-005) —
mock_llm_client fixture, no real LLM calls. Named test_graphrag_generator.py,
not test_generator.py, to avoid colliding with vanilla_rag's own unit test
file of that name already in this same directory."""

from src.services.generation.generator import generate_answer
from src.services.retrieval.context_builder import BuiltContext


def test_generate_answer_calls_llm_with_context(mock_llm_client):
    mock_llm_client.return_value = "BERT introduced pre-training. [BERT paper]"
    context = BuiltContext(
        text="ENTITIES:\n- [METHOD] BERT (introduced by Paper: 'BERT', 2018)",
        token_count=20,
        truncated=False,
    )

    answer = generate_answer("What is BERT?", context)

    assert answer == "BERT introduced pre-training. [BERT paper]"
    mock_llm_client.assert_called_once()
    _, kwargs = mock_llm_client.call_args
    assert "[METHOD] BERT" in kwargs["user_prompt"]
    assert "What is BERT?" in kwargs["user_prompt"]


def test_generate_answer_empty_context_skips_llm(mock_llm_client):
    context = BuiltContext(text="", token_count=0, truncated=False)

    answer = generate_answer("anything", context)

    assert "I don't know" in answer
    mock_llm_client.assert_not_called()
