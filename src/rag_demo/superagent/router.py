"""Super-agent Router：两级过滤 + Thread/WorkItem 归并。

Fast Path：确定性业务关键词/订单号；
Slow Path：可选 LLM 语义分类（QIANKE_SUPERAGENT_LLM_ROUTER=1）；
Batch：批量事件入口，同一 Thread 只维护一个活跃工作项。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from rag_demo.superagent import store

logger = logging.getLogger(__name__)

_ORDER_RE = re.compile(r"\b(order_[a-zA-Z0-9]+|ORD-\d{8}-\d{4})\b")
_KEYWORDS = (
    "订单",
    "售后",
    "退款",
    "退货",
    "物流",
    "发货",
    "快递",
    "库存",
    "商品",
    "优惠",
    "异常",
    "投诉",
    "尺码",
    "换货",
    "补发",
    "包裹",
    "没收到",
    "未收到",
    "没发货",
    "卖家",
    "客服",
    "下单",
    "付款",
    "签收",
    "收货",
)
_SEMANTIC_PROMPT = """你是千客商家客服的 Router。判断用户消息是否属于需要商家售后/订单调查的业务请求。

只输出 JSON：{"accept": true/false, "reason": "简短原因"}
需要受理：订单状态、物流、发货、退款、退货、售后、补发、换货、库存、商品质量问题、优惠纠纷；
也包括买家围绕已购买商品/包裹的投诉，例如未收到货、物流停滞、卖家不回复、商品坏了、少件/错发。
不受理：问候、闲聊、纯情绪、与商家订单/商品/售后无关的问题。

用户消息：
{message}
"""


def _semantic_enabled() -> bool:
    return (os.environ.get("QIANKE_SUPERAGENT_LLM_ROUTER") or "0").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }


def semantic_classify(text: str) -> tuple[bool, str]:
    """Slow Path：LLM 判断模糊消息；失败按不受理处理，避免误触发。"""
    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return False, "SEMANTIC_NO_KEY"
    llm = ChatOpenAI(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL") or None,
        temperature=0,
        timeout=20,
        max_retries=0,
    )
    try:
        raw = llm.invoke(_SEMANTIC_PROMPT.replace("{message}", text[:1000])).content
        data = json.loads(str(raw).strip().strip("`"))
        if bool(data.get("accept")):
            return True, f"SEMANTIC:{str(data.get('reason') or 'accepted')[:80]}"
    except Exception:  # noqa: BLE001 - Router 失败不阻塞
        logger.warning("Super-agent 语义分类失败", exc_info=True)
    return False, "SEMANTIC_REJECT"


def should_accept(text: str, metadata: dict[str, Any] | None = None) -> tuple[bool, str]:
    """程序策略优先；无信号时才启用可选语义层。"""
    content = (text or "").strip()
    if len(content) < 4:
        return False, "TOO_SHORT"
    if _ORDER_RE.search(content):
        return True, "ORDER_REF"
    for keyword in _KEYWORDS:
        if keyword in content:
            return True, f"KEYWORD:{keyword}"
    if metadata and metadata.get("force"):
        return True, "FORCED"
    if _semantic_enabled():
        return semantic_classify(content)
    return False, "NO_BUSINESS_SIGNAL"


def ingest_event(
    *,
    source: str,
    content: str,
    channel: str = "manual",
    thread_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise store.store.CStoreError("SA_EMPTY_EVENT", "事件内容不能为空")
    accepted, reason = should_accept(text, metadata)
    if not accepted:
        return {
            "accepted": False,
            "reason": reason,
            "trigger": None,
            "thread": None,
            "work_item": None,
        }
    result = store.create_trigger(
        source=source or "manual",
        content=text,
        channel=channel or "manual",
        thread_key=thread_key,
        metadata={**(metadata or {}), "filter_reason": reason},
    )
    result["accepted"] = True
    result["reason"] = reason
    return result


def ingest_batch(events: list[dict[str, Any]]) -> dict[str, Any]:
    """批量 Trigger：同一 Thread 的多条事件合并到一个 WorkItem。"""
    accepted = 0
    results: list[dict[str, Any]] = []
    for event in events[:50]:
        result = ingest_event(
            source=str(event.get("source") or "batch"),
            content=str(event.get("content") or ""),
            channel=str(event.get("channel") or "batch"),
            thread_key=event.get("thread_key"),
            metadata=event.get("metadata") if isinstance(event.get("metadata"), dict) else None,
        )
        results.append(result)
        if result.get("accepted"):
            accepted += 1
    return {"total": len(results), "accepted": accepted, "results": results}
