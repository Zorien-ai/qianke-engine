"""Agent 执行上下文：把一次 Agent 运行固定到可信数据集。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rag_demo.db.connection import reset_dataset, use_dataset


@contextmanager
def dataset_scope(dataset: str) -> Iterator[str]:
    """在可信 dataset 上执行 Agent，并保证 finally 还原。

    Agent 的 SQL / RAG Tool 内部调用 `get_conn()`，默认走 contextvar。
    因此 API 必须在进入 Graph 前切换 dataset，不能只把 dataset 写进响应体。
    """
    if not dataset:
        raise ValueError("dataset 不能为空")
    token = use_dataset(dataset)
    try:
        yield dataset
    finally:
        reset_dataset(token)
