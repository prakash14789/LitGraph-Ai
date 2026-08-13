"""Unit tests for entity_extractor.extract_entities — mocked LLM (mock_llm_client),
no real API calls. Live prompt-quality verification against 5 real papers was
done separately during development (see docs/02_TECHNICAL_ARCHITECTURE.md)."""

import json

import pytest

from src.config import settings
from src.services.ingestion.entity_extractor import extract_entities

pytestmark = pytest.mark.anyio


def _response(methods=None, datasets=None, metrics=None, claims=None) -> str:
    return json.dumps(
        {
            "methods": methods or [],
            "datasets": datasets or [],
            "metrics": metrics or [],
            "claims": claims or [],
        }
    )


async def test_empty_section_returns_empty_without_calling_llm(mock_llm_client):
    result = extract_entities("introduction", "   ")
    assert result.methods == result.datasets == result.metrics == result.claims == []
    mock_llm_client.assert_not_called()


async def test_parses_valid_json_into_typed_entities(mock_llm_client):
    mock_llm_client.return_value = _response(
        methods=[
            {
                "name": "BERT",
                "description": "a transformer",
                "category": "proposed",
                "confidence": 0.95,
            }
        ],
        datasets=[{"name": "SQuAD", "domain": "NLP", "confidence": 0.9}],
        metrics=[
            {
                "name": "F1",
                "value": "93.2",
                "method": "BERT",
                "dataset": "SQuAD",
                "confidence": 0.85,
            }
        ],
        claims=[{"text": "BERT outperforms prior work.", "type": "RESULT", "confidence": 0.9}],
    )

    result = extract_entities("results", "BERT achieves 93.2 F1 on SQuAD.")

    assert result.methods[0].name == "BERT"
    assert result.methods[0].category == "proposed"
    assert result.datasets[0].name == "SQuAD"
    assert result.metrics[0].method == "BERT" and result.metrics[0].dataset == "SQuAD"
    assert result.claims[0].claim_type == "RESULT"


async def test_strips_markdown_code_fence(mock_llm_client):
    mock_llm_client.return_value = (
        "```json\n" + _response(methods=[{"name": "ResNet", "confidence": 0.9}]) + "\n```"
    )

    result = extract_entities("method", "We use ResNet as a backbone.")
    assert result.methods[0].name == "ResNet"


async def test_extracts_json_object_surrounded_by_prose(mock_llm_client):
    mock_llm_client.return_value = (
        "Sure, here is the JSON: "
        + _response(datasets=[{"name": "ImageNet", "confidence": 0.9}])
        + " Let me know if you need anything else."
    )

    result = extract_entities("experiments", "We evaluate on ImageNet.")
    assert result.datasets[0].name == "ImageNet"


async def test_filters_entities_below_confidence_threshold(mock_llm_client, monkeypatch):
    monkeypatch.setattr(settings, "entity_confidence_threshold", 0.5)
    mock_llm_client.return_value = _response(
        methods=[
            {"name": "confident-method", "confidence": 0.9},
            {"name": "unsure-method", "confidence": 0.2},
        ]
    )

    result = extract_entities("method", "text")
    names = [m.name for m in result.methods]
    assert names == ["confident-method"]


async def test_drops_claims_with_unrecognized_type(mock_llm_client):
    mock_llm_client.return_value = _response(
        claims=[
            {"text": "A valid result.", "type": "RESULT", "confidence": 0.9},
            {"text": "Not a real type.", "type": "SPECULATION", "confidence": 0.9},
        ]
    )

    result = extract_entities("discussion", "text")
    assert len(result.claims) == 1
    assert result.claims[0].text == "A valid result."


async def test_retries_once_on_unparseable_json_then_returns_empty(mock_llm_client):
    mock_llm_client.side_effect = ["not json at all", "still not json"]

    result = extract_entities("intro", "text")
    assert result.methods == result.datasets == result.metrics == result.claims == []
    assert mock_llm_client.call_count == 2


async def test_retry_recovers_if_second_attempt_is_valid(mock_llm_client):
    mock_llm_client.side_effect = [
        "garbage",
        _response(methods=[{"name": "GPT", "confidence": 0.9}]),
    ]

    result = extract_entities("intro", "text")
    assert result.methods[0].name == "GPT"


async def test_missing_optional_fields_do_not_crash(mock_llm_client):
    mock_llm_client.return_value = json.dumps({"methods": [{"name": "bare method"}]})

    result = extract_entities("method", "text")
    # confidence defaults to 0.0, below any real threshold — dropped, not crashed
    assert result.methods == []
