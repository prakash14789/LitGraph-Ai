"""Unit tests for relation_extractor — mocked LLM (mock_llm_client), no real
API calls. Live prompt-quality verification against real papers was done
separately during development (see docs/02_TECHNICAL_ARCHITECTURE.md)."""

import json

import pytest

from src.config import settings
from src.services.ingestion.relation_extractor import (
    extract_cross_paper_relations,
    extract_intra_paper_relations,
)

pytestmark = pytest.mark.anyio


def _response(relations: list[dict]) -> str:
    return json.dumps({"relations": relations})


async def test_intra_empty_section_returns_empty_without_calling_llm(mock_llm_client):
    result = extract_intra_paper_relations("intro", "   ", ["BERT"])
    assert result == []
    mock_llm_client.assert_not_called()


async def test_cross_empty_candidates_returns_empty_without_calling_llm(mock_llm_client):
    result = extract_cross_paper_relations("intro", "some text", ["BERT"], [])
    assert result == []
    mock_llm_client.assert_not_called()


async def test_intra_parses_relations_with_paper_as_default_source(mock_llm_client):
    mock_llm_client.return_value = _response(
        [
            {
                "type": "USES_METHOD",
                "target": "BERT",
                "evidence_text": "We use BERT.",
                "confidence": 0.9,
            }
        ]
    )

    result = extract_intra_paper_relations("method", "We use BERT.", ["BERT"])
    assert len(result) == 1
    assert result[0].relation_type == "USES_METHOD"
    assert result[0].source == "paper"
    assert result[0].target == "BERT"


async def test_intra_evaluates_on_keeps_metric_and_value_in_properties(mock_llm_client):
    mock_llm_client.return_value = _response(
        [
            {
                "type": "EVALUATES_ON",
                "target": "SQuAD",
                "metric": "F1",
                "value": "93.2",
                "evidence_text": "93.2 F1 on SQuAD",
                "confidence": 0.9,
            }
        ]
    )

    result = extract_intra_paper_relations("results", "text", ["SQuAD"])
    assert result[0].properties == {"metric": "F1", "value": "93.2"}


async def test_intra_parses_distilled_from_with_paper_as_default_source(mock_llm_client):
    mock_llm_client.return_value = _response(
        [
            {
                "type": "DISTILLED_FROM",
                "target": "BERT",
                "evidence_text": "DistilBERT is distilled from BERT.",
                "confidence": 0.9,
            }
        ]
    )

    result = extract_intra_paper_relations("method", "DistilBERT is distilled from BERT.", ["BERT"])
    assert len(result) == 1
    assert result[0].relation_type == "DISTILLED_FROM"
    assert result[0].source == "paper"
    assert result[0].target == "BERT"


async def test_intra_drops_relation_type_outside_allowed_set(mock_llm_client):
    mock_llm_client.return_value = _response(
        [
            {
                "type": "OUTPERFORMS",  # a Pass B type — shouldn't leak into Pass A
                "target": "GPT-2",
                "evidence_text": "text",
                "confidence": 0.9,
            }
        ]
    )

    result = extract_intra_paper_relations("results", "text", ["GPT-2"])
    assert result == []


async def test_cross_parses_outperforms_with_all_three_extra_fields(mock_llm_client):
    mock_llm_client.return_value = _response(
        [
            {
                "type": "OUTPERFORMS",
                "source": "OurMethod",
                "target": "BaselineMethod",
                "metric": "F1",
                "dataset": "SQuAD",
                "margin": "2.1 points",
                "evidence_text": "text",
                "confidence": 0.85,
            }
        ]
    )

    result = extract_cross_paper_relations(
        "results", "text", ["OurMethod"], [("BaselineMethod", "Method")]
    )
    assert len(result) == 1
    assert result[0].properties == {"metric": "F1", "dataset": "SQuAD", "margin": "2.1 points"}


async def test_cross_filters_out_target_not_in_candidate_list(mock_llm_client):
    mock_llm_client.return_value = _response(
        [
            {
                "type": "EXTENDS",
                "source": "OurMethod",
                "target": "SomeInventedMethod",  # not in the candidate list
                "evidence_text": "text",
                "confidence": 0.9,
            }
        ]
    )

    result = extract_cross_paper_relations(
        "method", "text", ["OurMethod"], [("RealCandidateMethod", "Method")]
    )
    assert result == []  # enforced in code, not just trusted from the prompt


async def test_cross_keeps_target_that_is_in_candidate_list(mock_llm_client):
    mock_llm_client.return_value = _response(
        [
            {
                "type": "EXTENDS",
                "source": "OurMethod",
                "target": "RealCandidateMethod",
                "evidence_text": "text",
                "confidence": 0.9,
            }
        ]
    )

    result = extract_cross_paper_relations(
        "method", "text", ["OurMethod"], [("RealCandidateMethod", "Method")]
    )
    assert len(result) == 1
    assert result[0].target == "RealCandidateMethod"


async def test_filters_relations_below_confidence_threshold(mock_llm_client, monkeypatch):
    monkeypatch.setattr(settings, "relation_confidence_threshold", 0.5)
    mock_llm_client.return_value = _response(
        [
            {"type": "USES_METHOD", "target": "A", "evidence_text": "x", "confidence": 0.9},
            {"type": "USES_METHOD", "target": "B", "evidence_text": "x", "confidence": 0.2},
        ]
    )

    result = extract_intra_paper_relations("method", "text", ["A", "B"])
    assert [r.target for r in result] == ["A"]


async def test_retries_once_on_unparseable_json_then_returns_empty(mock_llm_client):
    mock_llm_client.side_effect = ["not json", "still not json"]

    result = extract_intra_paper_relations("intro", "text", ["A"])
    assert result == []
    assert mock_llm_client.call_count == 2


async def test_missing_target_is_skipped_not_crashed(mock_llm_client):
    mock_llm_client.return_value = _response(
        [{"type": "USES_METHOD", "evidence_text": "x", "confidence": 0.9}]
    )

    result = extract_intra_paper_relations("method", "text", ["A"])
    assert result == []
