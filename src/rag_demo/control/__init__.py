"""控制面存储抽象（P1 骨架）。"""
from .factory import PostgresControlRepository, SQLiteControlRepository, get_control_repository

__all__ = [
    "PostgresControlRepository",
    "SQLiteControlRepository",
    "get_control_repository",
]
