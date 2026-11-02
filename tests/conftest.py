"""测试隔离：每个用例使用独立的商家 SQLite 库，避免 C 端下单测试互相污染。"""
from __future__ import annotations

import pytest

from rag_demo.merchant import reset_merchant_repository_cache


@pytest.fixture(autouse=True)
def _isolate_merchant_db(tmp_path, monkeypatch):
    # 离线套件固定 SQLite；PG 专项测试自己显式设置 postgres。
    monkeypatch.setenv("QIANKE_MERCHANT_BACKEND", "sqlite")
    monkeypatch.setenv("QIANKE_MERCHANT_DB", str(tmp_path / "merchant.sqlite"))
    # 自动 Trigger / 常驻 Watchdog 只用于真实运行，测试默认关闭，避免后台线程和 LLM。
    monkeypatch.setenv("QIANKE_SUPERAGENT_AUTO_TRIGGER", "0")
    monkeypatch.setenv("QIANKE_SUPERAGENT_AUTO_RUN", "0")
    monkeypatch.setenv("QIANKE_SUPERAGENT_LLM_ROUTER", "0")
    monkeypatch.setenv("QIANKE_SUPERAGENT_WATCHDOG_ENABLED", "0")
    reset_merchant_repository_cache()
    yield
    reset_merchant_repository_cache()
