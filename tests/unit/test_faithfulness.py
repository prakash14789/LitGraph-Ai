"""Unit tests for src.services.generation.faithfulness (POLISH-006) —
mock_llm_client fixture, no real LLM calls."""

import json

from src.services.generation.faithfulness import WARNING_TEXT, check_faithfulness


def test_high_score_returns_no_warning(mock_llm_client):
    mock_llm_client.return_value = json.dumps({"score": 0.95, "reason": "fully grounded"})

    result = check_faithfulness("BERT uses masked language modeling.", "BERT: ... MLM ...")

    assert result is None
    mock_llm_client.assert_called_once()
    _, kwargs = mock_llm_client.call_args
    assert kwargs["temperature"] == 0.0


def test_low_score_returns_warning(mock_llm_client):
    mock_llm_client.return_value = json.dumps({"score": 0.2, "reason": "not supported"})

    result = check_faithfulness("BERT was invented by aliens.", "BERT: ... MLM ...")

    assert result == WARNING_TEXT


def test_score_exactly_at_threshold_is_not_a_warning(mock_llm_client):
    from src.config import settings

    mock_llm_client.return_value = json.dumps({"score": settings.faithfulness_threshold})

    assert check_faithfulness("some answer", "some context") is None


def test_unparseable_response_fails_open(mock_llm_client):
    mock_llm_client.return_value = "not json at all"

    assert check_faithfulness("some answer", "some context") is None


def test_llm_call_exception_fails_open(mock_llm_client):
    mock_llm_client.side_effect = RuntimeError("upstream 502")

    assert check_faithfulness("some answer", "some context") is None


def test_empty_answer_or_context_skips_llm(mock_llm_client):
    assert check_faithfulness("", "some context") is None
    assert check_faithfulness("some answer", "") is None
    mock_llm_client.assert_not_called()
