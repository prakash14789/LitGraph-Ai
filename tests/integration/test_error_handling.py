"""Integration tests for POLISH-001's request-ID + catch-all exception
handler (src/api/middleware.py) — real ASGI app via the test_client
fixture, same pattern as the other route integration tests."""

import uuid

import pytest

pytestmark = pytest.mark.anyio


async def test_successful_response_carries_request_id_header(test_client):
    response = await test_client.get("/health")
    assert response.status_code == 200
    assert uuid.UUID(response.headers["X-Request-ID"])  # parses as a real UUID


async def test_known_http_exception_still_carries_request_id(test_client):
    # A route-raised HTTPException (404 here) must not get swallowed by the
    # catch-all Exception handler — Starlette's own handler still runs it,
    # this only asserts the request-ID middleware wraps that path too.
    response = await test_client.get(f"/api/v1/papers/{uuid.uuid4()}")
    assert response.status_code == 404
    assert uuid.UUID(response.headers["X-Request-ID"])


async def test_unhandled_exception_returns_clean_500_with_request_id(test_client):
    from src.main import app

    @app.get("/api/v1/_test_boom")
    async def _boom():
        raise RuntimeError("boom")

    try:
        response = await test_client.get("/api/v1/_test_boom")
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/api/v1/_test_boom"
        ]

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "internal server error"
    assert uuid.UUID(body["request_id"])
    assert response.headers["X-Request-ID"] == body["request_id"]
