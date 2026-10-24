"""LangChain Tool 封装：复用千客引擎现有问答 / RAG 检索能力。

设计约束：
- 不复制业务逻辑。用户画像查询走现有 `POST /api/wizard/query`；
  运营 SOP 走现有混合检索 `hybrid_search`。
- 工具返回结构化 dict（ok/error），让 Agent 能判断“没查到”而不是编造。
- API 地址与数据集通过环境变量覆盖，便于本地 smoke / 后续部署：
    QIANKE_API_BASE        默认 http://127.0.0.1:8000
    QIANKE_AGENT_DATASET   默认 user（向导只接受 user / test / 企业库）
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from langchain_core.tools import tool

DEFAULT_API_BASE = "http://127.0.0.1:8000"
# /api/wizard/query 只服务 user / test / 企业库，不能查 demo（demo 的问答在 /qa）。
# 生产默认使用当前登录账号推导出的 user 数据集；本地冒烟可通过环境变量覆盖为 test。
DEFAULT_DATASET = "user"
DEFAULT_TIMEOUT = 60.0


def _api_base() -> str:
    return (os.environ.get("QIANKE_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def _dataset() -> str:
    return (os.environ.get("QIANKE_AGENT_DATASET") or DEFAULT_DATASET).strip()


def _auth_cookies() -> dict[str, str] | None:
    """可选会话 Cookie：Agent 作为已登录用户调用受保护接口时使用。

    QIANKE_AUTH_COOKIE 支持两种写法：
        rag_session=<token>
        <token>
    未设置时按匿名请求处理；服务端是否放行由现有权限中间件决定。
    """
    raw = (os.environ.get("QIANKE_AUTH_COOKIE") or "").strip()
    if not raw:
        return None
    if "=" in raw:
        name, value = raw.split("=", 1)
        return {name.strip(): value.strip()}
    return {"rag_session": raw}


def _post_wizard_query(question: str, dataset: str) -> dict[str, Any]:
    """调用现有 FastAPI 路由；单独抽出便于单测 monkeypatch。"""
    url = f"{_api_base()}/api/wizard/query"
    with httpx.Client(timeout=DEFAULT_TIMEOUT, cookies=_auth_cookies()) as client:
        response = client.post(
            url,
            json={"question": question, "dataset": dataset},
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"/api/wizard/query 返回了非对象响应: {type(data).__name__}")
    return data


def _search_sop(topic: str, dataset: str) -> list[dict[str, Any]]:
    """调用现有混合检索；单独抽出便于单测 monkeypatch。"""
    from rag_demo.db.connection import reset_dataset, use_dataset
    from rag_demo.retrieval.hybrid_retriever import hybrid_search

    token = use_dataset(dataset)
    try:
        hits = hybrid_search(topic, top_k=12)
    finally:
        reset_dataset(token)

    # 只保留规则文档，不把用户画像当成 SOP；source 以 .md 结尾是现有检索层的口径。
    docs = [
        hit for hit in hits
        if str(hit.get("source") or "").lower().endswith(".md")
    ]
    return docs


@tool
def query_user_profiles(query: str) -> dict[str, Any]:
    """查询用户画像与业务数据。

    当用户询问“哪些用户 / 用户特征 / 名单 / 筛选条件”时调用。
    例如：“上海的黑卡流失用户有哪些”“高客单女性用户的特征”。

    Args:
        query: 自然语言查询，例如“上海的黑卡流失用户”。

    Returns:
        包含 answer、sources、route、dataset 的结构化结果；
        查询失败时返回 {"ok": false, "error": "..."}，不得绕过失败编造数据。
    """
    question = (query or "").strip()
    if not question:
        return {"ok": False, "error": "query 不能为空"}

    dataset = _dataset()
    try:
        data = _post_wizard_query(question, dataset)
    except Exception as exc:  # noqa: BLE001 - 工具失败要变成 observation，不打死 Agent
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "query": question,
            "dataset": dataset,
        }

    return {
        "ok": True,
        "query": question,
        "dataset": data.get("dataset", dataset),
        "route": data.get("route"),
        "answer": data.get("answer", ""),
        "sources": data.get("sources", []) or [],
        "user_cards": data.get("user_cards", []) or [],
        "busy": bool(data.get("busy")),
        "elapsed_ms": data.get("elapsed_ms"),
    }


@tool
def get_operation_sop(topic: str) -> dict[str, Any]:
    """检索运营 SOP、规则和标准动作。

    当需要回答“怎么做 / 召回方案 / 物流延迟处理 / 退换货流程 / 会员权益”等
    业务规则时调用。只返回知识库中的规则片段，不生成营销文案。

    Args:
        topic: 规则主题，例如“高价值用户召回方案”“物流延迟处理”。

    Returns:
        包含 sources（文档名 + 原文片段 + 检索分数）的结构化结果；
        检索失败时返回 {"ok": false, "error": "..."}。
    """
    query = (topic or "").strip()
    if not query:
        return {"ok": False, "error": "topic 不能为空"}

    dataset = _dataset()
    try:
        docs = _search_sop(query, dataset)
    except Exception as exc:  # noqa: BLE001 - 检索失败不打死 Agent
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "topic": query,
            "dataset": dataset,
        }

    # 二次过滤：即使底层检索未来把画像/其他来源混进结果，本工具也只暴露规则文档。
    docs = [
        hit for hit in docs
        if str(hit.get("source") or "").lower().endswith(".md")
    ]

    sources = [
        {
            "rank": i,
            "source": hit.get("source"),
            "text": (hit.get("text") or "")[:500],
            "rerank_score": hit.get("rerank_score"),
        }
        for i, hit in enumerate(docs[:5], 1)
    ]
    return {
        "ok": True,
        "topic": query,
        "dataset": dataset,
        "count": len(sources),
        "sources": sources,
    }


__all__ = ["query_user_profiles", "get_operation_sop"]
