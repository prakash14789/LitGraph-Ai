"""POLISH-001 — request-ID correlation + a catch-all exception handler.

Without this, an unhandled exception anywhere in a route bubbles up to
FastAPI/Starlette's default handler: a bare 500 with no response body
structure, and nothing in the response ties it back to the matching log
line for a developer trying to debug a user's bug report. Every response
(success or error) now carries an X-Request-ID header, and that same ID is
bound into structlog's contextvars for the request's whole lifetime — every
log line during the request, including the traceback log if it fails,
already includes it via `merge_contextvars` (see src/utils/logging.py) with
no per-call plumbing needed.

Both concerns live in ONE middleware's dispatch(), not a request-ID
middleware plus a separate `@app.exception_handler(Exception)` — Starlette's
BaseHTTPMiddleware wraps call_next() in its own task group, and an
exception handler registered separately doesn't reliably intercept an
exception raised inside that wrapped call before it re-propagates past the
middleware (a known Starlette gotcha, confirmed live: the handler's log
line fired, but the original exception still reached the test client
instead of the handler's response). Catching directly in this dispatch()
sidesteps that entirely — there's nothing left for an exception to
propagate past.
"""

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

# Live finding 2026-08-20: llm_client.complete() walks its whole provider
# chain (gemini -> groq -> openrouter) and only re-raises one of these once
# every provider/key is genuinely exhausted or unreachable - a real,
# expected state under heavy free-tier usage, not a server bug. It used to
# land here as an indistinguishable generic 500 ("internal server error"),
# which read to a user exactly like a crash. AuthenticationError/
# BadRequestError deliberately excluded - llm_client.py itself treats those
# as immediately-fatal config/bug errors (bad key, bad request), never
# retries them, so they should keep surfacing as a real 500, not this.
_LLM_EXHAUSTED = (
    RateLimitError,
    InternalServerError,
    APIStatusError,
    APITimeoutError,
    APIConnectionError,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            try:
                response = await call_next(request)
            except _LLM_EXHAUSTED as exc:
                logger.error(
                    "llm_providers_exhausted",
                    path=request.url.path,
                    method=request.method,
                    error=str(exc),
                    exc_info=exc,
                )
                response = JSONResponse(
                    status_code=503,
                    content={
                        "detail": "AI provider temporarily unavailable (rate-limited or "
                        "overloaded across every configured provider) — please try again "
                        "in a while.",
                        "request_id": request_id,
                    },
                )
            except Exception as exc:
                logger.error(
                    "unhandled_exception",
                    path=request.url.path,
                    method=request.method,
                    error=str(exc),
                    exc_info=exc,
                )
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "internal server error", "request_id": request_id},
                )
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-ID"] = request_id
        return response


def install_error_handling(app: FastAPI) -> None:
    app.add_middleware(RequestIDMiddleware)
