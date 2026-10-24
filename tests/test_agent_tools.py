# -*- coding: utf-8 -*-
"""Agent Tool 封装与 LangGraph 冒烟单测（不连数据库、不调真实 API）。"""
from agent import tools as agent_tools
from agent.graph_smoke import build_smoke_graph


def test_query_user_profiles_wraps_wizard_response(monkeypatch):
    captured = {}

    def fake_query(question, dataset):
        captured.update({"question": question, "dataset": dataset})
        return {
            "answer": "上海黑卡流失用户 1 人",
            "sources": [{"source": "user_profile", "text": "画像"}],
            "route": "rag",
            "dataset": dataset,
            "busy": False,
        }

    monkeypatch.setenv("QIANKE_AGENT_DATASET", "demo")
    monkeypatch.setattr(agent_tools, "_post_wizard_query", fake_query)

    result = agent_tools.query_user_profiles.invoke({"query": "上海的黑卡流失用户有哪些"})

    assert result["ok"] is True
    assert result["route"] == "rag"
    assert len(result["sources"]) == 1
    assert result["sources"][0]["source"] == "user_profile"
    assert captured == {"question": "上海的黑卡流失用户有哪些", "dataset": "demo"}


def test_query_user_profiles_reports_http_failure(monkeypatch):
    def fail_query(question, dataset):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(agent_tools, "_post_wizard_query", fail_query)

    result = agent_tools.query_user_profiles.invoke({"query": "上海用户"})

    assert result["ok"] is False
    assert "connection refused" in result["error"]


def test_get_operation_sop_filters_docs(monkeypatch):
    def fake_search(topic, dataset):
        assert topic == "召回方案"
        assert dataset == "demo"
        return [
            {"source": "marketing_playbook.md", "text": "大额无门槛券", "rerank_score": 0.9},
            {"source": "user_profile", "text": "这是一条画像，不是 SOP", "rerank_score": 0.8},
            {"source": "tag_definitions.md", "text": "流失预警定义", "rerank_score": 0.7},
        ]

    monkeypatch.setenv("QIANKE_AGENT_DATASET", "demo")
    monkeypatch.setattr(agent_tools, "_search_sop", fake_search)

    result = agent_tools.get_operation_sop.invoke({"topic": "召回方案"})

    assert result["ok"] is True
    assert result["count"] == 2
    assert [s["source"] for s in result["sources"]] == [
        "marketing_playbook.md",
        "tag_definitions.md",
    ]


def test_smoke_graph_compiles():
    graph = build_smoke_graph()
    assert graph is not None
    # CompiledStateGraph 暴露 nodes；确认两个工具节点都在图里
    assert {"analyst", "copywriter"} <= set(graph.get_graph().nodes)
