"""Super-agent 自动 Trigger 适配器。

- CApp/IM 消息钩子：只把业务信号交给 Router，闲聊不产生工作项；
- 通用 Webhook：供企业微信/飞书中转或外部系统使用；
- 自动运行可配置，默认关闭，避免误触发真实模型成本。
"""
from __future__ import annotations

import hmac
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rag_demo.superagent import router as sa_router
from rag_demo.superagent import runtime as sa_runtime

logger = logging.getLogger(__name__)
WEBHOOK_SECRET_ENV = "QIANKE_SUPERAGENT_WEBHOOK_SECRET"
_CAPP_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sa-capp")


def _enabled() -> bool:
    return (os.environ.get("QIANKE_SUPERAGENT_AUTO_TRIGGER") or "0").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _auto_run() -> bool:
    return (os.environ.get("QIANKE_SUPERAGENT_AUTO_RUN") or "1").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _start_worker(work_item_id: str) -> None:
    try:
        sa_runtime.start_worker(work_item_id)
    except Exception:  # noqa: BLE001 - 自动触发不能影响聊天主链路
        logger.exception("Super-agent 自动运行提交失败 work_item=%s", work_item_id)


def ingest_async(
    *,
    source: str,
    content: str,
    channel: str,
    thread_key: str | None = None,
    merchant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _enabled():
        return {"accepted": False, "reason": "AUTO_TRIGGER_DISABLED", "work_item": None}
    try:
        result = sa_router.ingest_event(
            source=source,
            content=content,
            channel=channel,
            thread_key=thread_key,
            merchant_id=merchant_id or sa_router.store.DEFAULT_MERCHANT_ID,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Super-agent 自动 Trigger 失败 source=%s", source)
        return {"accepted": False, "reason": "INGEST_ERROR", "work_item": None}
    item = result.get("work_item")
    if result.get("accepted") and _auto_run() and item and item.get("status") == "PENDING":
        _start_worker(item["work_item_id"])
        result["auto_run_started"] = True
    return result


def maybe_trigger_capp(
    *,
    buyer_id: str,
    content: str,
    channel: str,
    thread_key: str,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    """CApp 好友/群聊消息钩子；异步入队，避免 Router LLM 拖慢聊天响应。"""
    if not _enabled():
        return {"accepted": False, "reason": "AUTO_TRIGGER_DISABLED", "work_item": None}
    _CAPP_EXECUTOR.submit(
        ingest_async,
        source="capp",
        content=content,
        channel=channel,
        thread_key=thread_key,
        merchant_id=merchant_id,
        metadata={"buyer_id": buyer_id},
    )
    return {"scheduled": True, "reason": "QUEUED"}


def verify_webhook_secret(provided: str | None) -> bool:
    expected = (os.environ.get(WEBHOOK_SECRET_ENV) or "").strip()
    if not expected:
        return False
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)
