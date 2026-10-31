"""测试隔离：每个用例使用独立的商家 SQLite 库，避免 C 端下单测试互相污染。"""
from __future__ import annotations

import pytest

from rag_demo.merchant import reset_merchant_repository_cache


@pytest.fixture(autouse=True)
def _isolate_merchant_db(tmp_path, monkeypatch):
    # 离线套件固定 SQLite；PG 专项测试自己显式设置 postgres。
    monkeypatch.setenv("QIANKE_MERCHANT_BACKEND", "sqlite")
    monkeypatch.setenv("QIANKE_MERCHANT_DB", str(tmp_path / "merchant.sqlite"))
    reset_merchant_repository_cache()
    yield
    reset_merchant_repository_cache()
