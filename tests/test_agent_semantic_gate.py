# -*- coding: utf-8 -*-
"""Agent 语义守门回归测试：没有精确匹配时绝不能硬生成“亲爱的”。"""
from types import SimpleNamespace

import agent.service as agent_service


class FakeTool:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        return self.result


def _run(monkeypatch, analyst_result, sop_result=None, llm_text=None,
         query="帮我给上海的黄金流失用户写一段美妆产品的召回短信"):
    monkeypatch.setattr(
        agent_service, "query_user_profiles", FakeTool(analyst_result)
    )
    monkeypatch.setattr(
        agent_service, "get_operation_sop", FakeTool(sop_result or {
            "ok": True,
            "dataset": "test",
            "count": 1,
            "sources": [{"source": "运营SOP.md", "text": "发无门槛100元美妆专用券"}],
        })
    )
    if llm_text is not None:
        import rag_demo.generation.generator as generator

        class FakeResponse:
            choices = [SimpleNamespace(message=SimpleNamespace(content=llm_text))]

        monkeypatch.setattr(generator, "chat_completion", lambda *args, **kwargs: FakeResponse())

    return agent_service.run_agent(
        query,
        dataset="test",
        api_base="http://127.0.0.1:8768",
    )


def test_agent_no_match(monkeypatch):
    # 故意让 analyst 的答案看起来“有 1 位”，但这位是黑卡，不是用户问的黄金；
    # 守门必须靠“请求等级不存在于候选卡”拦住，而不能被候选卡骗过。
    result = _run(monkeypatch, {
        "ok": True,
        "answer": "上海的黑卡用户只有 1 位：最爱喝奶茶；资料里没有黄金等级。",
        "user_cards": [
            {"user_id": "最爱喝奶茶", "city": "上海", "member_level": "黑卡"},
            {"user_id": "小仙女本仙", "city": "北京", "member_level": "金卡"},
        ],
    })

    # LLM 没有被调用；结果必须是固定兜底，不是“亲爱的黑卡VIP”
    assert "未找到匹配用户" in result["final_reply"]
    assert "亲爱的" not in result["final_reply"]


def test_agent_match(monkeypatch):
    result = _run(
        monkeypatch,
        {
            "ok": True,
            "answer": "上海的黑卡流失用户只有 1 位：最爱喝奶茶。",
            "user_cards": [
                {"user_id": "最爱喝奶茶", "city": "上海", "member_level": "黑卡"},
            ],
        },
        llm_text="亲爱的黑卡VIP，为您送上100元美妆券，期待您回来体验。",
        query="帮我给上海的黑卡流失用户写一段美妆产品的召回短信",
    )

    assert "亲爱的" in result["final_reply"]
    assert "黑卡" in result["final_reply"]
    assert "100元美妆券" in result["final_reply"]
