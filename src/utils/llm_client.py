"""Unified LLM client — Gemini, OpenAI, and Anthropic behind one interface.

All three providers speak (or expose a compatibility layer for) the OpenAI
chat-completions API, so one `openai.OpenAI` client with a swapped base_url
covers all of them — no need for three separate SDKs. Provider is chosen via
LLM_PROVIDER; switching is a config change only.
"""

import time
from functools import lru_cache

import structlog
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)

from src.config import settings

logger = structlog.get_logger()

_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": None,  # SDK default
    "anthropic": "https://api.anthropic.com/v1/",
}

_API_KEYS = {
    "gemini": settings.gemini_api_key,
    "openai": settings.openai_api_key,
    "anthropic": settings.anthropic_api_key,
}

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError)
_MAX_ATTEMPTS = 3


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    provider = settings.llm_provider
    return OpenAI(api_key=_API_KEYS[provider], base_url=_BASE_URLS[provider])


class _RateLimiter:
    """Proactive throttle so we never hit Gemini's free-tier RPM cap.
    ponytail: in-memory per-process sliding window — fine for one Celery
    worker; swap for a Redis token bucket if we ever run multiple workers.
    """

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self._calls: list[float] = []

    def wait(self) -> None:
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < 60]
        if len(self._calls) >= self.max_per_minute:
            sleep_for = 60 - (now - self._calls[0])
            if sleep_for > 0:
                logger.info("llm.rate_limit.throttle", sleep_seconds=round(sleep_for, 1))
                time.sleep(sleep_for)
        self._calls.append(time.monotonic())


_rate_limiter = _RateLimiter(settings.llm_rate_limit_rpm)


def complete(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> str:
    """Send one chat completion, return the text.

    Retries transient errors (rate limit / timeout / connection) up to
    _MAX_ATTEMPTS with exponential backoff. Auth and bad-request errors fail
    immediately — retrying won't fix a bad key or a content-policy rejection.
    """
    client = _client()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        _rate_limiter.wait()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = response.usage
            logger.info(
                "llm.completion",
                provider=settings.llm_provider,
                model=model,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            )
            return response.choices[0].message.content or ""
        except (AuthenticationError, BadRequestError):
            raise
        except _RETRYABLE:
            if attempt == _MAX_ATTEMPTS:
                raise
            backoff = 2**attempt
            logger.warning("llm.retry", attempt=attempt, backoff_seconds=backoff)
            time.sleep(backoff)
    raise RuntimeError("unreachable")  # loop above always returns or raises
