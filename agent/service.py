"""LangGraph 多智能体编排：Supervisor + Analyst + Copywriter。

拓扑：
    START → supervisor ──┬── analyst → copywriter → finalize → END
                         └── copywriter → finalize → END

- supervisor：判断请求是否需要先查画像，再决定分派给谁。
- analyst：调用 `query_user_profiles`（复用 /api/wizard/query）。
- copywriter：调用 `get_operation_sop`（复用底层 RAG），结合画像让 LLM 写短信。
- finalize：主管汇总最终结果。

本模块只编排，不复制检索 / SQL / 权限逻辑。
"""
from __future__ import annotations

import json
import logging
import operator
import os
import re
import threading
from contextlib import contextmanager
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.semantic_gate import build_fallback, should_gate
from agent.tools import get_operation_sop, query_user_profiles

logger = logging.getLogger(__name__)

# 本地同一进程内串行执行，避免 QIANKE_* 环境变量在并发请求间互相覆盖。
_RUN_LOCK = threading.Lock()


class AgentState(TypedDict, total=False):
    user_query: str
    profiles_data: dict[str, Any]
    sop_data: dict[str, Any]
    final_reply: str
    next_agent: str
    gated: bool
    trace: Annotated[list[dict[str, Any]], operator.add]


_SYSTEM_PROMPT = """你是一个严谨的电商文案专家。

你需要根据【用户画像】和【运营 SOP】生成一段发给用户的召回短信。
必须严格基于传入的用户画像生成文案。如果画像数据显示“没有匹配用户”，
直接输出“无法生成”并说明原因，绝对不能从候选列表中自行拼凑或假设用户身份。

短信必须包含：
1. 尊贵称谓（如：黑卡VIP）；
2. 真实的补偿权益（严格从 SOP 提取，如：100元美妆券）；
3. 符合用户偏好的话术（如：提到她喜欢的美妆类目新品）。

语气要真诚、亲切，字数控制在 100 字以内。
只输出短信正文，不要标题、解释、Markdown 或引号。
"""

_PROFILE_HINTS = (
    "用户", "画像", "名单", "哪些", "谁", "上海", "北京", "黑卡", "会员",
    "流失", "客单价", "消费", "下单", "高价值", "女生", "女性",
)
_SOP_HINTS = (
    "SOP", "sop", "规则", "流程", "话术", "短信", "召回", "优惠券",
    "物流", "退换", "权益",
)


def _supervisor_decision(query: str) -> tuple[str, str]:
    """轻量规则主管：先判断是否必须查画像。

    本轮是业务演示，主管的路由规则保持可解释、可测试，不额外消耗 LLM 调用。
    需要“先看用户数据”的请求一律先走 analyst；纯规则问题直接 copywriter。
    """
    text = (query or "").strip()
    if any(word in text for word in _PROFILE_HINTS):
        return "analyst", "检测到用户/画像筛选意图，先派数据分析师查名单"
    if any(word in text for word in _SOP_HINTS):
        return "copywriter", "检测到规则/话术意图，直接派文案专家检索 SOP"
    return "analyst", "默认先查画像，避免文案脱离真实用户数据"


def _analyst_query(user_query: str) -> str:
    """把“帮我给上海黑卡流失用户写短信”收敛成画像查询。"""
    text = (user_query or "").strip()
    text = re.sub(r"^帮我(给|为|针对)?", "", text).strip()
    text = re.sub(r"(写|生成|推荐|做).*(短信|文案|话术).*$", "", text).strip()
    text = text.strip("，。,.；; ")
    if not text:
        return user_query.strip()
    if not re.search(r"(有哪些|是谁|名单|什么|多少|哪些人)$", text):
        text += "有哪些"
    return text


def _sop_topic(user_query: str) -> str:
    topic = "高价值用户召回方案"
    if "美妆" in user_query:
        topic += " 美妆专属券 100元美妆券 新品优先体验"
    return topic


def supervisor_node(state: AgentState) -> dict[str, Any]:
    query = state.get("user_query", "")
    next_agent, reason = _supervisor_decision(query)
    return {
        "next_agent": next_agent,
        "trace": [{
            "agent": "supervisor",
            "label": "主管",
            "status": "done",
            "message": f"🧭 主管判断：{reason}",
        }],
    }


def route_supervisor(state: AgentState) -> str:
    return state.get("next_agent") or "analyst"


def analyst_node(state: AgentState) -> dict[str, Any]:
    query = _analyst_query(state.get("user_query", ""))
    result = query_user_profiles.invoke({"query": query})
    ok = bool(result.get("ok"))
    count = len(result.get("user_cards") or [])
    message = (
        f"🔍 数据分析师已查询「{query}」，返回 {count} 张用户卡片"
        if ok
        else f"🔍 画像查询失败：{result.get('error') or '未知错误'}"
    )
    return {
        "profiles_data": result,
        "trace": [{
            "agent": "analyst",
            "label": "数据分析师",
            "status": "done" if ok else "error",
            "message": message,
        }],
    }


def _build_copy_prompt(state: AgentState) -> str:
    profiles = state.get("profiles_data") or {}
    sop = state.get("sop_data") or {}
    profile_answer = (profiles.get("answer") or "").strip()
    cards = profiles.get("user_cards") or []
    sop_text = "\n".join(
        f"[{src.get('source')}] {src.get('text') or ''}"
        for src in (sop.get("sources") or [])
    )
    return f"""用户需求：{state.get('user_query', '')}

【用户画像】
{profile_answer or '画像工具没有返回用户数据，不得虚构用户。'}

【用户卡片】
{json.dumps(cards[:5], ensure_ascii=False, default=str)}

【运营 SOP】
{sop_text or 'SOP 工具没有返回规则，不得虚构权益。'}

请根据以上事实写一段召回短信。"""


def copywriter_node(state: AgentState) -> dict[str, Any]:
    # 确定性前置守门：必须在任何 SOP 检索 / LLM 调用之前执行。
    # user_cards 只是检索候选，不是精确命中；answer 明确说没有匹配时，
    # 即使候选卡非空，也绝不能把某个候选硬包装成目标用户。
    if "profiles_data" in state and should_gate(
        state.get("profiles_data"), state.get("user_query", "")
    ):
        reply = build_fallback(
            state.get("user_query", ""),
            (state.get("profiles_data") or {}).get("user_cards") or [],
        )
        return {
            "gated": True,
            "sop_data": {},
            "final_reply": reply,
            "trace": [{
                "agent": "copywriter",
                "label": "文案专家",
                "status": "done",
                "message": "🛡️ 画像没有精确匹配，已停止生成短信并请求确认筛选口径",
            }],
        }

    topic = _sop_topic(state.get("user_query", ""))
    sop = get_operation_sop.invoke({"topic": topic})

    trace = [{
        "agent": "copywriter",
        "label": "文案专家",
        "status": "done" if sop.get("ok") else "error",
        "message": f"📖 文案专家已调取运营规则（{sop.get('count', 0)} 条 SOP 片段）",
    }]

    try:
        from rag_demo.generation.generator import chat_completion

        response = chat_completion(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_copy_prompt({**state, "sop_data": sop})},
            ],
            temperature=0.3,
            feature="agent_copywriter",
        )
        final_reply = (response.choices[0].message.content or "").strip()
        if not final_reply:
            raise ValueError("LLM 返回空文案")
        trace.append({
            "agent": "copywriter",
            "label": "文案专家",
            "status": "done",
            "message": "✍️ 已根据画像与 SOP 生成专属召回短信",
        })
    except Exception as exc:  # noqa: BLE001 - 失败给可读兜底，不让整张图无声崩掉
        logger.exception("copywriter 生成失败")
        final_reply = (
            "尊敬的会员您好，感谢您一直以来的支持。"
            "我们为您准备了一份专属美妆心意，期待您回来体验。"
        )
        trace.append({
            "agent": "copywriter",
            "label": "文案专家",
            "status": "error",
            "message": f"✍️ 文案生成失败，已返回兜底话术：{type(exc).__name__}",
        })

    return {"sop_data": sop, "final_reply": final_reply, "trace": trace}


def route_after_copywriter(state: AgentState) -> str:
    """语义守门命中时直接结束，不进入主管汇总，也不再生成文案。"""
    return "end" if state.get("gated") else "finalize"


def finalize_node(state: AgentState) -> dict[str, Any]:
    return {
        "final_reply": state.get("final_reply", ""),
        "trace": [{
            "agent": "finalizer",
            "label": "主管汇总",
            "status": "done",
            "message": "✅ 主管已汇总画像、SOP 与专属话术",
        }],
    }


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("copywriter", copywriter_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {"analyst": "analyst", "copywriter": "copywriter"},
    )
    graph.add_edge("analyst", "copywriter")
    graph.add_conditional_edges(
        "copywriter",
        route_after_copywriter,
        {"finalize": "finalize", "end": END},
    )
    graph.add_edge("finalize", END)
    return graph.compile()


AGENT_GRAPH = build_agent_graph()


@contextmanager
def _tool_environment(dataset: str, api_base: str, auth_cookie: str | None):
    keys = ("QIANKE_AGENT_DATASET", "QIANKE_API_BASE", "QIANKE_AUTH_COOKIE")
    old = {key: os.environ.get(key) for key in keys}
    os.environ["QIANKE_AGENT_DATASET"] = dataset
    os.environ["QIANKE_API_BASE"] = api_base.rstrip("/")
    if auth_cookie:
        os.environ["QIANKE_AUTH_COOKIE"] = auth_cookie
    else:
        os.environ.pop("QIANKE_AUTH_COOKIE", None)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_agent(
    query: str,
    *,
    dataset: str,
    api_base: str,
    auth_cookie: str | None = None,
) -> dict[str, Any]:
    """执行一次多智能体运行，返回前端需要的结构化结果。"""
    with _RUN_LOCK, _tool_environment(dataset, api_base, auth_cookie):
        state = AGENT_GRAPH.invoke({"user_query": query, "trace": []})

    profiles = state.get("profiles_data") or {}
    sop = state.get("sop_data") or {}
    return {
        "user_query": query,
        "profiles": profiles,
        "sop": sop,
        "user_cards": profiles.get("user_cards") or [],
        "final_reply": state.get("final_reply") or "",
        "steps": state.get("trace") or [],
    }


__all__ = ["AgentState", "build_agent_graph", "run_agent"]
