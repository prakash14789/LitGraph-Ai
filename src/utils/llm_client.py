"""Unified LLM client — Gemini, OpenAI, and Anthropic behind one interface.

All three providers speak (or expose a compatibility layer for) the OpenAI
chat-completions API, so one `openai.OpenAI` client with a swapped base_url
covers all of them — no need for three separate SDKs. Provider is chosen via
LLM_PROVIDER; switching is a config change only.
"""

import time

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
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Gemini and Groq get key lists (both measured hitting real free-tier daily
# caps live — Gemini ~20 req/day, Groq ~100K tokens/day). openai/anthropic
# stay single-key: paid keys don't hit the same wall. openrouter also
# single-key for now (added 2026-08-13) — no 2nd key provided yet.
_API_KEYS = {
    "gemini": [k for k in [settings.gemini_api_key, settings.gemini_api_key_fallback] if k],
    "openai": [settings.openai_api_key],
    "anthropic": [settings.anthropic_api_key],
    "groq": [
        k
        for k in [
            settings.groq_api_key,
            settings.groq_api_key_fallback,
            settings.groq_api_key_fallback_2,
        ]
        if k
    ],
    "openrouter": [settings.openrouter_api_key],
}


class _KeyRing:
    """Walks forward through a provider's key list on quota errors and never
    goes back — once a key's daily quota is hit, there's no point retrying it
    again this process's lifetime (a fixed backoff won't refill a daily
    quota). Persists across calls (module-level singleton): after the first
    switch, every subsequent complete() call goes straight to the working key
    instead of re-discovering the exhausted one every time."""

    def __init__(self, keys: list[str]):
        self._keys = keys or [""]  # keep indexable even if misconfigured
        self._index = 0

    def current(self) -> str:
        return self._keys[self._index]

    def advance(self) -> bool:
        """Moves to the next key. Returns False if there isn't one (caller
        should fall back to backoff-retrying the current key)."""
        if self._index + 1 >= len(self._keys):
            return False
        self._index += 1
        logger.warning("llm.key_rotated", provider=settings.llm_provider, key_index=self._index)
        return True


_key_ring = _KeyRing(_API_KEYS[settings.llm_provider])


def _client() -> OpenAI:
    # Not cached: a rotated key must produce a fresh client on the very next
    # call, and constructing an OpenAI() instance does no network I/O — the
    # cache was saving essentially nothing.
    return OpenAI(api_key=_key_ring.current(), base_url=_BASE_URLS[settings.llm_provider])


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


_RETRYABLE = (APITimeoutError, APIConnectionError)
_MAX_ATTEMPTS = 3


def complete(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> str:
    """Send one chat completion, return the text.

    A quota/rate-limit error first tries switching to the next configured key
    (unlimited swaps — bounded by how many keys exist, not by _MAX_ATTEMPTS,
    since a fresh key/quota deserves an immediate retry, not a backoff wait).
    Once there's no next key, and for plain transient errors (timeout/
    connection), retries up to _MAX_ATTEMPTS with exponential backoff. Auth
    and bad-request errors fail immediately — retrying won't fix a bad key or
    a content-policy rejection.
    """
    backoff_attempt = 0
    while True:
        _rate_limiter.wait()
        try:
            response = _client().chat.completions.create(
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
        except RateLimitError:
            if _key_ring.advance():
                continue
            backoff_attempt += 1
            if backoff_attempt >= _MAX_ATTEMPTS:
                raise
            backoff = 2**backoff_attempt
            logger.warning("llm.retry", attempt=backoff_attempt, backoff_seconds=backoff)
            time.sleep(backoff)
        except _RETRYABLE:
            backoff_attempt += 1
            if backoff_attempt >= _MAX_ATTEMPTS:
                raise
            backoff = 2**backoff_attempt
            logger.warning("llm.retry", attempt=backoff_attempt, backoff_seconds=backoff)
            time.sleep(backoff)
