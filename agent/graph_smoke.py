"""LangGraph 最小冒烟图：验证框架能跑通，并串起两个现有能力。

注意：本文件刻意**不实现** Supervisor / 多智能体路由。
那是下一步（第三步）的工作；这里只验证：
    LangGraph StateGraph → Tool 调用 → 状态回传

运行（需先启动千客引擎 API）：
    python -m agent.graph_smoke
"""
from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.semantic_gate import build_fallback, should_gate
from agent.tools import get_operation_sop, query_user_profiles


class SmokeState(TypedDict, total=False):
    user_request: str
    analyst_query: str
    sop_topic: str
    profiles: dict[str, Any]
    sop: dict[str, Any]
    final_reply: str


def analyst_node(state: SmokeState) -> dict[str, Any]:
    """调用现有用户画像接口。"""
    query = state.get("analyst_query") or state.get("user_request", "")
    return {"profiles": query_user_profiles.invoke({"query": query})}


def copywriter_node(state: SmokeState) -> dict[str, Any]:
    """调用现有 RAG 检索，拿到运营规则片段。

    与正式图一样先做语义守门：画像明确没有匹配时，不再检索/生成，
    直接返回固定兜底话术，避免把候选用户硬包装成目标用户。
    """
    profiles = state.get("profiles") or {}
    if should_gate(profiles, state.get("user_request", "")):
        return {
            "sop": {},
            "final_reply": build_fallback(
                state.get("user_request", ""),
                profiles.get("user_cards") or [],
            ),
        }
    topic = state.get("sop_topic") or "高价值用户召回方案"
    return {"sop": get_operation_sop.invoke({"topic": topic}), "final_reply": ""}


def build_smoke_graph():
    graph = StateGraph(SmokeState)
    graph.add_node("analyst", analyst_node)
    graph.add_node("copywriter", copywriter_node)
    graph.add_edge(START, "analyst")
    graph.add_edge("analyst", "copywriter")
    graph.add_edge("copywriter", END)
    return graph.compile()


def run_smoke(
    user_request: str = "帮我给上海的黑卡流失用户写一段召回短信",
    analyst_query: str = "上海的黑卡流失用户有哪些",
    sop_topic: str = "高价值用户召回方案",
) -> dict[str, Any]:
    graph = build_smoke_graph()
    return graph.invoke(
        {
            "user_request": user_request,
            "analyst_query": analyst_query,
            "sop_topic": sop_topic,
        }
    )


def main() -> None:
    state = run_smoke()

    profiles = state.get("profiles") or {}
    sop = state.get("sop") or {}

    summary = {
        "user_request": state.get("user_request"),
        "final_reply": state.get("final_reply"),
        "profile_tool": {
            "ok": profiles.get("ok"),
            "dataset": profiles.get("dataset"),
            "route": profiles.get("route"),
            "answer_preview": (profiles.get("answer") or "")[:300],
            "source_count": len(profiles.get("sources") or []),
            "error": profiles.get("error"),
        },
        "sop_tool": {
            "ok": sop.get("ok"),
            "dataset": sop.get("dataset"),
            "count": sop.get("count"),
            "sources": [
                {"source": s.get("source"), "text_preview": (s.get("text") or "")[:160]}
                for s in (sop.get("sources") or [])
            ],
            "error": sop.get("error"),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
