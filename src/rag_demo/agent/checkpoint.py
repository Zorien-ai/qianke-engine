"""LangGraph durable checkpointer。

默认使用 SQLite 文件，便于本地重启后恢复；文件路径可通过
QIANKE_AGENT_CHECKPOINT_PATH 覆盖。测试可自行传入临时 saver。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from rag_demo.config import BASE_DIR

_lock = threading.Lock()
_saver: Any = None


def sqlite_checkpointer(path: str | Path | None = None) -> Any:
    """创建并初始化一个 SQLite checkpointer。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    target = Path(path or os.environ.get("QIANKE_AGENT_CHECKPOINT_PATH") or (Path(BASE_DIR) / "var" / "agent_checkpoints.sqlite"))
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False)
    # WAL 降低并发读写时的锁冲突；旧 SQLite 不支持时忽略。
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def get_checkpointer() -> Any:
    """进程级共享 checkpointer；API 与 Agent 共用。"""
    global _saver
    if _saver is None:
        with _lock:
            if _saver is None:
                _saver = sqlite_checkpointer()
    return _saver
