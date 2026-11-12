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


def _merchant_candidates(
    need: str,
    merchant_id: str = STORE_MERCHANT_ID,
    sku: str | None = None,
) -> list[dict[str, Any]]:
    """返回有库存的候选商品；指定 sku 时只返回该规格。"""
    try:
        repo = get_merchant_repository()
        if sku:
            exact = str(sku).strip()
            for product in repo.list_products(merchant_id, limit=50):
                for product_sku in repo.list_product_skus(product.product_id, merchant_id=merchant_id):
                    if product_sku.sku != exact:
                        continue
                    inventory = repo.get_inventory(product_sku.sku, merchant_id=merchant_id)
                    if inventory is None or inventory.available_qty <= 0:
                        return []
                    return [{
                        "product_id": product.product_id,
                        "title": product.title,
                        "category": product.category,
                        "price": float(product_sku.price),
                        "stock": inventory.available_qty,
                        "sku": product_sku.sku,
                        "spec": product_sku.spec,
                        "source": "merchant_v1",
                    }]
            return []
        keyword_products = repo.list_products(merchant_id, keyword=need, limit=20)
        candidates: list[dict[str, Any]] = []
        for product in keyword_products:
            skus = repo.list_product_skus(product.product_id, merchant_id=merchant_id)
            if not skus:
                continue
            sku = skus[0]
            inventory = repo.get_inventory(sku.sku, merchant_id=merchant_id)
            if inventory is None or inventory.available_qty <= 0:
                continue
            candidates.append({
                "product_id": product.product_id,
                "title": product.title,
                "category": product.category,
                "price": float(sku.price),
                "stock": inventory.available_qty,
                "sku": sku.sku,
                "spec": sku.spec,
                "source": "merchant_v1",
            })
        if candidates:
            candidates.sort(key=lambda item: item["price"])
            categories = {str(item.get("category") or "") for item in candidates}
            seen = {item["product_id"] for item in candidates}
            for product in repo.list_products(merchant_id, keyword="", limit=20):
                if product.product_id in seen:
                    continue
                if str(product.category or "") not in categories:
                    continue
                skus = repo.list_product_skus(product.product_id, merchant_id=merchant_id)
                if not skus:
                    continue
                sku = skus[0]
                inventory = repo.get_inventory(sku.sku, merchant_id=merchant_id)
                if inventory is None or inventory.available_qty <= 0:
                    continue
                candidates.append({
                    "product_id": product.product_id,
                    "title": product.title,
                    "category": product.category,
                    "price": float(sku.price),
                    "stock": inventory.available_qty,
                    "sku": sku.sku,
                    "spec": sku.spec,
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


def _negotiate_cart(
    *,
    buyer_id: str,
    friend_id: str,
    merchant_id: str,
    store_name: str,
    b_pet_name: str,
    need: str,
    budget: float,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """购物车多商品合并报价；价格/库存全部来自商家 SKU。"""
    if len(items) > 10:
        raise NegotiationError("NEGOTIATION_INVALID", "一次最多合并 10 个商品")

    merged: dict[str, dict[str, Any]] = {}
    for raw in items:
        try:
            sku = str(raw.get("sku") or "").strip()
            qty = int(raw.get("quantity") or 1)
        except (TypeError, ValueError):
            raise NegotiationError("NEGOTIATION_INVALID", "购物车商品数量无效") from None
        if not sku or qty <= 0 or qty > 20:
            raise NegotiationError("NEGOTIATION_INVALID", "购物车商品数量必须在 1–20 之间")
        existing = merged.get(sku)
        if existing:
            existing["quantity"] = min(20, int(existing["quantity"]) + qty)
        else:
            merged[sku] = {"sku": sku, "quantity": qty}

    transcript: list[dict[str, Any]] = [{
        "actor": "c_pet",
        "name": "小鱼",
        "text": f"我想把购物车里的 {len(merged)} 个商品一起买，预算 ¥{budget:.2f}，能合并报个价吗？",
    }]
    resolved: list[dict[str, Any]] = []
    subtotal = 0.0
    for line in merged.values():
        candidates = _merchant_candidates("", merchant_id, sku=line["sku"])
        if not candidates:
            transcript.append({
                "actor": "b_pet",
                "name": b_pet_name,
                "text": f"规格 {line['sku']} 暂时没有库存。",
            })
            return {
                "version": NEGOTIATION_VERSION,
                "status": "REJECTED",
                "reason": "SKU_NOT_AVAILABLE",
                "transcript": transcript,
                "quote": None,
            }
        candidate = candidates[0]
        available = int(candidate["stock"])
        if available < int(line["quantity"]):
            transcript.append({
                "actor": "b_pet",
                "name": b_pet_name,
                "text": f"{candidate['title']} 当前只剩 {available} 件，不够 {line['quantity']} 件。",
            })
            return {
                "version": NEGOTIATION_VERSION,
                "status": "REJECTED",
                "reason": "INSUFFICIENT_STOCK",
                "transcript": transcript,
                "quote": None,
            }
        price = float(candidate["price"])
        qty = int(line["quantity"])
        line_total = round(price * qty, 2)
        subtotal = round(subtotal + line_total, 2)
        resolved.append({
            "product_id": candidate["product_id"],
            "title": candidate["title"],
            "price": price,
            "unit_price": price,
            "quantity": qty,
            "subtotal": line_total,
            "sku": candidate["sku"],
            "spec": candidate.get("spec") or "",
            "source": candidate["source"],
        })

    discount = _platform_discount(subtotal)
    total = round(subtotal - discount, 2)
    policy_refs = _policy_refs(subtotal)
    summary = "；".join(
        f"{item['title']} {item['spec']} × {item['quantity']} ¥{item['subtotal']:.2f}"
        for item in resolved
    )
    policy_text = f"，平台满减 -¥{discount:.2f}" if discount else ""
    transcript.append({
        "actor": "b_pet",
        "name": b_pet_name,
        "text": f"合并报价：{summary}；合计 ¥{subtotal:.2f}{policy_text}，应付 ¥{total:.2f}。",
        "offer": {
            "items": resolved,
            "subtotal": subtotal,
            "discount": discount,
            "total": total,
            "source": "merchant_v1",
        },
    })
    if total > budget:
        transcript.append({
            "actor": "c_pet",
            "name": "小鱼",
            "text": f"合计 ¥{total:.2f} 超过预算 ¥{budget:.2f}，先不成交；可以减数量或等平台活动。",
        })
        return {
            "version": NEGOTIATION_VERSION,
            "status": "REJECTED",
            "reason": "BUDGET_TOO_LOW",
            "rounds": 1,
            "transcript": transcript,
            "quote": None,
        }

    transcript.append({
        "actor": "c_pet",
        "name": "小鱼",
        "text": "这个合并方案在预算内，我把它记成报价；最后仍由用户确认。",
    })
    quote_id = f"quote_neg_{uuid.uuid4().hex[:16]}"
    quote = store.create_quote(
        buyer_id,
        friend_id,
        {
            "quote_id": quote_id,
            "merchant_id": merchant_id,
            "friend_id": friend_id,
            "product_refs": [
                {
                    "product_id": item["product_id"],
                    "title": item["title"],
                    "price": item["price"],
                    "unit_price": item["unit_price"],
                    "quantity": item["quantity"],
                    "sku": item["sku"],
                    **({"spec": item["spec"]} if item["spec"] else {}),
                }
                for item in resolved
            ],
            "policy_refs": policy_refs,
        },
    )
    transcript.append({
        "actor": "b_pet",
        "name": b_pet_name,
        "text": "合并报价已生成，成交仍需用户在商城逐单确认。",
    })
    return {
        "version": NEGOTIATION_VERSION,
        "status": "ACCEPTED",
        "rounds": 1,
        "transcript": transcript,
        "quote": quote,
        "total_amount": total,
        "discount_amount": discount,
        "policy_refs": policy_refs,
        "items": resolved,
    }


def run_negotiation(
    buyer_id: str,
    *,
    need: str,
    budget: float,
    quantity: int = 1,
    friend_id: str | None = None,
    merchant_id: str | None = None,
    sku: str | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """两个独立 Agent 的确定性多轮报价；达成时落 PENDING 报价。

    items 存在时按购物车多商品合并报价，忽略单商品 sku/quantity。
    """
    resolved_friend = str(friend_id or "store_demo")
    resolved_merchant = str(
        merchant_id
        or store.merchant_for_store_friend(resolved_friend)
        or STORE_MERCHANT_ID
    )
    store_name = str((store.get_tenant(resolved_merchant) or {}).get("name") or "商家")
    b_pet_name = f"{store_name}店宠"
    need = str(need or "").strip()
    if not need or len(need) > 80:
        raise NegotiationError("NEGOTIATION_INVALID", "谈判需求不能为空且不超过 80 字")
    if budget <= 0 or budget > 100000:
        raise NegotiationError("NEGOTIATION_INVALID", "预算必须大于 0 且不超过 100000")
    quantity = max(1, min(int(quantity or 1), 20))

    if items:
        return _negotiate_cart(
            buyer_id=buyer_id,
            friend_id=resolved_friend,
            merchant_id=resolved_merchant,
            store_name=store_name,
            b_pet_name=b_pet_name,
            need=need,
            budget=budget,
            items=items,
        )

    requested_sku = str(sku or "").strip() or None
    candidates = _merchant_candidates(need, resolved_merchant, sku=requested_sku)
    if not candidates:
        return {
            "version": NEGOTIATION_VERSION,
            "status": "REJECTED",
            "reason": "SKU_NOT_AVAILABLE" if requested_sku else "MERCHANT_NO_MATCH",
            "transcript": [
                {"actor": "c_pet", "name": "小鱼", "text": f"我想在 ¥{budget:.2f} 内买{need}，有合适的吗？"},
                {"actor": "b_pet", "name": b_pet_name, "text": "店里暂时没有匹配且有库存的商品。"},
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
        if available < quantity:
            transcript.append({
                "actor": "b_pet",
                "name": b_pet_name,
                "text": f"{candidate['title']} 当前只剩 {available} 件，不够你要的 {quantity} 件。",
            })
            transcript.append({
                "actor": "c_pet",
                "name": "小鱼",
                "text": "库存不够，这次先不成交；可以减数量或换规格。",
            })
            return {
                "version": NEGOTIATION_VERSION,
                "status": "REJECTED",
                "reason": "INSUFFICIENT_STOCK",
                "rounds": index + 1,
                "transcript": transcript,
                "quote": None,
            }
        qty = quantity
        subtotal = round(price * qty, 2)
        discount = _platform_discount(subtotal)
        total = round(subtotal - discount, 2)
        policy_text = f"，平台满减 -¥{discount:.2f}" if discount else ""
        transcript.append({
            "actor": "b_pet",
            "name": b_pet_name,
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
                "spec": candidate.get("spec") or "",
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
                resolved_friend,
                {
                    "quote_id": quote_id,
                    "merchant_id": resolved_merchant,
                    "friend_id": resolved_friend,
                    "product_refs": [{
                        "product_id": candidate["product_id"],
                        "title": candidate["title"],
                        "price": price,
                        "unit_price": price,
                        "quantity": qty,
                        **({"sku": candidate["sku"]} if candidate.get("sku") else {}),
                        **({"spec": candidate.get("spec")} if candidate.get("spec") else {}),
                    }],
                    "policy_refs": policy_refs,
                },
            )
            transcript.append({
                "actor": "b_pet",
                "name": b_pet_name,
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
        "name": b_pet_name,
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
