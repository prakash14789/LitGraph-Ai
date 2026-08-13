"""Unit tests for src.utils.llm_client — mocked client, no real API calls."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from src.utils.llm_client import _API_KEYS, _BASE_URLS, _KeyRing, _RateLimiter, complete


def test_every_provider_has_a_base_url_and_key_list():
    # Catches the easy typo: adding a provider to one dict and forgetting
    # the other (both are keyed by settings.llm_provider's Literal values).
    assert (
        set(_BASE_URLS) == set(_API_KEYS) == {"gemini", "openai", "anthropic", "groq", "openrouter"}
    )


def _http_error(cls, status_code: int):
    response = httpx.Response(status_code, request=httpx.Request("POST", "http://x"))
    return cls("boom", response=response, body=None)


def _fake_response(text: str = "ok"):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
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


def test_rate_limiter_throttles_when_limit_hit():
    limiter = _RateLimiter(max_per_minute=2)
    limiter._calls = [0.0, 0.0]  # pretend 2 calls just happened at t=0

    with patch("time.monotonic", return_value=1.0), patch("time.sleep") as mock_sleep:
        limiter.wait()

    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(59.0)
