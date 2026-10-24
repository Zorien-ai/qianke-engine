# -*- coding: utf-8 -*-
"""Supervisor 路由与 Agent 图结构单测（不调 LLM / 不连数据库）。"""
from agent.service import _analyst_query, _sop_topic, _supervisor_decision, build_agent_graph


def test_supervisor_routes_profile_query_to_analyst():
    route, reason = _supervisor_decision("帮我给上海的黑卡流失用户写一段美妆召回短信")
    assert route == "analyst"
    assert "画像" in reason


def test_supervisor_routes_pure_sop_to_copywriter():
    route, _ = _supervisor_decision("物流延迟的 SOP 怎么处理")
    assert route == "copywriter"


def test_analyst_query_strips_copy_instruction():
    assert _analyst_query("帮我给上海的黑卡流失用户写一段美妆产品的召回短信") == (
        "上海的黑卡流失用户有哪些"
    )


def test_sop_topic_includes_beauty_coupon():
    topic = _sop_topic("给美妆用户写召回短信")
    assert "高价值用户召回方案" in topic
    assert "100元美妆券" in topic


def test_agent_graph_has_supervisor_branches():
    graph = build_agent_graph().get_graph()
    nodes = set(graph.nodes)
    assert {"supervisor", "analyst", "copywriter", "finalize"} <= nodes
    assert any(edge.source == "supervisor" and edge.target == "analyst" for edge in graph.edges)
    assert any(edge.source == "supervisor" and edge.target == "copywriter" for edge in graph.edges)
