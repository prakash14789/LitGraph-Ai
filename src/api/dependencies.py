"""FastAPI dependency injection — DB sessions (auth deps added when SETUP adds auth, not MVP)."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.db import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yields a session scoped to one request/unit-of-work: commits once if
    the request handler completes without raising, rolls back the whole
    transaction on any exception, and always closes the connection via the
    `async with` block. Repository methods only flush, not commit — this is
    where the actual commit boundary lives, so multiple repository calls in
    one request are atomic together."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
