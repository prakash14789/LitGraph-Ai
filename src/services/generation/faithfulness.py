"""POLISH-006: a self-audit second LLM call — after GraphRAG generates an
answer (RETRIEVAL-005), asks a separate call whether that answer actually
follows from the same context it was generated from, and returns a warning
string to surface in the response when it scores below threshold.

GraphRAG only. Vanilla RAG isn't in this ticket's scope (dependency is
RETRIEVAL-005, the GraphRAG generator specifically).
"""

import structlog

from src.config import settings
from src.utils import llm_client
from src.utils.llm_json import parse_json_response, to_confidence

logger = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You are a strict fact-checker. You will be given CONTEXT (the only source "
    "of truth) and an ANSWER generated from it. Judge how well the answer is "
    "supported by the context: 1.0 means every claim in the answer is directly "
    "grounded in the context, 0.0 means the answer is unsupported by or "
    "contradicts the context. Reasonable paraphrasing of the context still "
    'counts as grounded. Respond with ONLY a JSON object: {"score": <float '
    '0.0-1.0>, "reason": "<one short sentence>"}.'
)

WARNING_TEXT = "⚠️ Low confidence — some claims may not be fully supported by the retrieved sources."


def check_faithfulness(answer: str, context_text: str) -> str | None:
    """Returns WARNING_TEXT if the answer scores below
    settings.faithfulness_threshold, else None. Fails open (no warning, not
    an exception) on any call/parse error — this is a secondary self-audit
    running after the primary answer already succeeded; a broken audit
    shouldn't turn a good response into a failed request."""
    if not answer.strip() or not context_text.strip():
        return None

    user_prompt = f"CONTEXT:\n{context_text}\n\nANSWER:\n{answer}"
    try:
        raw = llm_client.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.generation_model,
            max_tokens=settings.faithfulness_max_tokens,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — see docstring: fail open
        logger.warning("faithfulness.call_failed", error=str(exc))
        return None

    parsed = parse_json_response(raw)
    if parsed is None or "score" not in parsed:
        logger.warning("faithfulness.unparseable_response", raw=raw[:200])
        return None

    score = to_confidence(parsed["score"])
    if score < settings.faithfulness_threshold:
        logger.info("faithfulness.low_score", score=score, reason=parsed.get("reason"))
        return WARNING_TEXT
    return None
