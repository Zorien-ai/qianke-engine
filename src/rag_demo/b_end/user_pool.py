"""B 端「千客用户池」：与本商户产生过会话或交易的 C 客户。

口径（2026-11-14 与需求方确认）：
- 只要在这家商户产生过**对话或交易**的客户，都算这家商户的千客用户；
- 会话与订单按 buyer_id 并集去重，不是两个列表简单相加；
- 订单 merchant_id 为空时，用订单明细里的商品所属商户兜底归属；
- 归属不到任何商户的订单（例如 m_demo 商品）不进入商户池。

本模块只做确定性聚合与文本拼装，不调用 LLM；embedding 由调用方注入，
失败时保留正文，搜索退回文本匹配（与 b_chat_user_profile 同一套降级策略）。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from rag_demo.c_end import store

Embedder = Callable[[str], list[float] | None]

POOL_MAX_BUYERS = 500
PROFILE_TEXT_MAX = 1000
MESSAGE_SNIPPETS = 3

# 消息原文可能带手机号/邮箱/证件号；只做确定性脱敏，不把原文交给模型。
_PII_RE = re.compile(
    r"\b1[3-9]\d{9}\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\b\d{17}[\dXx]\b|\b\d{16,19}\b"
)


def _redact(text: str) -> str:
    return _PII_RE.sub("[已脱敏]", str(text or ""))


def _default_embed(text: str) -> list[float] | None:
    try:
        from rag_demo.c_end.chat_profile import embed_text

        return embed_text(text)
    except Exception:  # noqa: BLE001 - 没有模型/远程不可用仍可保存正文
        return None


def collect_merchant_buyers(merchant_id: str) -> list[dict[str, Any]]:
    """把订单与会话合并成按 buyer_id 去重的池记录（不含 embedding）。"""
    records: dict[str, dict[str, Any]] = {}

    # 1) 订单：排除已取消；同一买家聚合成订单数/金额/客单价/最近一次/偏好品类。
    for row in store.list_merchant_order_rows(merchant_id):
        buyer_id = str(row.get("buyer_id") or "").strip()
        if not buyer_id:
            continue
        record = records.setdefault(buyer_id, _empty_buyer(buyer_id))
        record["has_order"] = True
        status = str(row.get("status") or "").upper()
        if status == "CANCELLED":
            continue
        try:
            amount = float(row.get("total_amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        record["order_count"] += 1
        record["order_amount"] += amount
        created_at = str(row.get("created_at") or "")
        if created_at and created_at > str(record["last_order_at"] or ""):
            record["last_order_at"] = created_at
        category = str(row.get("category") or "").strip()
        if category:
            record["_categories"][category] += 1

    # 2) 会话画像：已经抽取过结构化画像的买家。
    for profile in store.list_chat_user_profiles(merchant_id, limit=POOL_MAX_BUYERS):
        if str(profile.get("status") or "ACTIVE").upper() != "ACTIVE":
            continue
        buyer_id = str(profile.get("buyer_id") or "").strip()
        if not buyer_id:
            continue
        record = records.setdefault(buyer_id, _empty_buyer(buyer_id))
        record["has_chat"] = True
        record["chat_profile"] = profile.get("profile") or {}
        record["chat_profile_text"] = str(profile.get("profile_text") or "")
        record["confidence"] = float(profile.get("confidence") or 0)
        record["source_message_count"] = int(profile.get("source_message_count") or 0)
        record["chat_extracted_at"] = profile.get("extracted_at")

    # 3) 只聊过天、还没抽取出画像的买家：也算「有会话」，不能漏。
    for buyer_id in store.list_merchant_chat_buyers(merchant_id):
        record = records.setdefault(buyer_id, _empty_buyer(buyer_id))
        record["has_chat"] = True

    # 4) 最近消息作为确定性证据：补上「还没结构化画像」时的会话内容。
    for message in store.list_merchant_recent_messages(merchant_id, limit=200):
        buyer_id = str(message.get("buyer_id") or "").strip()
        if not buyer_id:
            continue
        record = records.setdefault(buyer_id, _empty_buyer(buyer_id))
        record["has_chat"] = True
        snippets = record["_messages"]
        if len(snippets) < MESSAGE_SNIPPETS:
            content = _redact(str(message.get("content") or "").strip())
            if content:
                snippets.append(content[:120])

    result = []
    for record in records.values():
        categories = record.pop("_categories", Counter())
        if categories:
            record["top_category"] = sorted(
                categories.items(), key=lambda item: (-item[1], item[0])
            )[0][0]
        if record["order_count"]:
            record["avg_order_amount"] = round(record["order_amount"] / record["order_count"], 2)
        record["order_amount"] = round(float(record["order_amount"]), 2)
        record["profile_text"] = build_profile_text(record)
        record.pop("_messages", None)
        record["profile_json"] = {
            "order": {
                "order_count": record["order_count"],
                "order_amount": record["order_amount"],
                "avg_order_amount": record["avg_order_amount"],
                "last_order_at": record["last_order_at"],
                "top_category": record["top_category"],
            },
            "chat": record["chat_profile"],
        }
        result.append(record)
    return result


def _empty_buyer(buyer_id: str) -> dict[str, Any]:
    return {
        "buyer_id": buyer_id,
        "order_count": 0,
        "order_amount": 0.0,
        "avg_order_amount": 0.0,
        "last_order_at": None,
        "top_category": None,
        "has_order": False,
        "has_chat": False,
        "chat_profile": {},
        "chat_profile_text": "",
        "confidence": 0.0,
        "source_message_count": 0,
        "chat_extracted_at": None,
        "_categories": Counter(),
        "_messages": [],
    }


def build_profile_text(record: dict[str, Any]) -> str:
    """把订单事实与会话事实拼成可检索的中文文本；不写姓名/手机号/地址。"""
    buyer_id = str(record.get("buyer_id") or "").strip()
    parts: list[str] = [f"千客用户 {buyer_id}"]
    if record.get("has_order"):
        order_count = int(record.get("order_count") or 0)
        if order_count:
            parts.append(
                f"在本商户有 {order_count} 笔有效订单，累计消费 ¥{float(record.get('order_amount') or 0):.2f}，"
                f"客单价 ¥{float(record.get('avg_order_amount') or 0):.2f}"
            )
            if record.get("last_order_at"):
                parts.append(f"最近一次下单 {record['last_order_at']}")
            if record.get("top_category"):
                parts.append(f"偏好品类 {record['top_category']}")
        else:
            parts.append("在本商户下过单（订单已取消，不计入消费统计）")
    if record.get("has_chat"):
        chat_text = str(record.get("chat_profile_text") or "").strip()
        if chat_text:
            parts.append(f"会话画像：{chat_text}")
        else:
            messages = [str(item) for item in record.get("_messages") or [] if str(item).strip()]
            if messages:
                parts.append("最近会话：" + "；".join(messages))
            else:
                parts.append("在店宠会话中有过沟通（尚未生成结构化会话画像）")
    if len(parts) == 1:
        parts.append("暂无可用的订单或会话事实")
    return "；".join(parts)[:PROFILE_TEXT_MAX]


def refresh_merchant_pool(
    merchant_id: str,
    *,
    embedder: Embedder | None = None,
    limit: int = POOL_MAX_BUYERS,
) -> dict[str, Any]:
    """重建/更新一个商户的千客用户池；返回刷新统计。"""
    records = collect_merchant_buyers(merchant_id)
    checked = len(records)
    records = records[: max(1, int(limit))]
    embed = embedder or _default_embed
    upserted = 0
    embedding_failed = 0
    for record in records:
        text = record["profile_text"]
        embedding = None
        try:
            embedding = embed(text)
        except Exception:  # noqa: BLE001
            embedding = None
        if embedding is None:
            embedding_failed += 1
        store.upsert_qianke_user_profile(
            merchant_id,
            record["buyer_id"],
            profile=record["profile_json"],
            profile_text=text,
            order_count=record["order_count"],
            order_amount=record["order_amount"],
            avg_order_amount=record["avg_order_amount"],
            last_order_at=record["last_order_at"],
            top_category=record["top_category"],
            has_order=record["has_order"],
            has_chat=record["has_chat"],
            chat_profile=record["chat_profile"],
            confidence=record["confidence"],
            source_message_count=record["source_message_count"],
            chat_extracted_at=record["chat_extracted_at"],
            embedding=embedding,
        )
        upserted += 1
    return {
        "merchant_id": merchant_id,
        "checked": checked,
        "upserted": upserted,
        "embedding_failed": embedding_failed,
        "truncated": checked > len(records),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def pool_summary(merchant_id: str) -> dict[str, Any]:
    """池的确定性摘要：多少人、多少人有订单/会话、最近更新时间。"""
    profiles = store.list_qianke_user_profiles(merchant_id, limit=POOL_MAX_BUYERS)
    with_order = sum(1 for item in profiles if item.get("has_order"))
    with_chat = sum(1 for item in profiles if item.get("has_chat"))
    updated_at = max((str(item.get("updated_at") or "") for item in profiles), default="")
    return {
        "count": store.count_qianke_user_profiles(merchant_id),
        "with_orders": with_order,
        "with_chat": with_chat,
        "updated_at": updated_at or None,
        "ready": True,
    }


__all__ = [
    "POOL_MAX_BUYERS",
    "build_profile_text",
    "collect_merchant_buyers",
    "pool_summary",
    "refresh_merchant_pool",
]
