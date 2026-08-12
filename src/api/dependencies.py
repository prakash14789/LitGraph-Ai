"""FastAPI dependency injection — DB sessions (auth deps added when SETUP adds auth, not MVP)."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.db import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yields a session and always closes it — the `async with` block closes
    the connection whether the request succeeds, raises, or is cancelled."""
    async with AsyncSessionLocal() as session:
        yield session
