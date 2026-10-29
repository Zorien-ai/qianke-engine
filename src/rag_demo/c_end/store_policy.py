"""店宠/平台活动的确定性规则数据（MVP mock）。"""
from __future__ import annotations

from typing import Any

POLICIES: tuple[dict[str, str], ...] = (
    {
        "policy_id": "sop_shipping",
        "kind": "merchant_sop",
        "title": "发货时效",
        "content": "现货商品 48 小时内发出；偏远地区可能延迟 1-2 天。",
    },
    {
        "policy_id": "sop_return",
        "kind": "merchant_sop",
        "title": "售后与退货",
        "content": "支持 7 天无理由退货，商品需保持不影响二次销售；质量问题商家承担运费。",
    },
    {
        "policy_id": "sop_no_change_price",
        "kind": "merchant_sop",
        "title": "店宠改价权限",
        "content": "店宠无权直接改价、发券或承诺赔付；优惠以平台活动或商家确认结果为准。",
    },
    {
        "policy_id": "platform_full_reduce",
        "kind": "platform_activity",
        "title": "满减活动",
        "content": "平台活动：满 299 减 30，满 599 减 80；具体以结算页为准。",
    },
    {
        "policy_id": "platform_blackcard",
        "kind": "platform_activity",
        "title": "黑卡会员券",
        "content": "黑卡会员可领取 50 元美妆/户外品类券，需在活动页领取后使用。",
    },
)


def search_policies(topic: str | None = None) -> list[dict[str, Any]]:
    text = (topic or "").strip()
    if not text:
        return [dict(item) for item in POLICIES]
    hits = [
        dict(item)
        for item in POLICIES
        if text in item["title"] or text in item["content"] or item["kind"] in text
    ]
    return hits or [dict(item) for item in POLICIES]
