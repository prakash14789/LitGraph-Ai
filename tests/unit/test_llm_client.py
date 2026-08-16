"""Unit tests for src.utils.llm_client — mocked client, no real API calls."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import AuthenticationError, InternalServerError, RateLimitError

from src.utils.llm_client import _API_KEYS, _BASE_URLS, _KeyRing, _RateLimiter, complete


def test_every_provider_has_a_base_url_and_key_list():
    # Catches the easy typo: adding a provider to one dict and forgetting
    # the other (both are keyed by settings.llm_provider's Literal values).
    assert (
        set(_BASE_URLS)
        == set(_API_KEYS)
        == {
            "gemini",
            "openai",
            "anthropic",
            "groq",
            "openrouter",
            "cerebras",
            "huggingface",
            "ollama",
        }
    )


def _http_error(cls, status_code: int):
    response = httpx.Response(status_code, request=httpx.Request("POST", "http://x"))
    return cls("boom", response=response, body=None)


def _fake_response(text: str = "ok"):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return response


def _empty_choices_response(error_detail="upstream error"):
    # EVAL-002 live finding: OpenRouter's upstream-502 response — a normal
    # 200 with choices=None and the error tucked in a non-standard field,
    # not a raised exception.
    response = MagicMock()
    response.choices = None
    response.error = error_detail
    return response


# _key_ring is a module-level singleton that permanently advances on quota
# errors (by design — see its docstring) — every test patches it fresh so
# one test's rotation can't bleed into the next.


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._key_ring", _KeyRing(["only-key"]))
@patch("src.utils.llm_client._client")
def test_complete_retries_then_succeeds(mock_client):
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _http_error(RateLimitError, 429),
        _fake_response("answer"),
    ]
    mock_client.return_value = client

    with patch("time.sleep"):  # skip real backoff delay
        result = complete("sys", "user", model="gemini-2.5-flash")

    assert result == "answer"
    assert client.chat.completions.create.call_count == 2


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._key_ring", _KeyRing(["only-key"]))
@patch("src.utils.llm_client._client")
def test_complete_does_not_retry_auth_error(mock_client):
    client = MagicMock()
    client.chat.completions.create.side_effect = _http_error(AuthenticationError, 401)
    mock_client.return_value = client

    with pytest.raises(AuthenticationError):
        complete("sys", "user", model="gemini-2.5-flash")

    assert client.chat.completions.create.call_count == 1


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._key_ring", _KeyRing(["key-1", "key-2"]))
@patch("src.utils.llm_client._client")
def test_quota_error_switches_key_without_backoff_or_raising(mock_client):
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _http_error(RateLimitError, 429),
        _fake_response("answer from key 2"),
    ]
    mock_client.return_value = client

    with patch("time.sleep") as mock_sleep:
        result = complete("sys", "user", model="gemini-flash-latest")

    assert result == "answer from key 2"
    mock_sleep.assert_not_called()  # key switch is immediate, no backoff wait


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._key_ring", _KeyRing(["key-1", "key-2"]))
@patch("src.utils.llm_client._client")
def test_quota_error_falls_back_to_backoff_once_all_keys_exhausted(mock_client):
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _http_error(RateLimitError, 429),  # key-1 exhausted, switches to key-2
        _http_error(RateLimitError, 429),  # key-2 also exhausted, no more keys
        _fake_response("recovered on backoff retry"),
    ]
    mock_client.return_value = client

    with patch("time.sleep") as mock_sleep:
        result = complete("sys", "user", model="gemini-flash-latest")

    assert result == "recovered on backoff retry"
    assert client.chat.completions.create.call_count == 3
    mock_sleep.assert_called_once()  # only the post-exhaustion retry backs off


def test_key_ring_advances_forward_and_never_wraps():
    ring = _KeyRing(["key-1", "key-2"])
    assert ring.current() == "key-1"
    assert ring.advance() is True
    assert ring.current() == "key-2"
    assert ring.advance() is False  # no more keys
    assert ring.current() == "key-2"  # stays put, doesn't wrap back to key-1


def test_key_ring_single_key_never_advances():
    ring = _KeyRing(["only-key"])
    assert ring.advance() is False


# --- EVAL-001: cross-provider failover ---------------------------------
# _KeyRing() (zero-arg) reads settings.llm_provider/_API_KEYS at
# construction time, so unlike the tests above (which pass a keys list and
# can use @patch decorators freely), these build the ring *inside* the
# test body after the fakes are already patched in via `with`.

_FAKE_KEYS = {
    "gemini": ["g-key"],
    "groq": ["q-key"],
    "openai": [],
    "anthropic": [],
    "openrouter": [],
}


def test_key_ring_builds_and_advances_across_providers():
    with (
        patch("src.utils.llm_client._API_KEYS", _FAKE_KEYS),
        patch("src.utils.llm_client.settings.llm_provider", "gemini"),
    ):
        ring = _KeyRing()
        assert ring.provider() == "gemini"
        assert ring.model_override() is None  # primary provider uses the caller's own model
        assert ring.advance() is True  # gemini's only key exhausted -> falls to groq
        assert ring.provider() == "groq"
        assert ring.model_override() == "llama-3.3-70b-versatile"
        assert ring.advance() is False  # openai/anthropic/openrouter have no keys configured


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
def test_complete_fails_over_to_next_provider_on_quota_exhaustion():
    with (
        patch("src.utils.llm_client._API_KEYS", _FAKE_KEYS),
        patch("src.utils.llm_client.settings.llm_provider", "gemini"),
    ):
        ring = _KeyRing()

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _http_error(RateLimitError, 429),  # gemini exhausted
        _fake_response("answer from groq"),
    ]
    with (
        patch("src.utils.llm_client._key_ring", ring),
        patch("src.utils.llm_client._client", return_value=client),
        patch("time.sleep") as mock_sleep,
    ):
        result = complete("sys", "user", model="gemini-flash-latest")

    assert result == "answer from groq"
    mock_sleep.assert_not_called()  # provider switch is immediate, no backoff wait
    assert ring.provider() == "groq"
    # the 2nd call must use groq's own model, not the caller's gemini model string
    assert (
        client.chat.completions.create.call_args_list[1].kwargs["model"]
        == "llama-3.3-70b-versatile"
    )


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
def test_complete_fails_over_on_server_overload_not_just_quota():
    # A 5xx "model overloaded" error isn't a quota error, but retrying the
    # *same* model won't fix genuine overload either — this should advance
    # to the next provider exactly like a 429 does, not sit in a backoff
    # loop hammering the same overloaded model.
    with (
        patch("src.utils.llm_client._API_KEYS", _FAKE_KEYS),
        patch("src.utils.llm_client.settings.llm_provider", "gemini"),
    ):
        ring = _KeyRing()

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _http_error(InternalServerError, 503),
        _fake_response("answer from groq"),
    ]
    with (
        patch("src.utils.llm_client._key_ring", ring),
        patch("src.utils.llm_client._client", return_value=client),
        patch("time.sleep") as mock_sleep,
    ):
        result = complete("sys", "user", model="gemini-flash-latest")

    assert result == "answer from groq"
    mock_sleep.assert_not_called()
    assert ring.provider() == "groq"


# --- EVAL-002 live finding: OpenRouter's empty-choices-on-502 response -----


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
def test_complete_fails_over_when_response_has_no_choices():
    # Previously an unhandled TypeError on response.choices[0] — nothing in
    # the except clauses catches it, so it crashed the whole call (and, live,
    # an entire paper's already-completed extraction work) instead of
    # advancing to the next provider like a real API error does.
    with (
        patch("src.utils.llm_client._API_KEYS", _FAKE_KEYS),
        patch("src.utils.llm_client.settings.llm_provider", "gemini"),
    ):
        ring = _KeyRing()

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _empty_choices_response("upstream 502"),
        _fake_response("answer from groq"),
    ]
    with (
        patch("src.utils.llm_client._key_ring", ring),
        patch("src.utils.llm_client._client", return_value=client),
        patch("time.sleep") as mock_sleep,
    ):
        result = complete("sys", "user", model="gemini-flash-latest")

    assert result == "answer from groq"
    mock_sleep.assert_not_called()
    assert ring.provider() == "groq"


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._key_ring", _KeyRing(["only-key"]))
@patch("src.utils.llm_client._client")
def test_complete_raises_after_exhausting_providers_on_empty_choices(mock_client):
    client = MagicMock()
    client.chat.completions.create.return_value = _empty_choices_response("still 502")
    mock_client.return_value = client

    with patch("time.sleep"), pytest.raises(RuntimeError, match="still 502"):
        complete("sys", "user", model="gemini-2.5-flash")


# --- qwen reasoning-model handling ---------------------------------------


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._key_ring", _KeyRing(["only-key"]))
@patch("src.utils.llm_client._client")
def test_qwen_model_gets_reasoning_effort_none(mock_client):
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response('{"score": 1.0}')
    mock_client.return_value = client

    complete("sys", "user", model="qwen/qwen3.6-27b")

    assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "none"


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._key_ring", _KeyRing(["only-key"]))
@patch("src.utils.llm_client._client")
def test_non_qwen_model_gets_no_reasoning_effort_kwarg(mock_client):
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("answer")
    mock_client.return_value = client

    complete("sys", "user", model="llama-3.3-70b-versatile")

    assert "reasoning_effort" not in client.chat.completions.create.call_args.kwargs


# --- EVAL-002 FIX E: caller-supplied independent key_ring ---------------


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._client")
def test_complete_uses_caller_supplied_ring_instead_of_shared_one(mock_client):
    shared_ring = _KeyRing(["shared-key"])
    own_ring = _KeyRing(["own-key-1", "own-key-2"])
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _http_error(RateLimitError, 429),  # own-key-1 exhausted
        _fake_response("answer from own ring"),
    ]
    mock_client.return_value = client

    with (
        patch("src.utils.llm_client._key_ring", shared_ring),
        patch("time.sleep"),
    ):
        result = complete("sys", "user", model="m", key_ring=own_ring)

    assert result == "answer from own ring"
    # the caller's own ring advanced...
    assert own_ring.current() == "own-key-2"
    # ...but the shared module ring a caller *didn't* pass was never touched.
    assert shared_ring.current() == "shared-key"


def test_rate_limiter_throttles_when_limit_hit():
    limiter = _RateLimiter(max_per_minute=2)
    limiter._calls = [0.0, 0.0]  # pretend 2 calls just happened at t=0

    with patch("time.monotonic", return_value=1.0), patch("time.sleep") as mock_sleep:
        limiter.wait()

    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(59.0)
