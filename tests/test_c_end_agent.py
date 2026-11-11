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
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
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
    assert result["status"] == "AWAITING_CONFIRMATION"
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


def test_c_agent_recommend_without_order(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    saver = sqlite_checkpointer(tmp_path / "c_agent_recommend.sqlite")
    fake = _FakeLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "recommend_products",
                "args": {"need": "跑鞋", "budget": 300},
                "id": "call_rec_1",
                "type": "tool_call",
            }],
        ),
        AIMessage(content="推荐 P001 轻量跑鞋"),
    ])
    result = c_agent.run_c_agent(
        "500 以内推荐一双跑鞋",
        buyer_id="buyer_1",
        thread_id="c_thread_recommend_1",
        checkpointer=saver,
        llm=fake,
    )
    assert result["interrupted"] is False
    assert result["status"] == "COMPLETED"
    assert result["draft"] is None


def test_c_agent_companion_mode_does_not_expose_tools(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    saver = sqlite_checkpointer(tmp_path / "c_agent_companion.sqlite")
    fake = _FakeLLM([AIMessage(content="今天先不聊商品，说说你今天怎么了。")])
    result = c_agent.run_c_agent(
        "今天有点累，陪我聊聊",
        buyer_id="buyer_1",
        thread_id="c_thread_companion_1",
        checkpointer=saver,
        llm=fake,
    )
    assert result["interrupted"] is False
    assert result["status"] == "COMPLETED"
    assert result["mode"] == "companion"
    assert result["draft"] is None


def test_c_agent_advisor_mode_recommends_without_order(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    saver = sqlite_checkpointer(tmp_path / "c_agent_advisor.sqlite")
    fake = _FakeLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "recommend_products",
                "args": {"need": "跑鞋", "budget": 300},
                "id": "call_advisor_1",
                "type": "tool_call",
            }],
        ),
        AIMessage(content="这两双可以对比一下，先不生成订单。"),
    ])
    result = c_agent.run_c_agent(
        "帮我挑一双 300 以内的跑鞋",
        buyer_id="buyer_1",
        thread_id="c_thread_advisor_1",
        checkpointer=saver,
        llm=fake,
    )
    assert result["mode"] == "advisor"
    assert result["interrupted"] is False
    assert result["draft"] is None


def test_c_agent_continues_same_thread_with_history(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    saver = sqlite_checkpointer(tmp_path / "c_agent_multi.sqlite")
    fake = _FakeLLM([AIMessage(content="第一轮回答"), AIMessage(content="第二轮回答")])
    first = c_agent.run_c_agent(
        "我叫小明，喜欢跑步",
        buyer_id="buyer_1",
        thread_id="c_thread_multi_1",
        checkpointer=saver,
        llm=fake,
    )
    second = c_agent.run_c_agent(
        "我叫什么名字",
        buyer_id="buyer_1",
        thread_id="c_thread_multi_1",
        checkpointer=saver,
        llm=fake,
    )
    assert first["status"] == "COMPLETED"
    assert second["status"] == "COMPLETED"
    # 第二轮调用必须能看到第一轮的用户消息和回答。
    second_context = "\n".join(str(getattr(m, "content", "")) for m in fake.calls[-1])
    assert "我叫小明" in second_context
    assert "第一轮回答" in second_context


def test_c_agent_new_thread_loads_persisted_app_history(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    c_store.save_app_message("buyer_1", "companion", "user", "我第一个问题是什么")
    c_store.save_app_message("buyer_1", "companion", "companion", "你第一个问题是我该买什么。")
    saver = sqlite_checkpointer(tmp_path / "c_agent_seed.sqlite")
    fake = _FakeLLM([AIMessage(content="你第一个问题是我该买什么。")])
    c_agent.run_c_agent(
        "那第二个问题呢",
        buyer_id="buyer_1",
        thread_id="c_thread_seed_1",
        checkpointer=saver,
        llm=fake,
    )
    context = "\n".join(str(getattr(m, "content", "")) for m in fake.calls[-1])
    assert "我第一个问题是什么" in context
    assert "你第一个问题是我该买什么" in context


def test_c_agent_cannot_resume_other_buyer(c_store, tmp_path):
    from rag_demo.agent.checkpoint import sqlite_checkpointer

    saver = sqlite_checkpointer(tmp_path / "c_agent_owner.sqlite")
    fake = _FakeLLM([_prepare_call()])
    c_agent.run_c_agent(
        "买一双跑鞋",
        buyer_id="buyer_1",
        thread_id="c_thread_owner_1",
        checkpointer=saver,
        llm=fake,
    )
    with pytest.raises(PermissionError):
        c_agent.resume_c_agent(
            buyer_id="buyer_2",
            thread_id="c_thread_owner_1",
            approved=True,
            checkpointer=saver,
            llm=fake,
        )
