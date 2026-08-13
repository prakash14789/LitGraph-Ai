"""Shared helper for LLM callers that expect a JSON object back — used by
entity_extractor.py (EXTRACT-001) and relation_extractor.py (EXTRACT-002),
which otherwise duplicate the exact same "strip markdown fences, fall back
to grabbing the outermost {...} block" recovery logic."""

import json
import re

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_response(raw: str) -> dict | None:
    text = raw.strip()
    fence = _JSON_FENCE_RE.match(text)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # The model occasionally wraps the JSON in a sentence or two despite
    # instructions not to — grab the outermost {...} block instead of
    # giving up outright.
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def to_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
