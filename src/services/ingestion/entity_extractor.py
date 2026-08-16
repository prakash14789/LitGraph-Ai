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
from rapidfuzz import fuzz

from src.config import settings
from src.services.generation.prompts import (
    ENTITY_EXTRACTION_SYSTEM_PROMPT,
    entity_extraction_user_prompt,
)
from src.utils import llm_client
from src.utils.llm_json import parse_json_response, to_confidence

logger = structlog.get_logger()

_CLAIM_TYPES = {"RESULT", "HYPOTHESIS", "LIMITATION", "FUTURE_WORK"}
# fuzz.partial_ratio floor for claim-to-section grounding (FIX-8 live
# incident: an unrelated legal/political passage ended up as a claim on an
# ML paper — the LLM drew on training data instead of the given text).
# Partial, not exact: the LLM paraphrases claims, so a verbatim-substring
# check (fine for entity names) would false-positive on every real claim.
_CLAIM_GROUNDING_THRESHOLD = 40.0


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

    return _to_extraction(data, section_name, section_text)


def _call_llm(user_prompt: str) -> str:
    return llm_client.complete(
        ENTITY_EXTRACTION_SYSTEM_PROMPT,
        user_prompt,
        model=settings.extraction_model,
        max_tokens=settings.extraction_max_tokens,
        temperature=settings.extraction_temperature,
    )


def _is_grounded_name(name: str, section_text: str) -> bool:
    """Exact-substring check for method/dataset names — catches OCR/symbol-
    merge garbage (e.g. "JXLNet" for "XLNet") the LLM invented rather than
    copied from the text it was actually given."""
    return name in section_text


def _drop_ungrounded(items: list, name_of, section_text: str, section_name: str, kind: str) -> list:
    kept = []
    for item in items:
        name = name_of(item)
        if _is_grounded_name(name, section_text):
            kept.append(item)
        else:
            logger.warning(
                "entity_extractor.name_not_grounded", section=section_name, kind=kind, name=name
            )
    return kept


def _to_extraction(data: dict, section_name: str, section_text: str) -> SectionExtraction:
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
    methods = [m for m in methods if m.confidence >= threshold]
    datasets = [d for d in datasets if d.confidence >= threshold]
    metrics = [m for m in metrics if m.confidence >= threshold]
    claims = [c for c in claims if c.confidence >= threshold]

    # FIX-7: drop method/dataset names the LLM invented rather than copied
    # from the given text (OCR/symbol-merge garbage like "JXLNet").
    methods = _drop_ungrounded(methods, lambda m: m.name, section_text, section_name, "Method")
    datasets = _drop_ungrounded(datasets, lambda d: d.name, section_text, section_name, "Dataset")

    # FIX-8: drop claims that don't plausibly trace back to this section's
    # text at all — live incident: unrelated legal/political text ended up
    # as a claim on an ML paper (the model drawing on training data instead
    # of the given text). Not silently dropped: logged so drop frequency is
    # visible, since a high rate would point at swapping EXTRACTION_MODEL.
    grounded_claims = []
    for c in claims:
        score = fuzz.partial_ratio(c.text, section_text)
        if score >= _CLAIM_GROUNDING_THRESHOLD:
            grounded_claims.append(c)
        else:
            logger.warning(
                "entity_extractor.claim_not_grounded",
                section=section_name,
                text=c.text[:200],
                score=score,
            )

    return SectionExtraction(
        methods=methods, datasets=datasets, metrics=metrics, claims=grounded_claims
    )
