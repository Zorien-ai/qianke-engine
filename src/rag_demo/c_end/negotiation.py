"""C 伙伴 ↔ 商家店宠的受控谈判 v1。

边界：
- 不是自由砍价/自由博弈；双方只在平台满减规则内协商。
- 商品价格、库存来自商家数据层，优惠只来自已配置平台活动。
- 达成后只创建 PENDING 报价；用户仍需在商城逐单确认，不能自动下单。
"""
from __future__ import annotations

import uuid
from typing import Any

from rag_demo.c_end import store
from rag_demo.merchant import MerchantError, get_merchant_repository

NEGOTIATION_VERSION = 1
MAX_ROUNDS = 3
STORE_MERCHANT_ID = "m_gear_002"
_MERCHANT_BUYER_IDS = {"buyer_1": "b_2001", "buyer_2": "b_2002"}


class NegotiationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _platform_discount(subtotal: float) -> float:
    if subtotal >= 599:
        return 80.0
    if subtotal >= 299:
        return 30.0
    return 0.0


def _policy_refs(subtotal: float) -> list[dict[str, Any]]:
    discount = _platform_discount(subtotal)
    if discount <= 0:
        return []
    return [
        {
            "policy_id": "platform_full_reduce",
            "kind": "platform_activity",
            "title": "平台满减活动",
            "content": f"满 299 减 30，满 599 减 80；当前小计 ¥{subtotal:.2f}。",
            "discount_amount": discount,
        }
    ]


def _merchant_candidates(need: str) -> list[dict[str, Any]]:
    """返回有库存的候选商品：关键词命中优先，其次同品类更便宜的替代。"""
    try:
        repo = get_merchant_repository()
        keyword_products = repo.list_products(STORE_MERCHANT_ID, keyword=need, limit=20)
        candidates: list[dict[str, Any]] = []
        for product in keyword_products:
            skus = repo.list_product_skus(product.product_id, merchant_id=STORE_MERCHANT_ID)
            if not skus:
                continue
            sku = skus[0]
            inventory = repo.get_inventory(sku.sku, merchant_id=STORE_MERCHANT_ID)
            if inventory is None or inventory.available_qty <= 0:
                continue
            candidates.append({
                "product_id": product.product_id,
                "title": product.title,
                "category": product.category,
                "price": float(sku.price),
                "stock": inventory.available_qty,
                "sku": sku.sku,
                "source": "merchant_v1",
            })
        if candidates:
            candidates.sort(key=lambda item: item["price"])
            categories = {str(item.get("category") or "") for item in candidates}
            seen = {item["product_id"] for item in candidates}
            for product in repo.list_products(STORE_MERCHANT_ID, keyword="", limit=20):
                if product.product_id in seen:
                    continue
                if str(product.category or "") not in categories:
                    continue
                skus = repo.list_product_skus(product.product_id, merchant_id=STORE_MERCHANT_ID)
                if not skus:
                    continue
                sku = skus[0]
                inventory = repo.get_inventory(sku.sku, merchant_id=STORE_MERCHANT_ID)
                if inventory is None or inventory.available_qty <= 0:
                    continue
                candidates.append({
                    "product_id": product.product_id,
                    "title": product.title,
                    "category": product.category,
                    "price": float(sku.price),
                    "stock": inventory.available_qty,
                    "sku": sku.sku,
                    "source": "merchant_v1",
                })
                seen.add(product.product_id)
            return candidates
    except MerchantError:
        pass

    products = store.list_products(keyword=need, limit=20)
    candidates = [
        {
            "product_id": item["product_id"],
            "title": item["title"],
            "category": item.get("category") or "",
            "price": float(item["price"]),
            "stock": int(item["stock"]),
            "source": "c_end_fallback",
        }
        for item in products
        if int(item["stock"]) > 0
    ]
    categories = {str(item.get("category") or "") for item in candidates}
    seen = {item["product_id"] for item in candidates}
    for item in store.list_products(limit=20):
        if item["product_id"] in seen or int(item["stock"]) <= 0:
            continue
        if str(item.get("category") or "") not in categories:
            continue
        candidates.append({
            "product_id": item["product_id"],
            "title": item["title"],
            "category": item.get("category") or "",
            "price": float(item["price"]),
            "stock": int(item["stock"]),
            "source": "c_end_fallback",
        })
    return sorted(candidates, key=lambda item: item["price"])


def run_negotiation(
    buyer_id: str,
    *,
    need: str,
    budget: float,
    quantity: int = 1,
) -> dict[str, Any]:
    """两个独立 Agent 的确定性多轮报价；达成时落 PENDING 报价。"""
    need = str(need or "").strip()
    if not need or len(need) > 80:
        raise NegotiationError("NEGOTIATION_INVALID", "谈判需求不能为空且不超过 80 字")
    if budget <= 0 or budget > 100000:
        raise NegotiationError("NEGOTIATION_INVALID", "预算必须大于 0 且不超过 100000")
    quantity = max(1, min(int(quantity or 1), 20))

    candidates = _merchant_candidates(need)
    if not candidates:
        return {
            "version": NEGOTIATION_VERSION,
            "status": "REJECTED",
            "reason": "MERCHANT_NO_MATCH",
            "transcript": [
                {"actor": "c_pet", "name": "小鱼", "text": f"我想在 ¥{budget:.2f} 内买{need}，有合适的吗？"},
                {"actor": "b_pet", "name": "山野店宠", "text": "店里暂时没有匹配且有库存的商品。"},
                {"actor": "c_pet", "name": "小鱼", "text": "那这次先不成交，等有合适商品再看。"},
            ],
            "quote": None,
        }

    transcript: list[dict[str, Any]] = [
        {
            "actor": "c_pet",
            "name": "小鱼",
            "text": f"我想在 ¥{budget:.2f} 内买{need}，数量 {quantity}，你先报个能成交的方案。",
        }
    ]
    max_rounds = min(MAX_ROUNDS, max(1, len(candidates)))
    for index, candidate in enumerate(candidates[:max_rounds]):
        price = float(candidate["price"])
        available = int(candidate["stock"])
        qty = min(quantity, available)
        if qty <= 0:
            continue
        subtotal = round(price * qty, 2)
        discount = _platform_discount(subtotal)
        total = round(subtotal - discount, 2)
        policy_text = f"，平台满减 -¥{discount:.2f}" if discount else ""
        transcript.append({
            "actor": "b_pet",
            "name": "山野店宠",
            "text": (
                f"{candidate['title']}，{qty} 件，单价 ¥{price:.2f}，"
                f"小计 ¥{subtotal:.2f}{policy_text}，合计 ¥{total:.2f}。"
            ),
            "offer": {
                "product_id": candidate["product_id"],
                "title": candidate["title"],
                "price": price,
                "quantity": qty,
                "subtotal": subtotal,
                "discount": discount,
                "total": total,
                "sku": candidate.get("sku"),
                "source": candidate["source"],
            },
        })
        if total <= budget:
            transcript.append({
                "actor": "c_pet",
                "name": "小鱼",
                "text": f"这个方案在预算内，可以接受；我把它记成报价，最后仍由用户确认。",
            })
            quote_id = f"quote_neg_{uuid.uuid4().hex[:16]}"
            policy_refs = _policy_refs(subtotal)
            quote = store.create_quote(
                buyer_id,
                "store_demo",
                {
                    "quote_id": quote_id,
                    "product_refs": [{
                        "product_id": candidate["product_id"],
                        "title": candidate["title"],
                        "price": price,
                        "quantity": qty,
                    }],
                    "policy_refs": policy_refs,
                },
            )
            transcript.append({
                "actor": "b_pet",
                "name": "山野店宠",
                "text": "报价已生成，成交仍需用户在商城逐单确认。",
            })
            return {
                "version": NEGOTIATION_VERSION,
                "status": "ACCEPTED",
                "rounds": index + 1,
                "transcript": transcript,
                "quote": quote,
                "total_amount": total,
                "discount_amount": discount,
                "policy_refs": policy_refs,
            }
        transcript.append({
            "actor": "c_pet",
            "name": "小鱼",
            "text": f"合计 ¥{total:.2f} 超过预算 ¥{budget:.2f}，还有更便宜的方案吗？",
        })

    transcript.append({
        "actor": "b_pet",
        "name": "山野店宠",
        "text": "没有更低且在预算内的方案了；店宠不能擅自改价或发券。",
    })
    transcript.append({
        "actor": "c_pet",
        "name": "小鱼",
        "text": "那这次先不成交；可以等平台活动或让我重新选商品。",
    })
    return {
        "version": NEGOTIATION_VERSION,
        "status": "REJECTED",
        "reason": "BUDGET_TOO_LOW",
        "rounds": max_rounds,
        "transcript": transcript,
        "quote": None,
    }
