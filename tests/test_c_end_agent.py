"""C 端 Agent：推荐 → 草稿 → interrupt 确认 → 模拟订单。"""
from __future__ import annotations

import sqlite3

import pytest
from langchain_core.messages import AIMessage

from rag_demo.c_end import agent as c_agent
from rag_demo.c_end import store


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self._responses.pop(0)


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _prepare_call():
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "prepare_order",
            "args": {"items": [{"product_id": "P001", "quantity": 1}]},
            "id": "call_prepare_1",
            "type": "tool_call",
        }],
    )


def test_c_agent_interrupts_before_order_and_resumes(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    saver = sqlite_checkpointer(tmp_path / "c_agent.sqlite")
    fake = _FakeLLM([_prepare_call()])
    result = c_agent.run_c_agent(
        "我想买一双跑鞋",
        buyer_id="buyer_1",
        thread_id="c_thread_test_1",
        checkpointer=saver,
        llm=fake,
    )

    assert result["interrupted"] is True
    assert result["draft"]["order_id"]
    assert result["draft"]["confirmation_token"]

    resumed = c_agent.resume_c_agent(
        buyer_id="buyer_1",
        thread_id="c_thread_test_1",
        approved=True,
        checkpointer=saver,
        llm=fake,
    )
    assert resumed["status"] == "CONFIRMED"
    assert resumed["order"]["order_id"].startswith("order_")

    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        stock = conn.execute("SELECT stock FROM c_product WHERE product_id = 'P001'").fetchone()[0]
    finally:
        conn.close()
    assert stock == 19


def test_c_agent_rejects_confirmation(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    saver = sqlite_checkpointer(tmp_path / "c_agent_reject.sqlite")
    fake = _FakeLLM([_prepare_call()])
    c_agent.run_c_agent(
        "买一双跑鞋",
        buyer_id="buyer_1",
        thread_id="c_thread_reject_1",
        checkpointer=saver,
        llm=fake,
    )
    resumed = c_agent.resume_c_agent(
        buyer_id="buyer_1",
        thread_id="c_thread_reject_1",
        approved=False,
        checkpointer=saver,
        llm=fake,
    )
    assert resumed["status"] == "CANCELLED"
    assert resumed["order"] is None
