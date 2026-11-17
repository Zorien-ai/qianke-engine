"""C 端自由砍价引擎 v1。

边界：
- C 小鱼和 B 店宠可以做多轮自然语言协商；
- 价格、库存、商家底价和让利额度全部由确定性代码计算；
- 自动额度内直接生成 PENDING 报价，超出自动额度转 B 端审批；
- 最终仍由用户在订单草稿中确认，不自动下单。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from rag_demo.c_end import store
from rag_demo.merchant import MerchantError, get_merchant_repository

BARGAIN_VERSION = 1
PLATFORM_FULL_REDUCE = ((599.0, 80.0), (299.0, 30.0))
TARGET_RE = re.compile(r"(?:¥|￥|预算|目标价?|便宜到|卖|成交)?\s*(\d{1,6}(?:\.\d{1,2})?)\s*(?:元|块)?")
ACCEPT_RE = re.compile(r"(可以|成交|行啊|行吧|行|接受|要了|好吧|OK|ok|就这么定)")
REJECT_RE = re.compile(r"(不买|不要了|算了|太贵|不考虑|放弃|不砍了)")
CHEAPER_RE = re.compile(r"(再便宜|便宜点|少点|降点|再低|优惠点|能少)")


class BargainError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _expires_at(minutes: int) -> str:
    return _iso(_now() + timedelta(minutes=max(1, int(minutes))))


def _platform_discount(subtotal: float) -> float:
    for threshold, amount in PLATFORM_FULL_REDUCE:
        if subtotal >= threshold:
            return amount
    return 0.0


def _resolve_merchant(friend_id: str) -> str:
    friend = str(friend_id or "").strip()
    if not friend:
        raise BargainError("BARGAIN_FRIEND_REQUIRED", "缺少商家店宠")
    merchant_id = store.merchant_for_store_friend(friend)
    if not merchant_id:
        raise BargainError("BARGAIN_FRIEND_NOT_FOUND", "店宠不存在或未绑定商家")
    return str(merchant_id)


def _merchant_sku(merchant_id: str, sku: str) -> dict[str, Any] | None:
    try:
        repo = get_merchant_repository()
        for product in repo.list_products(merchant_id, limit=200):
            for product_sku in repo.list_product_skus(product.product_id, merchant_id=merchant_id):
                if product_sku.sku != sku:
                    continue
                inventory = repo.get_inventory(product_sku.sku, merchant_id=merchant_id)
                available = int(inventory.available_qty) if inventory else 0
                return {
                    "product_id": product.product_id,
                    "title": product.title,
                    "category": product.category,
                    "sku": product_sku.sku,
                    "spec": product_sku.spec,
                    "price": float(product_sku.price),
                    "stock": available,
                    "source": "merchant_v1",
                }
    except MerchantError:
        return None
    return None


def _resolve_items(
    merchant_id: str,
    *,
    sku: str | None = None,
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    if items:
        for raw in items[:10]:
            try:
                line_sku = str(raw.get("sku") or "").strip()
                quantity = int(raw.get("quantity") or 1)
            except (TypeError, ValueError):
                raise BargainError("BARGAIN_ITEM_INVALID", "商品规格或数量无效") from None
            if not line_sku or quantity < 1 or quantity > 20:
                raise BargainError("BARGAIN_ITEM_INVALID", "商品数量必须在 1–20 之间")
            requests.append({"sku": line_sku, "quantity": quantity})
    elif sku:
        requests.append({"sku": str(sku).strip(), "quantity": 1})
    if not requests:
        raise BargainError("BARGAIN_ITEM_REQUIRED", "请选择要砍价的商品")

    merged: dict[str, dict[str, Any]] = {}
    for line in requests:
        existing = merged.get(line["sku"])
        if existing:
            existing["quantity"] = min(20, int(existing["quantity"]) + int(line["quantity"]))
        else:
            merged[line["sku"]] = dict(line)

    resolved: list[dict[str, Any]] = []
    for line in merged.values():
        product = _merchant_sku(merchant_id, line["sku"])
        if product is None:
            raise BargainError("BARGAIN_SKU_NOT_FOUND", f"规格 {line['sku']} 不存在")
        if int(product["stock"]) < int(line["quantity"]):
            raise BargainError("INSUFFICIENT_STOCK", f"{product['title']} 库存不足")
        resolved.append({
            **product,
            "quantity": int(line["quantity"]),
            "subtotal": _money(product["price"] * int(line["quantity"])),
        })
    return resolved


def _policy(merchant_id: str) -> dict[str, Any]:
    policy = store.get_bargain_policy(merchant_id)
    if not policy.get("enabled"):
        raise BargainError("BARGAIN_DISABLED", "该商家暂未开启砍价")
    return policy


def _items_text(items: list[dict[str, Any]]) -> str:
    return "、".join(f"{item['title']} {item['spec']} ×{item['quantity']}" for item in items)


def _base_values(items: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, float]:
    list_total = _money(sum(float(item["price"]) * int(item["quantity"]) for item in items))
    platform = _money(_platform_discount(list_total))
    base_payable = _money(max(0.0, list_total - platform))
    floor = _money(min(list_total, list_total * float(policy["floor_ratio"])))
    max_discount = _money(min(list_total * float(policy["max_merchant_discount_ratio"]), max(0.0, base_payable - floor)))
    auto_cap = _money(min(max_discount, list_total * float(policy["auto_approve_discount_ratio"])))
    return {
        "list_total": list_total,
        "platform_discount": platform,
        "base_payable": base_payable,
        "floor": floor,
        "max_discount": max_discount,
        "auto_cap": auto_cap,
    }


def _offer(
    values: dict[str, float],
    merchant_discount: float,
    *,
    approval_required: bool,
    expires_minutes: int,
) -> dict[str, Any]:
    discount = _money(min(max(0.0, merchant_discount), values["max_discount"]))
    payable = _money(max(0.0, values["base_payable"] - discount))
    return {
        "offer_id": f"offer_{uuid.uuid4().hex[:14]}",
        "payable": payable,
        "merchant_discount": discount,
        "platform_discount": values["platform_discount"],
        "approval_required": bool(approval_required),
        "expires_at": _expires_at(expires_minutes),
    }


def _counter_offer(
    values: dict[str, float],
    target: float,
    policy: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    base = values["base_payable"]
    target = _money(target)
    if target >= base:
        offer = _offer(values, 0.0, approval_required=False, expires_minutes=policy["expires_minutes"])
        return offer, f"不用降，当前到手价就是 ¥{base:.2f}；你要的话我按这个价给你留报价。"
    if target < values["floor"]:
        discount = values["base_payable"] - values["floor"]
        offer = _offer(values, discount, approval_required=discount > values["auto_cap"], expires_minutes=policy["expires_minutes"])
        return offer, (
            f"¥{target:.2f} 太低了，我最多能做到 ¥{offer['payable']:.2f}；"
            f"这个价{'还要店长确认' if offer['approval_required'] else '我可以直接给你'}。"
        )
    discount = _money(base - target)
    if discount <= values["auto_cap"] + 0.005:
        offer = _offer(values, discount, approval_required=False, expires_minutes=policy["expires_minutes"])
        return offer, f"¥{target:.2f} 可以，成交价 ¥{offer['payable']:.2f}，我给你出报价。"
    if discount <= values["max_discount"] + 0.005:
        offer = _offer(values, discount, approval_required=True, expires_minutes=policy["expires_minutes"])
        return offer, (
            f"¥{target:.2f} 我这边可以做，但让利超过自动额度，"
            f"需要店长确认；确认后按 ¥{offer['payable']:.2f} 成交。"
        )
    discount = values["max_discount"]
    offer = _offer(values, discount, approval_required=discount > values["auto_cap"], expires_minutes=policy["expires_minutes"])
    return offer, (
        f"¥{target:.2f} 低于我的底价，我最多能给到 ¥{offer['payable']:.2f}；"
        f"这个价{'需要店长确认' if offer['approval_required'] else '可以直接成交'}。"
    )


def _public(session: dict[str, Any]) -> dict[str, Any]:
    """C 端可见会话；不暴露商家底价/最大让利等内部策略。"""
    offer = dict(session.get("current_offer") or {})
    approval = None
    if session.get("approval_id"):
        approval = store.get_bargain_approval(str(session["approval_id"]))
    return {
        "version": BARGAIN_VERSION,
        "bargain_id": session.get("bargain_id"),
        "buyer_id": session.get("buyer_id"),
        "merchant_id": session.get("merchant_id"),
        "status": session.get("status"),
        "items": [
            {
                "product_id": item.get("product_id"),
                "title": item.get("title"),
                "sku": item.get("sku"),
                "spec": item.get("spec"),
                "price": item.get("price"),
                "quantity": item.get("quantity"),
                "subtotal": item.get("subtotal"),
                "image_url": item.get("image_url"),
            }
            for item in session.get("items") or []
        ],
        "list_total": session.get("list_total"),
        "platform_discount": session.get("platform_discount"),
        "target_price": session.get("target_price"),
        "current_offer": {
            "offer_id": offer.get("offer_id"),
            "payable": offer.get("payable"),
            "merchant_discount": offer.get("merchant_discount"),
            "platform_discount": offer.get("platform_discount"),
            "approval_required": bool(offer.get("approval_required")),
            "expires_at": offer.get("expires_at"),
        } if offer else None,
        "merchant_discount": session.get("merchant_discount"),
        "transcript": session.get("transcript") or [],
        "quote": store.get_quote(str(session["quote_id"]), session.get("buyer_id")) if session.get("quote_id") else None,
        "approval": approval,
        "expires_at": session.get("expires_at"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }


def _session_or_error(bargain_id: str, buyer_id: str) -> dict[str, Any]:
    session = store.get_bargain_session(bargain_id, buyer_id=buyer_id)
    if session is None:
        raise BargainError("BARGAIN_NOT_FOUND", "砍价会话不存在")
    if session["status"] in {"REJECTED", "EXPIRED", "ACCEPTED"}:
        return session
    expires_at = str(session.get("expires_at") or "")
    try:
        expired = datetime.fromisoformat(expires_at) <= _now()
    except ValueError:
        expired = False
    if expired:
        store.update_bargain_session(bargain_id, status="EXPIRED")
        session["status"] = "EXPIRED"
    return session


def _append(session: dict[str, Any], actor: str, name: str, text: str, **extra: Any) -> list[dict[str, Any]]:
    transcript = list(session.get("transcript") or [])
    item = {"actor": actor, "name": name, "text": text, "at": _iso(_now()), **extra}
    transcript.append(item)
    return transcript


def _assert_session_fresh(session: dict[str, Any]) -> None:
    """接受/审批前重新校验价格和库存，不能拿旧快照成交。"""
    try:
        current = _resolve_items(
            str(session["merchant_id"]),
            items=[{"sku": item["sku"], "quantity": item["quantity"]} for item in session.get("items") or []],
        )
    except BargainError as exc:
        if exc.code == "INSUFFICIENT_STOCK":
            raise BargainError("BARGAIN_STALE", "库存已经变化，请重新砍价") from exc
        raise
    old_by_sku = {item.get("sku"): item for item in session.get("items") or []}
    for item in current:
        old = old_by_sku.get(item.get("sku"))
        if old is None or abs(float(old.get("price") or 0) - float(item.get("price") or 0)) > 0.005:
            raise BargainError("BARGAIN_STALE", "商品价格已变化，请重新砍价")
        if int(item.get("stock") or 0) < int(item.get("quantity") or 1):
            raise BargainError("BARGAIN_STALE", "库存已经变化，请重新砍价")


def _assert_session_not_expired(session: dict[str, Any]) -> None:
    try:
        expired = datetime.fromisoformat(str(session.get("expires_at") or "")) <= _now()
    except ValueError:
        expired = False
    if expired:
        store.update_bargain_session(str(session["bargain_id"]), status="EXPIRED")
        raise BargainError("BARGAIN_EXPIRED", "砍价会话已过期，请重新发起")


def _quote_for_offer(session: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    buyer_id = str(session["buyer_id"])
    quote_id = f"quote_bargain_{uuid.uuid4().hex[:16]}"
    platform = _money(session.get("platform_discount"))
    merchant_discount = _money(offer.get("merchant_discount"))
    policy_refs: list[dict[str, Any]] = []
    if platform > 0:
        policy_refs.append({
            "policy_id": "platform_full_reduce",
            "kind": "platform_activity",
            "title": "平台满减活动",
            "discount_amount": platform,
        })
    if merchant_discount > 0:
        policy_refs.append({
            "policy_id": "merchant_bargain",
            "kind": "merchant_bargain",
            "title": "商家砍价让利",
            "discount_amount": merchant_discount,
        })
    quote = store.create_quote(
        buyer_id,
        str(session["friend_id"]),
        {
            "quote_id": quote_id,
            "merchant_id": session["merchant_id"],
            "friend_id": session["friend_id"],
            "product_refs": [
                {
                    "product_id": item["product_id"],
                    "title": item["title"],
                    "price": item["price"],
                    "unit_price": item["price"],
                    "quantity": item["quantity"],
                    "sku": item["sku"],
                    "spec": item.get("spec") or "",
                }
                for item in session.get("items") or []
            ],
            "policy_refs": policy_refs,
        },
    )
    if not quote:
        raise BargainError("BARGAIN_QUOTE_FAILED", "报价生成失败")
    quote["total_amount"] = _money(offer.get("payable"))
    quote["discount_amount"] = _money(platform + merchant_discount)
    return quote


def create_bargain(
    buyer_id: str,
    *,
    friend_id: str,
    sku: str | None = None,
    items: list[dict[str, Any]] | None = None,
    target_price: float | None = None,
    message: str = "",
) -> dict[str, Any]:
    merchant_id = _resolve_merchant(friend_id)
    policy = _policy(merchant_id)
    resolved = _resolve_items(merchant_id, sku=sku, items=items)
    values = _base_values(resolved, policy)
    if target_price is not None:
        if not 0 < float(target_price) <= 100000:
            raise BargainError("BARGAIN_TARGET_INVALID", "目标价必须在 1–100000 元之间")
        target_price = _money(target_price)
    offer = _offer(values, 0.0, approval_required=False, expires_minutes=policy["expires_minutes"])
    transcript = [{
        "actor": "c_pet",
        "name": "小鱼",
        "text": (
            f"我想买{_items_text(resolved)}"
            + (f"，目标价 ¥{target_price:.2f}" if target_price is not None else "")
            + "，能聊聊吗？"
        ),
        "at": _iso(_now()),
    }]
    if target_price is not None:
        offer, reply = _counter_offer(values, target_price, policy)
        transcript.append({"actor": "b_pet", "name": "店宠", "text": reply, "at": _iso(_now()), "offer": offer})
    else:
        transcript.append({
            "actor": "b_pet",
            "name": "店宠",
            "text": (
                f"原价 ¥{values['list_total']:.2f}，平台优惠 ¥{values['platform_discount']:.2f}，"
                f"当前到手 ¥{offer['payable']:.2f}；你想多少钱拿？"
            ),
            "at": _iso(_now()),
            "offer": offer,
        })
    bargain_id = f"bargain_{uuid.uuid4().hex[:16]}"
    session = store.create_bargain_session(
        bargain_id=bargain_id,
        buyer_id=buyer_id,
        friend_id=friend_id,
        merchant_id=merchant_id,
        list_total=values["list_total"],
        platform_discount=values["platform_discount"],
        target_price=target_price,
        items=resolved,
        current_offer=offer,
        transcript=transcript,
        expires_at=_expires_at(policy["expires_minutes"]),
    )
    return _public(session)


def send_message(buyer_id: str, bargain_id: str, message: str) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        raise BargainError("BARGAIN_MESSAGE_EMPTY", "说点什么再谈")
    session = _session_or_error(bargain_id, buyer_id)
    if session["status"] == "WAITING_APPROVAL":
        raise BargainError("BARGAIN_WAITING_APPROVAL", "等商家确认当前报价")
    if session["status"] != "NEGOTIATING":
        raise BargainError("BARGAIN_NOT_NEGOTIATING", "当前砍价已结束")
    merchant_id = str(session["merchant_id"])
    policy = _policy(merchant_id)
    resolved = _resolve_items(
        merchant_id,
        items=[{"sku": item["sku"], "quantity": item["quantity"]} for item in session.get("items") or []],
    )
    values = _base_values(resolved, policy)
    current = session.get("current_offer") or {}
    c_count = sum(1 for item in session.get("transcript") or [] if item.get("actor") == "c_pet")
    if c_count >= int(policy["max_rounds"]):
        transcript = _append(session, "b_pet", "店宠", "今天已经聊到最大轮次了；你可以按当前报价成交，或者重新发起。")
        store.update_bargain_session(bargain_id, status="REJECTED", transcript=transcript)
        return _public(store.get_bargain_session(bargain_id, buyer_id=buyer_id) or session)

    target = None
    match = TARGET_RE.search(text)
    if match:
        try:
            target = _money(match.group(1))
        except ValueError:
            target = None
    # “180 可以吗”必须优先当作还价，不能因为包含“可以”直接接受旧报价。
    if target is None and ACCEPT_RE.search(text):
        return accept_offer(buyer_id, bargain_id, str(current.get("offer_id") or ""))
    if target is None and REJECT_RE.search(text):
        transcript = _append(session, "c_pet", "小鱼", text)
        transcript = _append({"transcript": transcript}, "b_pet", "店宠", "没关系，这单先不成交；有需要再叫我。")
        store.update_bargain_session(bargain_id, status="REJECTED", transcript=transcript)
        return _public(store.get_bargain_session(bargain_id, buyer_id=buyer_id) or session)
    if target is None and CHEAPER_RE.search(text):
        current_payable = float(current.get("payable") or values["base_payable"])
        step = max(5.0, round(values["list_total"] * 0.02, 2))
        target = _money(max(values["floor"], current_payable - step))
    if target is None:
        transcript = _append(session, "c_pet", "小鱼", text)
        transcript = _append({"transcript": transcript}, "b_pet", "店宠", "你直接说个数吧，比如“180 可以吗”，我看看能不能做。")
        store.update_bargain_session(bargain_id, transcript=transcript)
        return _public(store.get_bargain_session(bargain_id, buyer_id=buyer_id) or session)
    if target <= 0 or target > 100000:
        raise BargainError("BARGAIN_TARGET_INVALID", "目标价必须在 1–100000 元之间")

    offer, reply = _counter_offer(values, target, policy)
    transcript = _append(session, "c_pet", "小鱼", text)
    transcript = _append({"transcript": transcript}, "b_pet", "店宠", reply, offer=offer)
    store.update_bargain_session(
        bargain_id,
        target_price=target,
        current_offer=offer,
        merchant_discount=float(offer.get("merchant_discount") or 0),
        transcript=transcript,
    )
    return _public(store.get_bargain_session(bargain_id, buyer_id=buyer_id) or session)


def accept_offer(buyer_id: str, bargain_id: str, offer_id: str = "") -> dict[str, Any]:
    session = _session_or_error(bargain_id, buyer_id)
    if session["status"] == "WAITING_APPROVAL":
        return _public(session)
    if session["status"] != "NEGOTIATING":
        raise BargainError("BARGAIN_NOT_NEGOTIATING", "当前砍价已结束")
    current = session.get("current_offer") or {}
    if not current.get("offer_id"):
        raise BargainError("BARGAIN_OFFER_REQUIRED", "当前没有可接受报价")
    if offer_id and str(offer_id) != str(current["offer_id"]):
        raise BargainError("BARGAIN_OFFER_CHANGED", "报价已更新，请重新确认")
    merchant_id = str(session["merchant_id"])
    _assert_session_not_expired(session)
    _assert_session_fresh(session)
    policy = _policy(merchant_id)
    transcript = _append(session, "c_pet", "小鱼", f"好，就按 ¥{current['payable']:.2f} 来。")
    if current.get("approval_required"):
        approval_id = f"bapproval_{uuid.uuid4().hex[:16]}"
        approval = store.create_bargain_approval(
            approval_id=approval_id,
            bargain_id=bargain_id,
            merchant_id=merchant_id,
            buyer_id=buyer_id,
            proposed_payable=float(current["payable"]),
            merchant_discount=float(current["merchant_discount"]),
            note=f"买家接受 ¥{current['payable']:.2f}",
        )
        transcript = _append({"transcript": transcript}, "b_pet", "店宠", "这个价格我提交店长确认，确认后报价生效。")
        updated = store.update_bargain_session(
            bargain_id,
            status="WAITING_APPROVAL",
            transcript=transcript,
            approval_id=approval_id,
            merchant_discount=float(current["merchant_discount"]),
        )
        public = _public(updated or session)
        public["approval"] = approval
        return public
    quote = _quote_for_offer(session, current)
    transcript = _append({"transcript": transcript}, "b_pet", "店宠", f"成交，报价 ¥{current['payable']:.2f} 已生成，确认订单后生效。")
    updated = store.update_bargain_session(
        bargain_id,
        status="ACCEPTED",
        transcript=transcript,
        quote_id=quote["quote_id"],
        merchant_discount=float(current["merchant_discount"]),
    )
    public = _public(updated or session)
    public["quote"] = quote
    return public


def cancel_bargain(buyer_id: str, bargain_id: str) -> dict[str, Any]:
    session = _session_or_error(bargain_id, buyer_id)
    if session["status"] in {"ACCEPTED", "EXPIRED"}:
        return _public(session)
    transcript = _append(session, "c_pet", "小鱼", "这次先不砍了。")
    store.update_bargain_session(bargain_id, status="REJECTED", transcript=transcript)
    return _public(store.get_bargain_session(bargain_id, buyer_id=buyer_id) or session)


def list_approvals(merchant_id: str, *, status: str = "PENDING_APPROVAL", limit: int = 100) -> list[dict[str, Any]]:
    rows = store.list_bargain_approvals(merchant_id, status="PENDING", limit=limit) if status == "PENDING_APPROVAL" else store.list_bargain_approvals(merchant_id, status=status, limit=limit)
    results: list[dict[str, Any]] = []
    for approval in rows:
        session = store.get_bargain_session(str(approval["bargain_id"]), merchant_id=merchant_id)
        results.append({"approval": approval, "session": _public(session) if session else None})
    return results


def decide_approval(
    approval_id: str,
    *,
    approved: bool,
    decided_by: str,
    note: str = "",
) -> dict[str, Any]:
    approval = store.get_bargain_approval(approval_id)
    if approval is None:
        raise BargainError("BARGAIN_APPROVAL_NOT_FOUND", "砍价审批不存在")
    session = store.get_bargain_session(str(approval["bargain_id"]), merchant_id=str(approval["merchant_id"]))
    if session is None:
        raise BargainError("BARGAIN_NOT_FOUND", "砍价会话不存在")
    if session["status"] != "WAITING_APPROVAL":
        raise BargainError("BARGAIN_APPROVAL_NOT_PENDING", "砍价会话不在待审批状态")
    _assert_session_not_expired(session)
    if approved:
        _assert_session_fresh(session)
    decided = store.decide_bargain_approval(approval_id, approved=approved, decided_by=decided_by, note=note)
    if approved:
        current = session.get("current_offer") or {}
        offer = {
            **current,
            "payable": float(approval["proposed_payable"]),
            "merchant_discount": float(approval["merchant_discount"]),
        }
        quote = _quote_for_offer(session, offer)
        transcript = _append(session, "b_pet", "店宠", f"店长确认了 ¥{offer['payable']:.2f}，报价已生效。")
        updated = store.update_bargain_session(
            session["bargain_id"],
            status="ACCEPTED",
            transcript=transcript,
            quote_id=quote["quote_id"],
        )
        public = _public(updated or session)
        public["quote"] = quote
        public["approval"] = decided
        return public
    transcript = _append(session, "b_pet", "店宠", "店长没有同意这个价格，这次先不成交。")
    updated = store.update_bargain_session(session["bargain_id"], status="REJECTED", transcript=transcript)
    public = _public(updated or session)
    public["approval"] = decided
    return public

def get_bargain(buyer_id: str, bargain_id: str) -> dict[str, Any]:
    session = _session_or_error(bargain_id, buyer_id)
    return _public(session)
