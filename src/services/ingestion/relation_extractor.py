"""LLM-based relationship extraction (EXTRACT-002) — two passes per the
ticket. Pass A (intra-paper) relates the paper to its own entities
(USES_METHOD, EVALUATES_ON, TRAINED_ON, INTRODUCES, DISTILLED_FROM,
REPORTS_RESULT) — no outside knowledge needed. Pass B (cross-paper) relates the paper's entities to a
given candidate list of entities from OTHER papers (EXTENDS, OUTPERFORMS,
CONTRADICTS, CITES) — the candidate list stands in for a real Neo4j lookup,
which doesn't exist until EXTRACT-004 (graph writer) lands.

AUTHORED_BY is deliberately not extracted here — see prompts.py's comment:
pdf_parser already parses paper.authors as structured data, so there's
nothing for an LLM to add there.

Same never-raises-on-a-bad-response contract as entity_extractor.py.
"""

from dataclasses import dataclass

import structlog

from src.config import settings
from src.services.generation.prompts import (
    RELATION_EXTRACTION_CROSS_PROMPT,
    RELATION_EXTRACTION_INTRA_PROMPT,
    relation_extraction_cross_user_prompt,
    relation_extraction_intra_user_prompt,
)
from src.utils import llm_client
from src.utils.llm_json import parse_json_response, to_confidence

logger = structlog.get_logger()

_INTRA_TYPES = {
    "USES_METHOD",
    "EVALUATES_ON",
    "TRAINED_ON",
    "INTRODUCES",
    "DISTILLED_FROM",
    "REPORTS_RESULT",
}
_CROSS_TYPES = {"EXTENDS", "OUTPERFORMS", "CONTRADICTS", "CITES"}


@dataclass
class ExtractedRelation:
    relation_type: str
    source: str  # "paper" sentinel for Pass A — the paper itself
    target: str
    evidence_text: str
    confidence: float
    properties: dict  # type-specific extras: metric/value, or metric/dataset/margin


def extract_intra_paper_relations(
    section_name: str, section_text: str, entity_names: list[str]
) -> list[ExtractedRelation]:
    """Pass A. entity_names should be every method/dataset name already
    extracted from this same section (entity_extractor.extract_entities) —
    an empty list is valid (a section can have no relatable entities)."""
    if not section_text.strip():
        return []

    user_prompt = relation_extraction_intra_user_prompt(section_name, section_text, entity_names)
    data = _extract(RELATION_EXTRACTION_INTRA_PROMPT, user_prompt, "relation_extractor.intra")
    if data is None:
        return []
    return _to_relations(data, _INTRA_TYPES, default_source="paper")


def extract_cross_paper_relations(
    section_name: str,
    section_text: str,
    own_entity_names: list[str],
    candidate_entities: list[tuple[str, str]],
) -> list[ExtractedRelation]:
    """Pass B. candidate_entities is [(name, entity_type), ...] from OTHER
    papers — normally a Neo4j lookup (post EXTRACT-004), simulated here.
    Empty candidates -> empty result without calling the LLM (nothing to
    possibly link to)."""
    if not section_text.strip() or not candidate_entities:
        return []

    user_prompt = relation_extraction_cross_user_prompt(
        section_name, section_text, own_entity_names, candidate_entities
    )
    data = _extract(RELATION_EXTRACTION_CROSS_PROMPT, user_prompt, "relation_extractor.cross")
    if data is None:
        return []

    candidate_names = {name for name, _ in candidate_entities}
    relations = _to_relations(data, _CROSS_TYPES, default_source=None)
    # Enforce the "never invent a candidate" rule in code, not just the
    # prompt — a model that ignores the instruction shouldn't get to create
    # a phantom cross-paper link (and therefore a phantom duplicate entity).
    return [r for r in relations if r.target in candidate_names]


def _extract(system_prompt: str, user_prompt: str, log_tag: str) -> dict | None:
    raw = llm_client.complete(
        system_prompt,
        user_prompt,
        model=settings.extraction_model,
        max_tokens=settings.extraction_max_tokens,
        temperature=settings.extraction_temperature,
    )
    data = parse_json_response(raw)
    if data is None:
        # One retry, same as entity_extractor — a fresh sample sometimes
        # recovers from a one-off formatting slip.
        raw = llm_client.complete(
            system_prompt,
            user_prompt,
            model=settings.extraction_model,
            max_tokens=settings.extraction_max_tokens,
            temperature=settings.extraction_temperature,
        )
        data = parse_json_response(raw)
    if data is None:
        logger.error(f"{log_tag}.unparseable_response")
    return data


def _to_relations(
    data: dict, allowed_types: set[str], default_source: str | None
) -> list[ExtractedRelation]:
    if not isinstance(data, dict):
        return []

    _EXTRA_FIELDS = {
        "type",
        "source",
        "target",
        "evidence_text",
        "confidence",
    }

    relations = []
    for r in data.get("relations", []):
        if not isinstance(r, dict) or not r.get("target"):
            continue
        relation_type = str(r.get("type", "")).strip().upper()
        if relation_type not in allowed_types:
            continue
        source = r.get("source") or default_source
        if not source:
            continue
        relations.append(
            ExtractedRelation(
                relation_type=relation_type,
                source=str(source).strip(),
                target=str(r["target"]).strip(),
                evidence_text=str(r.get("evidence_text", "")).strip(),
                confidence=to_confidence(r.get("confidence")),
                properties={k: v for k, v in r.items() if k not in _EXTRA_FIELDS and v is not None},
            )
        )

    threshold = settings.relation_confidence_threshold
    return [r for r in relations if r.confidence >= threshold]
