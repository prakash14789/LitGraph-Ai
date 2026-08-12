"""Async SQLAlchemy engine + session factory. Single source for both the app
(via src/api/dependencies.py) and Alembic (via alembic/env.py)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
