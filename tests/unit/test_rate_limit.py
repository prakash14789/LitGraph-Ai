"""POLISH-002 self-check: proves the slowapi wiring (Limiter + exception
handler + SlowAPIMiddleware, see src/main.py) actually turns a request over
a decorated limit into a 429 — not exercised by the real endpoints since
conftest.py disables the limiter for the shared test_client fixture."""

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.api.rate_limit import limiter

pytestmark = pytest.mark.anyio


async def test_exceeding_a_decorated_limit_returns_429():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/_rl_test")
    @limiter.limit("2/minute")
    async def _endpoint(request: Request):
        return {"ok": True}

    limiter.enabled = True
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/_rl_test")).status_code == 200
            assert (await client.get("/_rl_test")).status_code == 200
            third = await client.get("/_rl_test")
            assert third.status_code == 429
    finally:
        limiter.enabled = False  # restore conftest's blanket disable for other tests
