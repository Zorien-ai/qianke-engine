"""B 店宠 Agent 的唤醒闸门与工具链测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from rag_demo.c_end import social, store, store_agent


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self._responses.pop(0)


def _catalog_call():
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "search_catalog",
            "args": {"need": "跑鞋", "budget": 300},
            "id": "call_catalog_1",
            "type": "tool_call",
        }],
    )


def _policy_call():
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "search_store_policy",
            "args": {"topic": "活动"},
            "id": "call_policy_1",
            "type": "tool_call",
        }],
    )


def test_intent_gate_requires_wake_and_business_intent():
    assert store_agent.intent_gate("这双鞋多少钱") == (False, False, "这双鞋多少钱")
    assert store_agent.intent_gate("@店宠 你好") == (True, False, "你好")
    wake, allowed, cleaned = store_agent.intent_gate("@店宠 推荐一双跑鞋")
    assert (wake, allowed, cleaned) == (True, True, "推荐一双跑鞋")


def test_reply_without_wake_does_not_call_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "store_agent.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    fake = _FakeLLM([])
    text, awakened = store_agent.reply("buyer_1", "这双鞋多少钱", llm=fake)
    assert awakened is False
    assert "未被唤醒" in text
    assert fake.calls == 0


def test_reply_with_wake_uses_catalog_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "store_agent_catalog.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    fake = _FakeLLM([_catalog_call(), AIMessage(content="推荐 P001 轻量跑鞋")])
    text, awakened = store_agent.reply("buyer_1", "@店宠 推荐一双跑鞋，预算 300", llm=fake)
    assert awakened is True
    assert "P001" in text
    assert fake.calls == 2


def test_reply_can_query_sop_and_platform_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "store_agent_policy.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    fake = _FakeLLM([_policy_call(), AIMessage(content="平台满 299 减 30，以结算页为准")])
    result = store_agent.reply_with_meta("buyer_1", "@店宠 现在有什么活动", llm=fake)
    assert result.awakened is True
    assert "满 299" in result.text
    assert result.metadata["requires_user_confirmation"] is True
    assert result.metadata["policy_refs"]
    assert fake.calls == 2


def test_companion_commentary_is_text_only(tmp_path, monkeypatch):
    from rag_demo.c_end import companion_agent

    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "companion_comment.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()

    class _FakeCommentLLM:
        def invoke(self, messages):
            return AIMessage(content="主人，先看清活动规则再决定。")

    text = companion_agent.commentary(
        "buyer_1",
        "有什么优惠",
        "平台满 299 减 30",
        llm=_FakeCommentLLM(),
    )
    assert text == "主人，先看清活动规则再决定。"


def test_social_accepts_store_agent_reply_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "social_agent.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    social.init()
    result = social.send_message(
        "buyer_1",
        "store_demo",
        "@店宠 推荐跑鞋",
        reply_provider=lambda text: store_agent.StoreReply(
            "店宠 Agent 回复",
            True,
            {"quote_id": "quote_1", "requires_user_confirmation": True},
        ),
        commentary_provider=lambda text, reply: "主人，先核对活动规则。",
    )
    assert result["reply"]["content"] == "店宠 Agent 回复"
    assert result["reply"]["awakened"] is True
    assert result["reply"]["metadata"]["quote_id"] == "quote_1"
    assert result["companion_message"]["content"] == "主人，先核对活动规则。"
    assert len(social.get_messages("buyer_1", "store_demo")) == 3
