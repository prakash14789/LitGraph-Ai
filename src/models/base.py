"""Shared declarative base — every model's metadata lives here so Alembic
autogenerate (and create_all in tests) sees the whole schema in one place."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
