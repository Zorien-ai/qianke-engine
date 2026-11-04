"""控制面 repository 工厂。"""
from __future__ import annotations

from .postgres_repository import PostgresControlRepository
from .settings import backend
from .sqlite_repository import SQLiteControlRepository


def get_control_repository(*, schema: str | None = None):
    if backend() == "postgres":
        return PostgresControlRepository(schema=schema)
    return SQLiteControlRepository()


__all__ = [
    "PostgresControlRepository",
    "SQLiteControlRepository",
    "get_control_repository",
]
