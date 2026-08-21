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
    "cerebras": "https://api.cerebras.ai/v1",
    "huggingface": "https://router.huggingface.co/v1",
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
            settings.groq_api_key_fallback_3,
            settings.groq_api_key_fallback_4,
            settings.groq_api_key_fallback_5,
            settings.groq_api_key_fallback_6,
        ]
        if k
    ],
    "openrouter": [
        k for k in [settings.openrouter_api_key, settings.openrouter_api_key_fallback] if k
    ],
    "cerebras": [settings.cerebras_api_key],
    "huggingface": [settings.huggingface_api_key],
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
# huggingface/cerebras dropped 2026-08-17 — both consistently 402'd
# (no billing on either key) every live run since EVAL-002 added them;
# they only ever added two guaranteed-failed hops before falling through
# to openrouter/ollama. _API_KEYS/_FALLBACK_MODEL entries left in place,
# harmless dead config, in case billing is ever added and they're re-added here.
#
# ollama (local qwen2.5:14b): dropped 2026-08-17 (misconfigured URL, looked
# dead), re-added 2026-08-18 (URL fix proved it answers), dropped again
# 2026-08-19 after it hung mid-extraction-run with nothing behind it to fail
# over to. Re-added the same day once max_retries=0 + the 180s client
# timeout bounded the worst case to ~9 min — but then failed *every* real
# pipeline run it was reached in afterward (3+ occurrences, 0 successes),
# despite passing an isolated 4/4-call standalone test. The standalone test
# had nothing else competing for this machine's CPU/RAM; a real pipeline run
# has its own embedding model running at the same time, and that contention
# is the likely reason it can't keep up for real. Dropped again, this time
# on live evidence across multiple real runs, not a single hang — reconsider
# only if it's ever swapped for something this hardware can sustain under
# real concurrent load, not just standalone.
_FALLBACK_PROVIDERS = ["gemini", "groq", "openrouter"]
_FALLBACK_MODEL = {
    "gemini": "gemini-flash-latest",
    # Kept in sync with EXTRACTION_MODEL's .env value (openai/gpt-oss-120b,
    # 2026-08-19 — llama-3.3-70b-versatile was decommissioned, see that
    # comment for the live finding). This entry is currently unreachable
    # dead code anyway (groq IS the configured primary provider, so the
    # chain never fails *over to* it) — kept in sync regardless.
    "groq": "openai/gpt-oss-120b",
    # EVAL-002 live finding: this key's account has no Llama model access —
    # client.models.list() returned only zai-glm-4.7/gpt-oss-120b/gemma-4-31b,
    # and all three 402'd ("Payment required") on a real test call. gpt-oss-120b
    # picked as the best-quality id to have wired up once/if billing is added —
    # unusable until then, same as any exhausted-quota provider in this chain.
    "cerebras": "gpt-oss-120b",
    "huggingface": "meta-llama/Llama-3.3-70B-Instruct",
    # User-provided 2026-08-16 specifically to speed up this session's
    # RoBERTa/ELECTRA/ALBERT reprocess once Groq+Gemini were both exhausted
    # for the day — a free, large (550B-A55B MoE) reasoning-capable model.
    # Reasoning left off (no `reasoning` extra_body below): OpenRouter's own
    # sample code shows it as an opt-in flag, off by default, and turning it
    # on would risk the exact <think>-block token-budget trap qwen hit on
    # Groq — needed here even less, since our calls want terse structured
    # output, not multi-turn reasoning.
    "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    # Switched from llama3.1:8b to qwen2.5:14b (2026-08-16, user request) —
    # nearly 2x the parameters, still free/local/unlimited. Live finding
    # this session: llama3.1:8b's entity-resolution verification calls gave
    # false "same entity" confirmations on genuinely different methods
    # (see entity_resolver.py's _verification_key_ring) — a stronger local
    # model is the general mitigation for whenever cloud quota is fully
    # exhausted and Ollama is truly the last resort.
    "ollama": "qwen2.5:14b",
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


def reset_key_ring() -> None:
    """Live finding: the module-level ring is sticky for the whole worker
    *process's* lifetime, not per-paper — so once one paper's run pushes it
    all the way to the last fallback (e.g. a transient OpenRouter 502
    advancing into Ollama), every subsequent paper processed by that same
    long-running Celery worker inherits the already-degraded state and never
    gets to retry gemini/groq/openrouter fresh, even though their failure
    may have been transient (a 503, a rate-limit window) rather than a hard
    daily-quota exhaustion. Confirmed live: back-to-back paper runs on one
    worker — the second showed zero new llm.provider_failover log lines,
    meaning it started already stuck on the first paper's final fallback.
    Called at the start of each pipeline run (see pipeline.py) so every
    paper gets its own fair shot at the full chain, same as a fresh
    worker restart used to force before this existed."""
    global _key_ring
    _key_ring = _KeyRing()


def _client(ring: _KeyRing) -> OpenAI:
    # Not cached: a rotated key/provider must produce a fresh client on the
    # very next call, and constructing an OpenAI() instance does no network
    # I/O — the cache was saving essentially nothing.
    #
    # timeout=180s, not the SDK's ~600s default — live finding: a reachable
    # but overloaded/unresponsive provider (local Ollama on this machine's
    # hardware, real completions measured taking 10+ minutes) doesn't fail
    # fast enough for _RETRYABLE's own backoff/failover to matter — 3
    # attempts against a 10-minute hang burns ~30 minutes per call before
    # ever reaching a real error. 180s comfortably covers real cloud calls
    # (measured live at 90-130s for OpenRouter's free-tier model) while
    # still failing a genuinely stuck call fast enough for failover to work.
    # max_retries=0 — the SDK's own default (2) retries transparently
    # *inside* one .create() call on timeout, invisible to complete()'s own
    # retry/backoff/failover loop. Live finding: this compounds catastrophically
    # with a genuinely-hung provider — 3 of our own backoff attempts, each
    # silently multiplied by the SDK's 2 extra internal retries, each eating
    # a full 180s timeout, turned one dead Ollama call into a ~24-minute
    # stall before the job finally failed. We already have our own retry
    # logic; a second hidden layer underneath it isn't a safety net, it's
    # unbounded latency.
    return OpenAI(
        api_key=ring.current(), base_url=_BASE_URLS[ring.provider()], timeout=180.0, max_retries=0
    )


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
    *,
    key_ring: "_KeyRing | None" = None,
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

    key_ring (EVAL-002 FIX E): defaults to the shared module-level ring used
    by bulk entity/relation extraction. A caller with its own independent
    ring (entity_resolver's verification calls — see that module) doesn't
    inherit whatever fallback provider bulk extraction has already
    exhausted its way down to in the same process; it fails over on its own
    call volume instead, which for a low-volume caller usually means it
    stays on better-quality cloud providers even when extraction is already
    stuck on the local fallback.
    """
    ring = key_ring or _key_ring
    backoff_attempt = 0
    while True:
        _rate_limiter.wait()
        effective_model = ring.model_override() or model
        # Qwen models are reasoning models by default — live finding
        # (2026-08-16): a bare call spent the entire max_tokens budget
        # inside a <think>...</think> block and never reached the actual
        # answer (confirmed: 500 tokens wasn't even enough to finish
        # thinking on a one-line prompt). reasoning_effort="none" is Groq's
        # documented switch to turn that off — needed for every terse
        # structured-output use case here (JSON extraction, YES/NO
        # verification, judge scores), not just one call site.
        extra = {"reasoning_effort": "none"} if effective_model.startswith("qwen/") else {}
        # Live finding: Groq's free tier caps openai/gpt-oss-120b at 8000
        # tokens/minute, and that check counts the *requested* max_tokens
        # budget, not actual usage — confirmed live, a one-word prompt with
        # max_tokens=8192 still 413'd ("Requested 8265"). EXTRACTION_MAX_TOKENS
        # (8192, .env) was tuned for the old local Ollama model's rambling
        # output, not this cap. The real section/candidate-list content is
        # small by comparison (measured live: a 194-entity candidate list is
        # ~1000 tokens) — chunking that wouldn't have helped, since an empty
        # prompt alone already exceeds the cap at max_tokens=8192. Capped
        # here, not in .env, so it only clamps the provider that actually
        # has this limit; gemini/openrouter keep the caller's real budget.
        effective_max_tokens = min(max_tokens, 3000) if ring.provider() == "groq" else max_tokens
        try:
            response = _client(ring).chat.completions.create(
                model=effective_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=effective_max_tokens,
                temperature=temperature,
                **extra,
            )
            if not response.choices:
                # EVAL-002 live finding: an upstream 502 from OpenRouter's
                # underlying model host (nvidia/nemotron-3-ultra-550b-a55b:free)
                # came back as a normal 200 response with choices=None and the
                # error detail buried in a non-standard `error` field instead
                # of a raised HTTPStatusError — the openai SDK has nothing to
                # catch there, so this silently crashed with an unhandled
                # TypeError on response.choices[0] the moment it happened,
                # losing an entire paper's already-completed extraction work
                # (this call is typically one of the last in a long run).
                # Treated exactly like a retryable API error: advance the
                # ring first, only back off once every provider is exhausted.
                detail = getattr(response, "error", None)
                logger.warning(
                    "llm.empty_choices",
                    provider=ring.provider(),
                    model=effective_model,
                    detail=detail,
                )
                if ring.advance():
                    continue
                backoff_attempt += 1
                if backoff_attempt >= _MAX_ATTEMPTS:
                    raise RuntimeError(f"LLM call returned no choices: {detail}")
                backoff = 2**backoff_attempt
                logger.warning("llm.retry", attempt=backoff_attempt, backoff_seconds=backoff)
                time.sleep(backoff)
                continue
            content = response.choices[0].message.content
            # .strip() check, not bare truthiness: a whitespace-only string
            # ("   "/"\n") is truthy in Python, so `if not content:` let a
            # near-blank completion sail straight through as a "real"
            # answer - rendered as visually empty markdown while sources
            # still showed, indistinguishable from this exact bug's
            # original symptom. Same retry/failover treatment either way.
            if not content or not content.strip():
                # Live finding 2026-08-20 (Compare page): choices non-empty
                # (so the check above doesn't catch it) but message.content
                # itself is None/"" - a "successful" call that produced
                # nothing usable (seen with reasoning-style models that can
                # put text in a different field, or a genuine empty-gen
                # glitch). This used to `return ""` here with no retry, no
                # failover, no error - a real answer silently became an
                # empty string with nothing downstream able to tell the
                # difference from "the model legitimately said nothing".
                # Same treatment as the empty-choices case just above:
                # advance the ring and retry before giving up.
                logger.warning("llm.empty_content", provider=ring.provider(), model=effective_model)
                if ring.advance():
                    continue
                backoff_attempt += 1
                if backoff_attempt >= _MAX_ATTEMPTS:
                    raise RuntimeError("LLM call returned an empty message")
                backoff = 2**backoff_attempt
                logger.warning("llm.retry", attempt=backoff_attempt, backoff_seconds=backoff)
                time.sleep(backoff)
                continue
            usage = response.usage
            logger.info(
                "llm.completion",
                provider=ring.provider(),
                model=effective_model,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            )
            return content
        except (AuthenticationError, BadRequestError):
            raise
        except (RateLimitError, InternalServerError, APIStatusError):
            if ring.advance():
                continue
            backoff_attempt += 1
            if backoff_attempt >= _MAX_ATTEMPTS:
                raise
            backoff = 2**backoff_attempt
            logger.warning("llm.retry", attempt=backoff_attempt, backoff_seconds=backoff)
            time.sleep(backoff)
        except _RETRYABLE:
            # Same "advance before backing off" logic as the branch above —
            # this docstring already claimed that behavior, but the code
            # didn't actually call ring.advance() here, so a connection
            # hiccup on one provider burned all _MAX_ATTEMPTS retries against
            # that same provider instead of trying the next one first.
            if ring.advance():
                continue
            backoff_attempt += 1
            if backoff_attempt >= _MAX_ATTEMPTS:
                raise
            backoff = 2**backoff_attempt
            logger.warning("llm.retry", attempt=backoff_attempt, backoff_seconds=backoff)
            time.sleep(backoff)
