"""C 端 mock 商品/模拟订单存储测试。"""
from __future__ import annotations

import csv
import io
import sqlite3

import pytest

from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _product_stock(c_store, product_id: str) -> int:
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        return conn.execute(
            "SELECT stock FROM c_product WHERE product_id = ?", (product_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_prepare_confirm_is_explicit_and_idempotent(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 2}])
    assert draft["status"] == "DRAFT"
    assert draft["total_amount"] == 598.0
    assert _product_stock(c_store, "P001") == 20

    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_order_001",
    )
    assert order["status"] == "CONFIRMED"
    assert order["total_amount"] == 598.0
    assert _product_stock(c_store, "P001") == 18

    repeated = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_order_001",
    )
    assert repeated["order_id"] == order["order_id"]
    assert _product_stock(c_store, "P001") == 18


def test_confirm_rejects_wrong_token(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P002", "quantity": 1}])
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.confirm_order("buyer_1", draft["order_id"], "wrong-token")
    assert exc.value.code == "INVALID_CONFIRMATION"
    assert _product_stock(c_store, "P002") == 15


def test_price_change_requires_reprepare(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        conn.execute("UPDATE c_product SET price = 99 WHERE product_id = 'P003'")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(c_store.CStoreError) as exc:
        c_store.confirm_order(
            "buyer_1",
            draft["order_id"],
            draft["confirmation_token"],
            request_id="req_c_price_changed",
        )
    assert exc.value.code == "ORDER_CHANGED"


def test_insufficient_stock_rejected(c_store):
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.prepare_order("buyer_1", [{"product_id": "P004", "quantity": 99}])
    assert exc.value.code == "INSUFFICIENT_STOCK"


def test_other_buyer_cannot_confirm(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P005", "quantity": 1}])
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.confirm_order("buyer_2", draft["order_id"], draft["confirmation_token"])
    assert exc.value.code == "ORDER_FORBIDDEN"


def test_companion_is_configurable_not_hardcoded_fish(c_store):
    companion = c_store.get_companion("buyer_1")
    assert companion["species"] == "digital_companion"
    assert companion["name"] == "小鱼"
    assert companion["user_nickname"] == ""

    updated = c_store.update_companion(
        "buyer_1",
        name="阿团",
        user_nickname="小满",
        species="cat",
        persona="calm",
        appearance="cat-v1",
    )
    assert updated["name"] == "阿团"
    assert updated["user_nickname"] == "小满"
    assert updated["species"] == "cat"
    assert c_store.get_companion("buyer_1")["appearance"] == "cat-v1"


def test_companion_name_and_nickname_validation(c_store):
    c_store.get_companion("buyer_1")

    with pytest.raises(c_store.CStoreError) as exc:
        c_store.update_companion("buyer_1", name="客服小鱼")
    assert exc.value.code == "INVALID_COMPANION_NAME"

    with pytest.raises(c_store.CStoreError) as exc:
        c_store.update_companion("buyer_1", user_nickname="主人")
    assert exc.value.code == "INVALID_USER_NICKNAME"

    with pytest.raises(c_store.CStoreError) as exc:
        c_store.update_companion("buyer_1", name="一二三四五六七八九十一二三")
    assert exc.value.code == "INVALID_COMPANION_NAME"

    # 清空昵称是合法状态：之后一律称呼"你"。
    cleared = c_store.update_companion("buyer_1", user_nickname="")
    assert cleared["user_nickname"] == ""


def test_confirm_rewards_companion_once(c_store):
    before = c_store.get_companion("buyer_1")
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_companion_reward_1",
    )
    after = c_store.get_companion("buyer_1")
    assert after["exp"] == before["exp"] + 10
    assert after["satiety"] == min(100, before["satiety"] + 5)

    c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_companion_reward_1",
    )
    repeated = c_store.get_companion("buyer_1")
    assert repeated["exp"] == after["exp"]
    assert repeated["satiety"] == after["satiety"]


def test_quote_links_order_and_consumes_audit(c_store):
    quote = c_store.create_quote(
        "buyer_1",
        "store_demo",
        {
            "quote_id": "quote_audit_1",
            "product_refs": [{"product_id": "P001", "title": "轻量跑鞋", "price": 299.0}],
            "policy_refs": [{"policy_id": "platform_full_reduce", "title": "满减活动"}],
        },
    )
    assert quote["status"] == "PENDING"

    draft = c_store.prepare_order("buyer_1", [], quote_id="quote_audit_1")
    assert draft["quote_id"] == "quote_audit_1"
    assert draft["original_amount"] == 299.0
    assert draft["discount_amount"] == 30.0
    assert draft["total_amount"] == 269.0
    assert draft["policy_ids"] == ["platform_full_reduce"]

    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_quote_audit_1",
    )
    assert order["quote_id"] == "quote_audit_1"
    assert order["policy_ids"] == ["platform_full_reduce"]
    assert c_store.get_quote("quote_audit_1", "buyer_1")["status"] == "CONSUMED"
    audit = c_store.list_orders("buyer_1")
    assert audit[0]["order_id"] == order["order_id"]
    assert audit[0]["quote_id"] == "quote_audit_1"
    assert all(item["order_id"].startswith("order_") for item in audit)


def test_cancel_quote_and_release_draft(c_store):
    c_store.create_quote(
        "buyer_1",
        "store_demo",
        {
            "quote_id": "quote_cancel_1",
            "product_refs": [{"product_id": "P001", "quantity": 1}],
            "policy_refs": [],
        },
    )
    draft = c_store.prepare_order("buyer_1", [], quote_id="quote_cancel_1")
    cancelled = c_store.cancel_order_draft("buyer_1", draft["order_id"])
    assert cancelled["status"] == "CANCELLED"
    assert c_store.get_quote("quote_cancel_1", "buyer_1")["status"] == "PENDING"

    again = c_store.prepare_order("buyer_1", [], quote_id="quote_cancel_1")
    assert again["total_amount"] == 299.0
    c_store.cancel_order_draft("buyer_1", again["order_id"])
    c_store.cancel_quote("quote_cancel_1", "buyer_1")
    assert c_store.get_quote("quote_cancel_1", "buyer_1")["status"] == "CANCELLED"


def test_app_messages_are_persisted_and_scoped(c_store):
    c_store.save_app_message("buyer_1", "companion", "user", "看看跑鞋")
    c_store.save_app_message(
        "buyer_1",
        "companion",
        "companion",
        "轻量跑鞋 299 元",
        {"quote_id": "quote_app_1"},
    )
    messages = c_store.list_app_messages("buyer_1", "companion")
    assert [m["role"] for m in messages] == ["user", "companion"]
    assert messages[1]["metadata"]["quote_id"] == "quote_app_1"
    assert c_store.list_app_messages("buyer_2", "companion") == []


def test_app_messages_pagination_and_clear(c_store):
    import time

    for index in range(4):
        c_store.save_app_message("buyer_1", "companion", "user", f"消息{index}")
        time.sleep(0.01)
    latest = c_store.list_app_messages("buyer_1", "companion", limit=2)
    assert [m["content"] for m in latest] == ["消息2", "消息3"]
    older = c_store.list_app_messages(
        "buyer_1",
        "companion",
        limit=2,
        before=latest[0]["created_at"],
    )
    assert [m["content"] for m in older] == ["消息0", "消息1"]
    assert c_store.clear_app_messages("buyer_1", "companion") == 4
    assert c_store.list_app_messages("buyer_1", "companion") == []


def test_admin_audit_lists_cross_buyer_orders_and_quotes(c_store):
    c_store.create_quote(
        "buyer_1",
        "store_demo",
        {
            "quote_id": "quote_admin_1",
            "product_refs": [{"product_id": "P001", "quantity": 1}],
            "policy_refs": [{"policy_id": "platform_full_reduce"}],
        },
    )
    draft = c_store.prepare_order("buyer_1", [], quote_id="quote_admin_1")
    c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_admin_audit_1",
    )
    c_store.save_app_message("buyer_2", "companion", "user", "另一买家的消息")
    c_store.create_quote(
        "buyer_2",
        "store_demo",
        {
            "quote_id": "quote_admin_2",
            "product_refs": [{"product_id": "P002", "quantity": 1}],
            "policy_refs": [],
        },
    )

    orders = c_store.list_all_orders()
    quotes = c_store.list_all_quotes()
    assert orders[0]["quote_id"] == "quote_admin_1"
    assert orders[0]["policy_ids"] == ["platform_full_reduce"]
    assert all(order["order_id"].startswith("order_") for order in orders)

    buyer_2_orders = c_store.list_all_orders(buyer_id="buyer_2")
    buyer_2_quotes = c_store.list_all_quotes(buyer_id="buyer_2")
    assert buyer_2_orders == []
    assert [quote["quote_id"] for quote in buyer_2_quotes] == ["quote_admin_2"]

    pending = c_store.list_all_quotes(status="PENDING")
    assert [quote["quote_id"] for quote in pending] == ["quote_admin_2"]


AUDIT_CSV_HEADER = [
    "order_id",
    "buyer_id",
    "total_amount",
    "original_amount",
    "discount_amount",
    "quote_id",
    "policy_ids",
    "confirmed_at",
]


def _parse_audit_csv(csv_text: str) -> tuple[list[str], list[list[str]]]:
    """CSV 必须是带 BOM 的 UTF-8，解析时先去掉 BOM 才能读到正确表头。"""
    assert csv_text.startswith("\ufeff")
    assert csv_text.encode("utf-8").startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
    return rows[0], rows[1:]


def _set_confirmed_at(c_store, order_id: str, value: str) -> None:
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        conn.execute("UPDATE c_order SET confirmed_at = ? WHERE order_id = ?", (value, order_id))
        conn.commit()
    finally:
        conn.close()


def test_audit_csv_export_reuses_audit_filters(c_store):
    """导出复用审计筛选：订单行、顺序、截断与 list_all_orders 完全一致。"""
    c_store.create_quote(
        "buyer_1",
        "store_demo",
        {
            "quote_id": "quote_export_1",
            "product_refs": [{"product_id": "P001", "quantity": 1}],
            "policy_refs": [
                {"policy_id": "platform_full_reduce", "title": "满减活动"},
                {"policy_id": "vip_free_shipping", "title": "会员包邮"},
            ],
        },
    )
    quote_draft = c_store.prepare_order("buyer_1", [], quote_id="quote_export_1")
    first = c_store.confirm_order(
        "buyer_1",
        quote_draft["order_id"],
        quote_draft["confirmation_token"],
        request_id="req_export_1",
    )

    second_draft = c_store.prepare_order("buyer_2", [{"product_id": "P002", "quantity": 1}])
    second = c_store.confirm_order(
        "buyer_2",
        second_draft["order_id"],
        second_draft["confirmation_token"],
        request_id="req_export_2",
    )
    # 固定确认时间，让日期筛选可以确定性断言（下单时间默认是 now）。
    _set_confirmed_at(c_store, first["order_id"], "2026-10-29T10:00:00+00:00")
    _set_confirmed_at(c_store, second["order_id"], "2026-10-28T09:30:00+00:00")

    header, rows = _parse_audit_csv(c_store.export_audit_orders_csv(limit=50))
    assert header == AUDIT_CSV_HEADER
    assert header == list(c_store.AUDIT_ORDER_CSV_FIELDS)

    all_orders = c_store.list_all_orders(limit=50)
    assert len(rows) == len(all_orders) == 2
    assert [row[0] for row in rows] == [order["order_id"] for order in all_orders]
    assert [row[7] for row in rows] == [order["confirmed_at"] for order in all_orders]

    # 每列的值与订单列表一致；policy_ids 用 ; 连接，quote_id 保留审计链。
    first_row = rows[0]
    assert first_row[1] == "buyer_1"
    assert first_row[2] == "269.00"
    assert first_row[3] == "299.00"
    assert first_row[4] == "30.00"
    assert first_row[5] == "quote_export_1"
    assert first_row[6] == "platform_full_reduce;vip_free_shipping"
    assert rows[1][1:7] == ["buyer_2", "199.00", "199.00", "0.00", "", ""]

    # 草稿不进入导出（与审计列表同口径：只导已确认订单）。
    c_store.prepare_order("buyer_2", [{"product_id": "P003", "quantity": 1}])
    _, rows_after_draft = _parse_audit_csv(c_store.export_audit_orders_csv(limit=50))
    assert len(rows_after_draft) == 2

    # buyer_id 筛选
    _, buyer_rows = _parse_audit_csv(c_store.export_audit_orders_csv(limit=50, buyer_id="buyer_1"))
    buyer_orders = c_store.list_all_orders(limit=50, buyer_id="buyer_1")
    assert [row[0] for row in buyer_rows] == [order["order_id"] for order in buyer_orders]
    assert len(buyer_rows) == 1

    # 自然日范围筛选（date_to 含当天 23:59:59）
    _, day_rows = _parse_audit_csv(
        c_store.export_audit_orders_csv(limit=50, date_from="2026-10-29", date_to="2026-10-29")
    )
    assert [row[0] for row in day_rows] == [first["order_id"]]
    day_orders = c_store.list_all_orders(
        limit=50, date_from="2026-10-29", date_to="2026-10-29"
    )
    assert [row[0] for row in day_rows] == [order["order_id"] for order in day_orders]

    # limit 生效且与列表同序
    _, limited_rows = _parse_audit_csv(c_store.export_audit_orders_csv(limit=1))
    assert [row[0] for row in limited_rows] == [
        order["order_id"] for order in c_store.list_all_orders(limit=1)
    ]
    assert len(limited_rows) == 1

    # status 按订单关联的报价状态过滤：first 的报价确认后是 CONSUMED，second 无 quote_id 被排除。
    _, consumed_rows = _parse_audit_csv(
        c_store.export_audit_orders_csv(limit=50, status="CONSUMED")
    )
    consumed_orders = c_store.list_all_orders(limit=50, status="CONSUMED")
    assert [row[0] for row in consumed_rows] == [first["order_id"]]
    assert [row[0] for row in consumed_rows] == [order["order_id"] for order in consumed_orders]
    # 没有关联 PENDING 报价的订单 → 导出只有表头，与列表同口径。
    _, pending_rows = _parse_audit_csv(c_store.export_audit_orders_csv(limit=50, status="PENDING"))
    assert pending_rows == []
    assert c_store.list_all_orders(limit=50, status="PENDING") == []


def _set_quote_status(c_store, quote_id: str, status: str) -> None:
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        conn.execute("UPDATE c_quote SET status = ? WHERE quote_id = ?", (status, quote_id))
        conn.commit()
    finally:
        conn.close()


def test_audit_status_filters_orders_by_linked_quote_status(c_store):
    """选 PENDING/CONSUMED 时订单按关联报价状态过滤；无 quote_id 订单被排除。"""
    # 订单 A：buyer_1 关联报价 quote_status_1（确认后 CONSUMED）。
    c_store.create_quote(
        "buyer_1",
        "store_demo",
        {
            "quote_id": "quote_status_1",
            "product_refs": [{"product_id": "P001", "quantity": 1}],
            "policy_refs": [{"policy_id": "platform_full_reduce"}],
        },
    )
    draft_a = c_store.prepare_order("buyer_1", [], quote_id="quote_status_1")
    order_a = c_store.confirm_order(
        "buyer_1", draft_a["order_id"], draft_a["confirmation_token"], request_id="req_status_a"
    )

    # 订单 B：buyer_2 直购，没有 quote_id，任何 status 过滤都不应返回它。
    draft_b = c_store.prepare_order("buyer_2", [{"product_id": "P002", "quantity": 1}])
    order_b = c_store.confirm_order(
        "buyer_2", draft_b["order_id"], draft_b["confirmation_token"], request_id="req_status_b"
    )

    # 订单 C：buyer_1 关联报价 quote_status_2。
    c_store.create_quote(
        "buyer_1",
        "store_demo",
        {
            "quote_id": "quote_status_2",
            "product_refs": [{"product_id": "P005", "quantity": 1}],
            "policy_refs": [],
        },
    )
    draft_c = c_store.prepare_order("buyer_1", [], quote_id="quote_status_2")
    order_c = c_store.confirm_order(
        "buyer_1", draft_c["order_id"], draft_c["confirmation_token"], request_id="req_status_c"
    )
    _set_confirmed_at(c_store, order_a["order_id"], "2026-10-29T10:00:00+00:00")
    _set_confirmed_at(c_store, order_b["order_id"], "2026-10-29T11:00:00+00:00")
    _set_confirmed_at(c_store, order_c["order_id"], "2026-10-28T09:00:00+00:00")

    def order_ids(**kwargs) -> list[str]:
        return [order["order_id"] for order in c_store.list_all_orders(**kwargs)]

    # 不传 status：三笔都返回（无 quote 的 B 也在）。
    assert order_ids() == [order_b["order_id"], order_a["order_id"], order_c["order_id"]]

    # 选 CONSUMED：只返回关联 CONSUMED 报价的 A/C，无 quote_id 的 B 被排除。
    assert order_ids(status="CONSUMED") == [order_a["order_id"], order_c["order_id"]]
    # limit 在 status 过滤之后截断（按 confirmed_at DESC）。
    assert order_ids(status="CONSUMED", limit=1) == [order_a["order_id"]]
    assert order_ids(status="PENDING") == []
    assert order_ids(status="CANCELLED") == []

    # 把 C 的关联报价改成 PENDING：PENDING 只返回 C，CONSUMED 只剩 A。
    _set_quote_status(c_store, "quote_status_2", "PENDING")
    assert order_ids(status="PENDING") == [order_c["order_id"]]
    assert order_ids(status="CONSUMED") == [order_a["order_id"]]
    assert order_ids(status="CANCELLED") == []
    # store 侧对大小写保持健壮（API 层另有严格校验）。
    assert order_ids(status="pending") == [order_c["order_id"]]

    # buyer / 日期过滤与 status 组合仍生效。
    assert order_ids(status="CONSUMED", buyer_id="buyer_1") == [order_a["order_id"]]
    assert order_ids(status="PENDING", buyer_id="buyer_1") == [order_c["order_id"]]
    assert order_ids(status="CONSUMED", buyer_id="buyer_2") == []
    assert order_ids(
        status="CONSUMED", date_from="2026-10-29", date_to="2026-10-29"
    ) == [order_a["order_id"]]
    assert order_ids(
        status="PENDING", date_from="2026-10-28", date_to="2026-10-28"
    ) == [order_c["order_id"]]
    assert order_ids(status="PENDING", date_from="2026-10-29", date_to="2026-10-29") == []

    # 导出与列表同口径：PENDING 只导 C，CONSUMED 只导 A。
    _, pending_csv = _parse_audit_csv(c_store.export_audit_orders_csv(status="PENDING"))
    assert [row[0] for row in pending_csv] == [order_c["order_id"]]
    assert [row[5] for row in pending_csv] == ["quote_status_2"]
    _, consumed_csv = _parse_audit_csv(c_store.export_audit_orders_csv(status="CONSUMED"))
    assert [row[0] for row in consumed_csv] == [order_a["order_id"]]
    # 无 quote 订单被排除：buyer_2 只有直购订单 B，带 status 导出为空。
    _, buyer_2_csv = _parse_audit_csv(
        c_store.export_audit_orders_csv(status="CANCELLED", buyer_id="buyer_2")
    )
    assert buyer_2_csv == []
    # 不传 status 的导出仍包含直购订单 B。
    _, all_csv = _parse_audit_csv(c_store.export_audit_orders_csv())
    assert len(all_csv) == 3


def test_audit_csv_export_empty_result_keeps_header(c_store):
    """无数据时仍返回表头，CSV 行数 = 1。"""
    header, rows = _parse_audit_csv(c_store.export_audit_orders_csv(buyer_id="buyer_404"))
    assert header == AUDIT_CSV_HEADER
    assert rows == []

