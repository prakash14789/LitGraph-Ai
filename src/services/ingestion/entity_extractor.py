"""LLM-based entity extraction (EXTRACT-001) — Methods, Datasets, Metrics,
and Claims from one paper section at a time. The prompt itself lives in
src/services/generation/prompts.py per the architecture doc; this module
calls it and turns the response into typed data.

Section-by-section, not whole-paper-at-once: a full paper blows past
extraction_max_tokens and dilutes the model's attention across unrelated
sections. Operates on the raw section text from pdf_parser (not chunker's
~1000-token chunks) — keeping a whole section together gives the model more
context to attribute a metric to the right method/dataset than a chunk
boundary would.

Never raises on a bad response — one malformed section shouldn't fail the
whole paper's extraction (same contract as pdf_parser.parse_pdf).
"""

from dataclasses import dataclass, field

import structlog

from src.config import settings
from src.services.generation.prompts import (
    ENTITY_EXTRACTION_SYSTEM_PROMPT,
    entity_extraction_user_prompt,
)
from src.utils import llm_client
from src.utils.llm_json import parse_json_response, to_confidence

logger = structlog.get_logger()

_CLAIM_TYPES = {"RESULT", "HYPOTHESIS", "LIMITATION", "FUTURE_WORK"}


@dataclass
class ExtractedMethod:
    name: str
    description: str
    category: str
    confidence: float


@dataclass
class ExtractedDataset:
    name: str
    domain: str
    confidence: float


@dataclass
class ExtractedMetric:
    name: str
    value: str
    method: str | None
    dataset: str | None
    confidence: float


@dataclass
class ExtractedClaim:
    text: str
    claim_type: str
    confidence: float


@dataclass
class SectionExtraction:
    methods: list[ExtractedMethod] = field(default_factory=list)
    datasets: list[ExtractedDataset] = field(default_factory=list)
    metrics: list[ExtractedMetric] = field(default_factory=list)
    claims: list[ExtractedClaim] = field(default_factory=list)


def extract_entities(section_name: str, section_text: str) -> SectionExtraction:
    if not section_text.strip():
        return SectionExtraction()

    user_prompt = entity_extraction_user_prompt(section_name, section_text)
    data = parse_json_response(_call_llm(user_prompt))
    if data is None:
        # One retry — a fresh sample sometimes recovers from a one-off
        # formatting slip (stray prose around the JSON, a truncated object).
        data = parse_json_response(_call_llm(user_prompt))
    if data is None:
        logger.error("entity_extractor.unparseable_response", section=section_name)
        return SectionExtraction()

    return _to_extraction(data)


def _call_llm(user_prompt: str) -> str:
    return llm_client.complete(
        ENTITY_EXTRACTION_SYSTEM_PROMPT,
        user_prompt,
        model=settings.extraction_model,
        max_tokens=settings.extraction_max_tokens,
        temperature=settings.extraction_temperature,
    )


def _to_extraction(data: dict) -> SectionExtraction:
    if not isinstance(data, dict):
        return SectionExtraction()

    methods = [
        ExtractedMethod(
            name=str(m["name"]).strip(),
            description=str(m.get("description", "")).strip(),
            category=str(m.get("category", "")).strip(),
            confidence=to_confidence(m.get("confidence")),
        )
        for m in data.get("methods", [])
        if isinstance(m, dict) and m.get("name")
    ]
    datasets = [
        ExtractedDataset(
            name=str(d["name"]).strip(),
            domain=str(d.get("domain", "")).strip(),
            confidence=to_confidence(d.get("confidence")),
        )
        for d in data.get("datasets", [])
        if isinstance(d, dict) and d.get("name")
    ]
    metrics = [
        ExtractedMetric(
            name=str(m["name"]).strip(),
            value=str(m.get("value", "")).strip(),
            method=(str(m["method"]).strip() if m.get("method") else None),
            dataset=(str(m["dataset"]).strip() if m.get("dataset") else None),
            confidence=to_confidence(m.get("confidence")),
        )
        for m in data.get("metrics", [])
        if isinstance(m, dict) and m.get("name")
    ]
    claims = [
        ExtractedClaim(
            text=str(c["text"]).strip(),
            claim_type=str(c.get("type", "")).strip().upper(),
            confidence=to_confidence(c.get("confidence")),
        )
        for c in data.get("claims", [])
        if isinstance(c, dict) and c.get("text")
    ]
    # Drop claims outside the schema's 4 types rather than guess a bucket —
    # known limitation: a model typo/synonym here silently loses that claim.
    claims = [c for c in claims if c.claim_type in _CLAIM_TYPES]

    threshold = settings.entity_confidence_threshold
    return SectionExtraction(
        methods=[m for m in methods if m.confidence >= threshold],
        datasets=[d for d in datasets if d.confidence >= threshold],
        metrics=[m for m in metrics if m.confidence >= threshold],
        claims=[c for c in claims if c.confidence >= threshold],
    )
