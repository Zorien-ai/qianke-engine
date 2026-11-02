"""Super-agent Router：Fast Path 事件过滤 + Thread/WorkItem 归并。

MVP 用确定性规则做第一层过滤；LLM 只在下游 Worker 使用，避免每条闲聊都调模型。
"""
from __future__ import annotations

import re
from typing import Any

from rag_demo.superagent import store

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
)


def should_accept(text: str, metadata: dict[str, Any] | None = None) -> tuple[bool, str]:
    """程序层 Fast Path：只把明确的业务请求送进 Super-agent。"""
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
