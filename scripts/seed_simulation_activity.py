"""把模拟 C 端用户补齐到 80 人，并把订单 / 店宠会话补到 100 条。

链路：
- 用户：auth.create_consumer（真实注册流程）
- 订单：cstore.create_quote → prepare_order → confirm_order（真实 C 端下单链路）
- 会话：social.add_friend → social.send_message（真实店宠会话链路）
- 不直接插 c_order / c_message

用法：
    QIANKE_CEND_BACKEND=postgres QIANKE_MERCHANT_BACKEND=postgres \
    python scripts/seed_simulation_activity.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_demo import auth  # noqa: E402
from rag_demo.c_end import social  # noqa: E402
from rag_demo.c_end import store as cstore  # noqa: E402

PASSWORD = "Sim2026!"
TARGET_USERS = 80
TARGET_ORDERS = 100
TARGET_MESSAGES = 100

SURNAMES = ("赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈")
GIVEN = ("清和", "知微", "言川", "予宁", "若溪", "星野", "南栀", "以安")
NEW_NAMES = tuple(f"{SURNAMES[i % len(SURNAMES)]}{GIVEN[(i // len(SURNAMES)) % len(GIVEN)]}" for i in range(50))

MERCHANTS = {
    "m_sim_tea": ("山岚茶事", "sim_store_tea"),
    "m_sim_outdoor": ("岩行户外", "sim_store_outdoor"),
    "m_sim_home": ("晚灯家居", "sim_store_home"),
    "m_sim_coffee": ("北纬咖啡", "sim_store_coffee"),
    "m_sim_stationery": ("纸间文具", "sim_store_stationery"),
    "m_sim_fresh": ("禾木生鲜", "sim_store_fresh"),
}


def _phone(index: int) -> str:
    return f"1381000{index:04d}"


def _ensure_users() -> list[dict[str, Any]]:
    users = []
    for index in range(1, TARGET_USERS + 1):
        phone = _phone(index)
        user = auth.find_user_by_login(phone)
        if user is None:
            nickname = (
                ("林小满", "陈一诺", "周予安", "苏晚晴", "顾清和", "许知夏", "沈星野", "江屿", "唐棠", "宋知远",
                 "叶青", "程念", "陆晨", "温言", "夏栀", "白露", "韩松", "孟婉", "徐行", "乔安",
                 "罗伊", "谢遥", "秦川", "何夕", "曹阳", "邓琳", "方宁", "高远", "胡桃", "简宁")[index - 1]
                if index <= 30
                else NEW_NAMES[index - 31]
            )
            user = auth.create_consumer(phone=phone, password=PASSWORD, nickname=nickname)
        users.append(user)
    return users


def _buyer_id(user: dict[str, Any]) -> str:
    return f"buyer_{int(user['id'])}"


def _seed_cold_start(users: list[dict[str, Any]]) -> int:
    genders = ("女", "男")
    ages = ("18-24", "25-30", "31-35", "36-40", "41-45")
    cities = ("上海", "杭州", "深圳", "成都", "北京", "苏州")
    levels = ("普通", "银卡", "金卡", "黑卡")
    count = 0
    for index, user in enumerate(users, start=1):
        buyer_id = _buyer_id(user)
        cstore.upsert_user_attributes(
            buyer_id,
            gender=genders[index % len(genders)],
            age_range=ages[index % len(ages)],
            city=cities[index % len(cities)],
            member_level=levels[index % len(levels)],
            registered_at=user.get("created_at"),
            source="simulation_seed",
        )
        count += 1
    return count


def _count_orders(buyer_ids: list[str]) -> int:
    conn = cstore._connect()  # noqa: SLF001
    try:
        marks = ",".join("?" * len(buyer_ids))
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM c_order WHERE buyer_id IN ({marks})", buyer_ids).fetchone()["n"])
    finally:
        conn.close()


def _catalog() -> list[dict[str, Any]]:
    products = cstore.list_products(limit=200)
    return [p for p in products if str(p.get("product_id", "")).startswith("SIM-")]


def _create_order(buyer_id: str, index: int, products: list[dict[str, Any]]) -> str | None:
    product = products[index % len(products)]
    merchant_id = str(product["merchant_id"])
    merchant_name, friend_id = MERCHANTS[merchant_id]
    request_id = f"req_topup_{buyer_id}_{index}"
    conn = cstore._connect()  # noqa: SLF001
    try:
        if conn.execute("SELECT 1 FROM c_order WHERE idempotency_key = ?", (request_id,)).fetchone():
            return None
    finally:
        conn.close()
    quote_id = f"quote_topup_{buyer_id}_{index}"
    cstore.create_quote(
        buyer_id,
        friend_id,
        {
            "quote_id": quote_id,
            "merchant_id": merchant_id,
            "product_refs": [{
                "product_id": product["product_id"],
                "title": product["title"],
                "quantity": 1,
                "unit_price": float(product["price"]),
                "sku": f"{product['product_id']}-S1",
                "spec": "标准装",
            }],
            "policy_refs": [],
        },
    )
    draft = cstore.prepare_order(buyer_id, [], quote_id=quote_id)
    order = cstore.confirm_order(
        buyer_id,
        draft["order_id"],
        draft["confirmation_token"],
        request_id=request_id,
    )
    return str(order.get("order_id") or "")


def _count_messages(buyer_ids: list[str]) -> int:
    conn = cstore._connect()  # noqa: SLF001
    try:
        marks = ",".join("?" * len(buyer_ids))
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM c_message WHERE owner_id IN ({marks})", buyer_ids).fetchone()["n"])
    finally:
        conn.close()


def _ensure_messages(buyer_ids: list[str]) -> int:
    target = TARGET_MESSAGES
    created = 0
    current = _count_messages(buyer_ids)
    for index, buyer_id in enumerate(buyer_ids):
        if current >= target:
            break
        merchant_id = list(MERCHANTS)[index % len(MERCHANTS)]
        merchant_name, friend_id = MERCHANTS[merchant_id]
        try:
            social.add_friend(buyer_id, friend_id, merchant_name, kind="merchant", note="模拟店宠")
            social.send_message(
                buyer_id,
                friend_id,
                "你好，我想了解这款商品的发货时间、库存和售后政策。",
                reply_provider=lambda _text: ("你好，现货 48 小时内发出；支持 7 天无理由退货，具体以商品页为准。", True),
            )
        except Exception as exc:  # noqa: BLE001 - 单用户失败不阻断批量
            print(f"[warn] message {buyer_id}: {exc}")
            continue
        current = _count_messages(buyer_ids)
        created = current
    return _count_messages(buyer_ids)


def run(*, apply: bool) -> dict[str, Any]:
    users = _ensure_users()
    buyer_ids = [_buyer_id(user) for user in users]
    attributes = _seed_cold_start(users) if apply else 0
    orders_before = _count_orders(buyer_ids)
    messages_before = _count_messages(buyer_ids)
    if not apply:
        return {
            "dry_run": True,
            "users": len(users),
            "attributes": attributes,
            "orders_before": orders_before,
            "messages_before": messages_before,
        }

    products = _catalog()
    orders_created = 0
    # 先让每个新用户至少下一单，再给已有用户补到 100 单。
    for index, buyer_id in enumerate(buyer_ids, start=1):
        if _count_orders(buyer_ids) >= TARGET_ORDERS:
            break
        if index <= 30:
            continue
        try:
            order_id = _create_order(buyer_id, index, products)
            if order_id:
                orders_created += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] order {buyer_id}: {exc}")
    for index, buyer_id in enumerate(buyer_ids, start=1):
        if _count_orders(buyer_ids) >= TARGET_ORDERS:
            break
        try:
            order_id = _create_order(buyer_id, 1000 + index, products)
            if order_id:
                orders_created += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] extra order {buyer_id}: {exc}")

    messages = _ensure_messages(buyer_ids)
    return {
        "dry_run": False,
        "users": len(users),
        "attributes": attributes,
        "orders_before": orders_before,
        "orders_after": _count_orders(buyer_ids),
        "orders_created": orders_created,
        "messages_before": messages_before,
        "messages_after": messages,
        "messages_created": max(0, messages - messages_before),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = run(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
