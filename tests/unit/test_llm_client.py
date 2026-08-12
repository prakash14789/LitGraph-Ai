"""Unit tests for src.utils.llm_client — mocked client, no real API calls."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from src.utils.llm_client import _RateLimiter, complete


def _http_error(cls, status_code: int):
    response = httpx.Response(status_code, request=httpx.Request("POST", "http://x"))
    return cls("boom", response=response, body=None)


def _fake_response(text: str = "ok"):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return response


@patch("src.utils.llm_client._rate_limiter", _RateLimiter(max_per_minute=999))
@patch("src.utils.llm_client._client")
def test_complete_retries_then_succeeds(mock_client, mock_sleep=None):
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
@patch("src.utils.llm_client._client")
def test_complete_does_not_retry_auth_error(mock_client):
    client = MagicMock()
    client.chat.completions.create.side_effect = _http_error(AuthenticationError, 401)
    mock_client.return_value = client

    with pytest.raises(AuthenticationError):
        complete("sys", "user", model="gemini-2.5-flash")

    assert client.chat.completions.create.call_count == 1


def test_rate_limiter_throttles_when_limit_hit():
    limiter = _RateLimiter(max_per_minute=2)
    limiter._calls = [0.0, 0.0]  # pretend 2 calls just happened at t=0

    with patch("time.monotonic", return_value=1.0), patch("time.sleep") as mock_sleep:
        limiter.wait()

    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(59.0)
