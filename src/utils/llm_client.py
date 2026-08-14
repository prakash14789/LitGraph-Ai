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
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
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
    "ollama": settings.ollama_base_url,
}

# Gemini and Groq get key lists (both measured hitting real free-tier daily
# caps live — Gemini ~20 req/day, Groq ~100K tokens/day). openai/anthropic
# stay single-key: paid keys don't hit the same wall. openrouter also
# single-key for now (added 2026-08-13) — no 2nd key provided yet. ollama
# gets a harmless placeholder — its local server has no auth, but the
# OpenAI SDK requires some non-empty api_key string.
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
    "ollama": ["ollama"],
}


# EVAL-001 live finding: a single real paper's extraction (3 LLM calls/
# section) can burn an entire free-tier provider's daily quota by itself.
# The extraction loop (pipeline.py's _write_graph) has no per-section
# checkpointing, so previously, once a provider's own keys were exhausted
# mid-paper, complete() just raised — losing all progress on that paper and
# forcing a full manual provider switch + full re-upload. Cross-provider
# models are known-good from live testing this session; hardcoded here
# rather than added as more settings, since they're only used after already
# failing over off the configured LLM_PROVIDER. ollama is last in the
# chain, not first — it's genuinely unlimited (no daily cap at all,
# running on this machine's own hardware), but the cloud models are
# higher-quality, so prefer them while they have headroom and only fall
# back to local once every cloud option is actually exhausted.
_FALLBACK_PROVIDERS = ["gemini", "groq", "openrouter", "ollama"]
_FALLBACK_MODEL = {
    "gemini": "gemini-flash-latest",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "openai/gpt-oss-20b:free",
    "ollama": "llama3.1:8b",
}


class _KeyRing:
    """Walks forward through (provider, key) pairs on quota/overload errors
    and never goes back — once a key's daily quota is hit, there's no point
    retrying it again this process's lifetime (a fixed backoff won't refill
    a daily quota). Starts on the configured LLM_PROVIDER's own key list
    (using whatever model the caller passes — already correct for it), then
    falls through to the other free providers in _FALLBACK_PROVIDERS once
    that list is exhausted, using _FALLBACK_MODEL for those since the
    caller's model string is only valid for the originally-configured
    provider. Persists across calls (module-level singleton): after the
    first switch, every subsequent complete() call goes straight to the
    working (provider, key) instead of re-discovering exhausted ones."""

    def __init__(self, keys: list[str] | None = None):
        # `keys` is a test-only escape hatch (existing tests construct
        # _KeyRing(["key-1", "key-2"]) directly) — treated as a single-
        # provider chain, same behavior as before this class grew
        # cross-provider failover. Real usage is the zero-arg form below,
        # which builds the full chain from settings/_API_KEYS.
        if keys is not None:
            self._chain: list[tuple[str, list[str]]] = [(settings.llm_provider, keys or [""])]
        else:
            chain: list[tuple[str, list[str]]] = []
            primary = settings.llm_provider
            chain.append((primary, _API_KEYS.get(primary) or [""]))
            for p in _FALLBACK_PROVIDERS:
                if p == primary:
                    continue
                fallback_keys = [k for k in _API_KEYS.get(p, []) if k]
                if fallback_keys:
                    chain.append((p, fallback_keys))
            self._chain = chain
        self._provider_idx = 0
        self._key_idx = 0

    def provider(self) -> str:
        return self._chain[self._provider_idx][0]

    def current(self) -> str:
        return self._chain[self._provider_idx][1][self._key_idx]

    def model_override(self) -> str | None:
        """None while still on the primary (configured) provider — its
        model comes from the caller. Set once failed over to a fallback
        provider, overriding whatever model the caller passed."""
        if self._provider_idx == 0:
            return None
        return _FALLBACK_MODEL.get(self.provider())

    def advance(self) -> bool:
        """Moves to the next key, or the next provider once the current
        provider's keys are exhausted. Returns False if nothing is left."""
        provider, keys = self._chain[self._provider_idx]
        if self._key_idx + 1 < len(keys):
            self._key_idx += 1
            logger.warning("llm.key_rotated", provider=provider, key_index=self._key_idx)
            return True
        if self._provider_idx + 1 < len(self._chain):
            self._provider_idx += 1
            self._key_idx = 0
            logger.warning("llm.provider_failover", provider=self.provider())
            return True
        return False


_key_ring = _KeyRing()


def _client() -> OpenAI:
    # Not cached: a rotated key/provider must produce a fresh client on the
    # very next call, and constructing an OpenAI() instance does no network
    # I/O — the cache was saving essentially nothing.
    return OpenAI(api_key=_key_ring.current(), base_url=_BASE_URLS[_key_ring.provider()])


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

    A quota/rate-limit error first tries switching to the next configured
    key, then the next fallback provider (unlimited swaps — bounded by how
    many (provider, key) pairs exist, not by _MAX_ATTEMPTS, since a fresh
    key/quota deserves an immediate retry, not a backoff wait). A 5xx
    "overloaded" error is treated the same way — retrying the *same* model
    won't fix genuine overload, but a different provider's different model
    will, so it also advances rather than backing off in place. Any other
    non-2xx status (APIStatusError's catch-all — e.g. a 413 "request too
    large", live-hit on Groq's tighter per-request token cap during
    EVAL-001) advances too, as a defensive backstop: a request too big for
    one provider's limits may fit another's, and the alternative is losing
    all progress on a whole paper with no per-section checkpointing to
    resume from. Once there's no next (provider, key), and for plain
    transient errors (timeout/connection), retries up to _MAX_ATTEMPTS with
    exponential backoff. Auth and bad-request errors fail immediately —
    retrying won't fix a bad key or a content-policy rejection.
    """
    backoff_attempt = 0
    while True:
        _rate_limiter.wait()
        effective_model = _key_ring.model_override() or model
        try:
            response = _client().chat.completions.create(
                model=effective_model,
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
                provider=_key_ring.provider(),
                model=effective_model,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            )
            return response.choices[0].message.content or ""
        except (AuthenticationError, BadRequestError):
            raise
        except (RateLimitError, InternalServerError, APIStatusError):
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
