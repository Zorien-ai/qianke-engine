"""生成可重复执行的模拟商家 / C 端用户数据。

只做增量插入，不删除、不重置现有数据；重复执行会跳过已存在账号、租户、商品、
订单和会话。所有账号密码仅用于本地演示环境。

用法：
    python scripts/seed_simulation.py --apply
    python scripts/seed_simulation.py --apply --merchants 6 --consumers 30
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_demo import auth  # noqa: E402
from rag_demo.c_end import store as cstore  # noqa: E402
from rag_demo.merchant import (  # noqa: E402
    get_merchant_repository,
    get_merchant_write_repository,
)

PASSWORD = "Sim2026!"
CONTACT_DOMAIN = "simulation.qianke.local"
CSTORE_THREAD = "sim_thread_{index:02d}"
RNG_SEED = 20261115


@dataclass(frozen=True)
class ProductSpec:
    suffix: str
    title: str
    category: str
    brand: str
    price: float
    stock: int = 100
    spec: str = "标准装"


@dataclass(frozen=True)
class MerchantSpec:
    merchant_id: str
    name: str
    owner_username: str
    owner_name: str
    slug: str
    products: tuple[ProductSpec, ...]
    shipping_sop: str
    return_sop: str


MERCHANTS: tuple[MerchantSpec, ...] = (
    MerchantSpec(
        "m_sim_tea", "山岚茶事", "sim_biz_tea", "山岚茶事主理人", "tea",
        (
            ProductSpec("TEA-01", "明前龙井", "绿茶", "山岚", 198),
            ProductSpec("TEA-02", "白毫银针", "白茶", "山岚", 268),
            ProductSpec("TEA-03", "桂花乌龙", "乌龙茶", "山岚", 168),
        ),
        "现货茶叶 48 小时内发出，礼盒装加防震包装。",
        "未拆封茶叶支持 7 天无理由退货；质量问题商家承担运费。",
    ),
    MerchantSpec(
        "m_sim_outdoor", "岩行户外", "sim_biz_outdoor", "岩行户外店长", "outdoor",
        (
            ProductSpec("OUT-01", "轻量冲锋衣", "户外服饰", "岩行", 499),
            ProductSpec("OUT-02", "折叠登山杖", "户外装备", "岩行", 129),
            ProductSpec("OUT-03", "真空保温壶", "户外装备", "岩行", 159),
        ),
        "现货商品 48 小时内发出，偏远地区可能延迟 1–2 天。",
        "支持 7 天无理由退货，商品需保持不影响二次销售。",
    ),
    MerchantSpec(
        "m_sim_home", "晚灯家居", "sim_biz_home", "晚灯家居主理人", "home",
        (
            ProductSpec("HOME-01", "无火香薰", "家居香氛", "晚灯", 129),
            ProductSpec("HOME-02", "水洗棉四件套", "家纺", "晚灯", 399),
            ProductSpec("HOME-03", "藤编收纳筐", "收纳", "晚灯", 89),
        ),
        "家居现货 48 小时内发出，大件商品会提前电话确认。",
        "支持 7 天无理由退货；已拆封香氛不支持退货。",
    ),
    MerchantSpec(
        "m_sim_coffee", "北纬咖啡", "sim_biz_coffee", "北纬咖啡主理人", "coffee",
        (
            ProductSpec("COF-01", "耶加雪菲咖啡豆", "咖啡豆", "北纬", 88),
            ProductSpec("COF-02", "细口手冲壶", "咖啡器具", "北纬", 199),
            ProductSpec("COF-03", "挂耳咖啡礼盒", "咖啡礼盒", "北纬", 69),
        ),
        "咖啡豆按下单顺序烘焙，48 小时内发出。",
        "食品类未拆封支持 7 天无理由退货；拆封后不支持。",
    ),
    MerchantSpec(
        "m_sim_stationery", "纸间文具", "sim_biz_stationery", "纸间文具主理人", "stationery",
        (
            ProductSpec("STA-01", "布面手账本", "手账", "纸间", 59),
            ProductSpec("STA-02", "黄铜钢笔", "书写工具", "纸间", 239),
            ProductSpec("STA-03", "城市贴纸套装", "文具周边", "纸间", 29),
        ),
        "文具现货 48 小时内发出，默认不含礼盒。",
        "不影响二次销售支持 7 天无理由退货。",
    ),
    MerchantSpec(
        "m_sim_fresh", "禾木生鲜", "sim_biz_fresh", "禾木生鲜主理人", "fresh",
        (
            ProductSpec("FRE-01", "每日坚果", "休闲食品", "禾木", 79),
            ProductSpec("FRE-02", "冻干草莓", "休闲食品", "禾木", 49),
            ProductSpec("FRE-03", "枇杷蜂蜜", "冲调饮品", "禾木", 99),
        ),
        "生鲜食品 48 小时内发出，夏季默认加冰袋。",
        "食品类未拆封支持 7 天无理由退货；拆封后不支持。",
    ),
)

CONSUMER_NAMES: tuple[str, ...] = (
    "林小满", "陈一诺", "周予安", "苏晚晴", "顾清和",
    "许知夏", "沈星野", "江屿", "唐棠", "宋知远",
    "叶青", "程念", "陆晨", "温言", "夏栀",
    "白露", "韩松", "孟婉", "徐行", "乔安",
    "罗伊", "谢遥", "秦川", "何夕", "曹阳",
    "邓琳", "方宁", "高远", "胡桃", "简宁",
)


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _find_user(username: str) -> dict[str, Any] | None:
    return auth.find_user(username)


def _ensure_merchant_owner(spec: MerchantSpec) -> dict[str, Any]:
    username = spec.owner_username
    user = _find_user(username)
    if user is None:
        user = auth.create_user(
            username,
            PASSWORD,
            auth.ACCOUNT_ENTERPRISE,
            display_name=spec.owner_name,
            contact=f"{username}@{CONTACT_DOMAIN}",
        )
    if user.get("status") != auth.STATUS_ACTIVE:
        user = auth.approve(int(user["id"]), "ent_admin", actor="simulation_seed")
    return user


def _ensure_tenant(spec: MerchantSpec, owner: dict[str, Any]) -> bool:
    tenant = cstore.get_tenant(spec.merchant_id)
    if tenant is not None:
        return False
    member = cstore.get_merchant_member(int(owner["id"]))
    if member is not None and member["merchant_id"] != spec.merchant_id:
        raise RuntimeError(f"{spec.owner_username} 已绑定其他商家 {member['merchant_id']}")
    cstore.provision_tenant(
        spec.merchant_id,
        spec.name,
        int(owner["id"]),
        compensation_max_amount=50,
        refund_max_amount=1000,
        created_by="simulation_seed",
    )
    return True


def _insert_merchant_catalog(spec: MerchantSpec) -> int:
    repo = get_merchant_repository()
    created = 0
    now = _now()
    with repo._transaction() as cur:  # noqa: SLF001 - 种子脚本复用存储层事务
        for product in spec.products:
            product_id = f"SIM-{product.suffix}"
            sku = f"{product_id}-S1"
            cur.execute(
                "INSERT INTO m_product "
                "(product_id, merchant_id, title, category, brand, status, created_at, image_url, images_json) "
                "VALUES (%s, %s, %s, %s, %s, 'ACTIVE', %s, NULL, NULL) "
                "ON CONFLICT (product_id) DO NOTHING",
                (product_id, spec.merchant_id, product.title, product.category, product.brand, now),
            )
            cur.execute(
                "INSERT INTO m_sku "
                "(sku, merchant_id, product_id, spec, price, status, barcode) "
                "VALUES (%s, %s, %s, %s, %s, 'ACTIVE', %s) "
                "ON CONFLICT (sku) DO NOTHING",
                (sku, spec.merchant_id, product_id, product.spec, f"{product.price:.2f}", None),
            )
            cur.execute(
                "INSERT INTO m_inventory "
                "(sku, warehouse_id, merchant_id, available_qty, reserved_qty, safety_stock, updated_at) "
                "VALUES (%s, 'WH-SIM', %s, %s, 0, 5, %s) "
                "ON CONFLICT (sku, warehouse_id) DO NOTHING",
                (sku, spec.merchant_id, product.stock, now),
            )
            created += 1
    return created


def _insert_c_catalog(spec: MerchantSpec) -> int:
    cstore.init()
    conn = cstore._connect()  # noqa: SLF001 - 种子脚本复用 C 端存储连接
    created = 0
    try:
        for product in spec.products:
            product_id = f"SIM-{product.suffix}"
            cur = conn.execute(
                "INSERT INTO c_product(product_id, merchant_id, title, category, price, stock) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(product_id) DO NOTHING",
                (product_id, spec.merchant_id, product.title, product.category, product.price, product.stock),
            )
            created += int(cur.rowcount or 0)
        for topic, title, content in (
            ("shipping", "发货时效", spec.shipping_sop),
            ("return", "售后与退货", spec.return_sop),
            ("no_change_price", "店宠改价权限", "店宠无权直接改价、发券或承诺赔付。"),
        ):
            conn.execute(
                "INSERT INTO c_merchant_sop(merchant_id, topic, title, content, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(merchant_id, topic) DO UPDATE SET "
                "title = excluded.title, content = excluded.content, updated_at = excluded.updated_at",
                (spec.merchant_id, topic, title, content, _now()),
            )
        conn.commit()
    finally:
        conn.close()
    try:
        cstore.bind_store_friend(spec.merchant_id, f"sim_store_{spec.slug}")
    except Exception:  # noqa: BLE001 - 店宠映射已存在/可恢复时不影响商品和订单
        pass
    return created


def _ensure_consumer(index: int) -> dict[str, Any]:
    phone = f"1381000{index:04d}"
    nickname = CONSUMER_NAMES[index - 1]
    user = auth.find_user_by_login(phone)
    if user is None:
        user = auth.create_consumer(phone=phone, password=PASSWORD, nickname=nickname)
    if user.get("status") != auth.STATUS_ACTIVE:
        user = auth.approve(int(user["id"]), "buyer", actor="simulation_seed")
    return user


def _order_exists(request_id: str) -> bool:
    conn = cstore._connect()  # noqa: SLF001
    try:
        row = conn.execute(
            "SELECT 1 FROM c_order WHERE idempotency_key = ?", (request_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _create_order(
    buyer_id: str,
    consumer_index: int,
    order_index: int,
    catalog: list[tuple[MerchantSpec, ProductSpec]],
    rng: random.Random,
) -> dict[str, Any] | None:
    request_id = f"req_sim_{consumer_index:02d}_{order_index:02d}"
    if _order_exists(request_id):
        return None
    merchant, first = rng.choice(catalog)
    picked = [first]
    if rng.random() < 0.35:
        alternatives = [p for m, p in catalog if m.merchant_id == merchant.merchant_id and p != first]
        if alternatives:
            picked.append(rng.choice(alternatives))
    refs = [
        {
            "product_id": f"SIM-{product.suffix}",
            "title": product.title,
            "quantity": rng.randint(1, 2),
            "unit_price": product.price,
            "sku": f"SIM-{product.suffix}-S1",
            "spec": product.spec,
        }
        for product in picked
    ]
    quote_id = f"quote_{request_id}_{merchant.slug}"
    cstore.create_quote(
        buyer_id,
        f"sim_store_{merchant.slug}",
        {
            "quote_id": quote_id,
            "merchant_id": merchant.merchant_id,
            "product_refs": refs,
            "policy_refs": [],
        },
    )
    draft = cstore.prepare_order(buyer_id, [], quote_id=quote_id)
    return cstore.confirm_order(
        buyer_id,
        draft["order_id"],
        draft["confirmation_token"],
        request_id=request_id,
    )


def _seed_messages(buyer_id: str, index: int) -> int:
    thread_id = CSTORE_THREAD.format(index=index)
    conn = cstore._connect()  # noqa: SLF001
    try:
        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM c_app_message WHERE owner_id = ? AND thread_id = ?",
            (buyer_id, thread_id),
        ).fetchone()
        if int(existing["n"]) > 0:
            return 0
    finally:
        conn.close()
    cstore.save_app_message(
        buyer_id,
        thread_id,
        "user",
        "你好，想确认一下这款商品的发货时间和售后政策。",
    )
    cstore.save_app_message(
        buyer_id,
        thread_id,
        "companion",
        "在的，现货一般 48 小时内发出；支持 7 天无理由退货，具体以商品页面说明为准。",
    )
    return 2


def _advance_sim_orders(merchant_specs: list[MerchantSpec]) -> int:
    """把模拟商家订单推进到已支付 / 已发货 / 已完成，避免整批都是待支付。"""
    repo = get_merchant_repository()
    writer = get_merchant_write_repository()
    changed = 0
    for spec in merchant_specs:
        orders = sorted(repo.list_orders(spec.merchant_id, limit=500), key=lambda o: str(o.created_at))
        for index, order in enumerate(orders):
            if not str(order.buyer_id).startswith("buyer_"):
                continue
            if str(order.status).upper() != "CREATED":
                continue
            target = ("PAID", "SHIPPED", "COMPLETED")[index % 3]
            try:
                writer.update_order_status(spec.merchant_id, order.order_id, "PAID")
                if target in {"SHIPPED", "COMPLETED"}:
                    writer.update_order_status(
                        spec.merchant_id,
                        order.order_id,
                        "SHIPPED",
                        tracking_no=f"SF-SIM-{order.order_id[-8:].upper()}",
                        carrier="顺丰",
                    )
                if target == "COMPLETED":
                    writer.update_order_status(spec.merchant_id, order.order_id, "COMPLETED")
                changed += 1
            except Exception as exc:  # noqa: BLE001 - 状态推进失败不阻断造数
                print(f"[warn] advance {spec.merchant_id}/{order.order_id} -> {target}: {exc}")
    return changed


def seed(*, merchants: int, consumers: int, apply: bool) -> dict[str, Any]:
    merchant_specs = MERCHANTS[: max(0, min(merchants, len(MERCHANTS)))]
    if not apply:
        return {
            "dry_run": True,
            "merchants": [spec.merchant_id for spec in merchant_specs],
            "consumers": [f"1381000{index:04d}" for index in range(1, consumers + 1)],
            "products": sum(len(spec.products) for spec in merchant_specs),
        }

    owner_ids: list[int] = []
    tenant_created = 0
    catalog_created = 0
    c_catalog_created = 0
    for spec in merchant_specs:
        owner = _ensure_merchant_owner(spec)
        owner_ids.append(int(owner["id"]))
        if _ensure_tenant(spec, owner):
            tenant_created += 1
        catalog_created += _insert_merchant_catalog(spec)
        c_catalog_created += _insert_c_catalog(spec)

    rng = random.Random(RNG_SEED)
    catalog = [
        (spec, product)
        for spec in merchant_specs
        for product in spec.products
    ]
    buyers: list[dict[str, Any]] = []
    orders_created = 0
    messages_created = 0
    for index in range(1, min(consumers, len(CONSUMER_NAMES)) + 1):
        user = _ensure_consumer(index)
        buyer_id = f"buyer_{int(user['id'])}"
        buyers.append(user)
        # 订单数量必须与数据库当前状态无关；否则已有订单提前 return 会改变 RNG 序列，
        # 重跑时凭空多生成订单。固定按用户序号决定 1 或 2 单。
        order_total = 2 if index % 3 == 0 else 1
        for order_index in range(1, order_total + 1):
            try:
                order = _create_order(buyer_id, index, order_index, catalog, rng)
            except Exception as exc:  # noqa: BLE001 - 单笔失败不阻断整批，最后汇总
                print(f"[warn] consumer={index} order={order_index} 跳过: {exc}")
                continue
            if order is not None:
                orders_created += 1
        messages_created += _seed_messages(buyer_id, index)

    orders_advanced = _advance_sim_orders(merchant_specs)
    cstore.init()
    conn = cstore._connect()  # noqa: SLF001
    try:
        order_count = conn.execute("SELECT COUNT(*) AS n FROM c_order").fetchone()["n"]
    finally:
        conn.close()

    return {
        "dry_run": False,
        "merchants_requested": len(merchant_specs),
        "merchants_ready": len(merchant_specs),
        "tenants_created": tenant_created,
        "merchant_products_created": catalog_created,
        "c_products_created": c_catalog_created,
        "consumers_requested": consumers,
        "consumers_ready": len(buyers),
        "orders_created": orders_created,
        "orders_advanced": orders_advanced,
        "messages_created": messages_created,
        "c_order_count": int(order_count),
        "accounts": {
            "password": PASSWORD,
            "merchants": [
                {
                    "merchant_id": spec.merchant_id,
                    "name": spec.name,
                    "username": spec.owner_username,
                    "owner": spec.owner_name,
                }
                for spec in merchant_specs
            ],
            "consumers": [
                {
                    "buyer_id": f"buyer_{int(user['id'])}",
                    "phone": user.get("contact") or "",
                    "nickname": user.get("display_name") or "",
                }
                for user in buyers
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merchants", type=int, default=6)
    parser.add_argument("--consumers", type=int, default=30)
    parser.add_argument("--apply", action="store_true", help="写入数据库；缺省只做 dry-run")
    args = parser.parse_args()
    result = seed(merchants=args.merchants, consumers=args.consumers, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.apply:
        out = ROOT / "var" / "simulation_accounts.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.get("accounts", {}), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"accounts: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
