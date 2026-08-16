"""POLISH-002: rate limiting via slowapi, keyed by client IP and backed by
the same Redis instance Celery already uses. Limits are the non-auth rows
from docs/03_SECURITY_ACCESS.md §5.1 — the `/auth/*` rows describe the
future production/multi-user system and don't apply (MVP has no auth)."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=["120/minute"],  # §5.1 "all other endpoints" row
)
