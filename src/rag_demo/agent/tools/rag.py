"""RAG 检索薄壳：JSON 输入/输出，不生成最终答案。"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from rag_demo.agent.tool import ToolResult

logger = logging.getLogger(__name__)


class RagSearchInput(BaseModel):
    """rag_search 的 JSON Schema。"""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=1, description="检索问题")
    top_k: int = Field(5, ge=1, le=20, description="返回结果数量，1~20")


def retrieve(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """领域逻辑：复用千客引擎的混合检索，只返回资料与来源。

    混合检索失败时降级到关键词召回；降级仍然失败才把结构化错误交给 LLM。
    """
    from rag_demo.retrieval.hybrid_retriever import hybrid_search, keyword_search

    try:
        hits = hybrid_search(query, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 - 记录原因后尝试关键词降级
        logger.warning("混合检索失败，降级到关键词召回: %s: %s", type(exc).__name__, exc)
        hits = keyword_search(query, top_k=top_k)
    results: list[dict[str, Any]] = []
    for item in hits or []:
        meta = item.get("metadata") or {}
        results.append({
            "content": item.get("text") or item.get("content") or item.get("parent_text") or "",
            "score": item.get("score", item.get("rrf_score", 0.0)),
            "source": item.get("source") or meta.get("source") or item.get("id", ""),
        })
    return results


def _rag_adapter(query: str, top_k: int = 5) -> dict[str, Any]:
    try:
        results = retrieve(query, top_k)
        return ToolResult.success(query=query, results=results).dump()
    except Exception as exc:  # noqa: BLE001 - 工具失败交给 LLM 决策
        return ToolResult.failure(
            "RAG_SEARCH_ERROR",
            f"{type(exc).__name__}: {exc}",
            {"query": query, "results": []},
        ).dump()


@tool(args_schema=RagSearchInput)
def rag_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """检索千客引擎的用户画像 / 运营知识库。

    返回 results（content/score/source）与来源，不生成最终答案。
    """
    return _rag_adapter(query, top_k)
