"""Generic repository — one implementation of create/get_by_id/list/delete,
parametrized by model, instead of four near-identical classes.

Deliberately does NOT commit — create/delete only flush (visible within the
current transaction, not yet durable). The caller's session owns the
transaction boundary (see src/api/dependencies.get_db, which commits once at
the end of the request). This lets multiple repository calls in one request
share one atomic commit/rollback instead of each committing independently —
e.g. INGEST-004 creating a Paper + ExtractionJob together must not leave an
orphaned Paper if the second insert fails."""

import uuid
from typing import Generic, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class Repository(Generic[ModelType]):
    def __init__(self, model: type[ModelType]) -> None:
        self.model = model

    async def create(self, session: AsyncSession, **kwargs) -> ModelType:
        obj = self.model(**kwargs)
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def get_by_id(self, session: AsyncSession, id: uuid.UUID) -> ModelType | None:
        return await session.get(self.model, id)

    async def list(
        self, session: AsyncSession, limit: int = 100, offset: int = 0
    ) -> Sequence[ModelType]:
        result = await session.execute(select(self.model).limit(limit).offset(offset))
        return result.scalars().all()

    async def delete(self, session: AsyncSession, id: uuid.UUID) -> bool:
        obj = await self.get_by_id(session, id)
        if obj is None:
            return False
        await session.delete(obj)
        await session.flush()
        return True
