"""C 端模拟商品/订单存储（SQLite，第一版 mock）。

设计约束：
- 商品价格、库存、订单金额来自确定性存储，不由 LLM 生成。
- 订单创建必须经过 prepare → 用户确认 → confirm 两步。
- confirm 绑定 confirmation_token + 订单快照；内容变化后旧 token 失效。
- request_id 唯一，重复确认不会重复扣库存/重复生成订单。
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_demo.config import BASE_DIR

_DB_LOCK = threading.Lock()
_DB_PATH: Path | None = None


class CStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        raw = os.environ.get("QIANKE_C_END_DB") or str(Path(BASE_DIR) / "var" / "c_end_mock.sqlite")
        _DB_PATH = Path(raw)
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS c_product (
    product_id  TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       REAL NOT NULL CHECK (price >= 0),
    stock       INTEGER NOT NULL CHECK (stock >= 0),
    status      TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS c_order (
    order_id          TEXT PRIMARY KEY,
    buyer_id          TEXT NOT NULL,
    status            TEXT NOT NULL,
    total_amount      REAL NOT NULL,
    confirmation_hash TEXT,
    snapshot_json     TEXT NOT NULL,
    idempotency_key   TEXT UNIQUE,
    source_order_id   TEXT,
    created_at        TEXT NOT NULL,
    confirmed_at      TEXT
);

CREATE TABLE IF NOT EXISTS c_order_item (
    order_id   TEXT NOT NULL REFERENCES c_order(order_id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES c_product(product_id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL,
    PRIMARY KEY (order_id, product_id)
);
"""

_SEED = (
    ("P001", "m_demo", "轻量跑鞋", "运动", 299.0, 20),
    ("P002", "m_demo", "通勤双肩包", "箱包", 199.0, 15),
    ("P003", "m_demo", "保温杯", "生活", 89.0, 50),
    ("P004", "m_demo", "蓝牙耳机", "数码", 399.0, 12),
    ("P005", "m_demo", "运动 T 恤", "运动", 129.0, 30),
    ("P006", "m_demo", "防晒衣", "户外", 159.0, 18),
)


def init() -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(c_order)").fetchall()}
            if "source_order_id" not in columns:
                conn.execute("ALTER TABLE c_order ADD COLUMN source_order_id TEXT")
            count = conn.execute("SELECT COUNT(*) AS n FROM c_product").fetchone()["n"]
            if count == 0:
                conn.executemany(
                    "INSERT INTO c_product(product_id, merchant_id, title, category, price, stock) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    _SEED,
                )
            conn.commit()
        finally:
            conn.close()


def list_products(category: str | None = None, keyword: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    init()
    where = ["status = 'ACTIVE'"]
    params: list[Any] = []
    if category:
        where.append("category = ?")
        params.append(category)
    if keyword:
        where.append("(title LIKE ? OR category LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    params.append(max(1, min(int(limit), 50)))
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_product WHERE {' AND '.join(where)} ORDER BY price ASC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot(items: list[dict[str, Any]]) -> str:
    return json.dumps(items, ensure_ascii=False, sort_keys=True)


def _validate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        raise CStoreError("EMPTY_ITEMS", "订单至少需要一个商品")
    merged: dict[str, int] = {}
    for item in items:
        product_id = str(item.get("product_id") or "").strip()
        try:
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError):
            raise CStoreError("INVALID_QUANTITY", "商品数量必须是正整数") from None
        if not product_id or quantity <= 0:
            raise CStoreError("INVALID_QUANTITY", "商品 ID 和数量必须有效")
        merged[product_id] = merged.get(product_id, 0) + quantity
    return [{"product_id": pid, "quantity": qty} for pid, qty in merged.items()]


def prepare_order(buyer_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """生成待确认订单草稿；不扣库存。"""
    init()
    normalized = _validate_items(items)
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        products: list[dict[str, Any]] = []
        total = 0.0
        for item in normalized:
            row = conn.execute(
                "SELECT * FROM c_product WHERE product_id = ? AND status = 'ACTIVE'",
                (item["product_id"],),
            ).fetchone()
            if row is None:
                raise CStoreError("PRODUCT_NOT_FOUND", f"商品不存在或已下架：{item['product_id']}")
            if row["stock"] < item["quantity"]:
                raise CStoreError("INSUFFICIENT_STOCK", f"库存不足：{row['title']}")
            unit_price = float(row["price"])
            total += unit_price * item["quantity"]
            products.append({
                "product_id": row["product_id"],
                "title": row["title"],
                "quantity": item["quantity"],
                "unit_price": unit_price,
            })

        order_id = f"draft_{uuid.uuid4().hex[:16]}"
        token = secrets.token_urlsafe(24)
        snapshot = _snapshot(products)
        conn.execute(
            "INSERT INTO c_order(order_id, buyer_id, status, total_amount, confirmation_hash, "
            "snapshot_json, created_at) VALUES (?, ?, 'DRAFT', ?, ?, ?, ?)",
            (order_id, buyer_id, round(total, 2), _sha256(token), snapshot, _now()),
        )
        conn.executemany(
            "INSERT INTO c_order_item(order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            [(order_id, p["product_id"], p["quantity"], p["unit_price"]) for p in products],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "order_id": order_id,
        "status": "DRAFT",
        "buyer_id": buyer_id,
        "items": products,
        "total_amount": round(total, 2),
        "confirmation_token": token,
        "confirmation_version": 1,
        "message": "请确认订单内容后再提交；确认前不会扣库存。",
    }


def confirm_order(
    buyer_id: str,
    draft_id: str,
    confirmation_token: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """确认草稿并创建正式模拟订单；按 request_id 幂等。"""
    init()
    if not draft_id or not confirmation_token:
        raise CStoreError("INVALID_CONFIRMATION", "缺少订单或确认凭证")
    if not request_id:
        request_id = f"req_c_{uuid.uuid4().hex[:16]}"

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM c_order WHERE idempotency_key = ?",
            (request_id,),
        ).fetchone()
        if existing is not None:
            if existing["buyer_id"] != buyer_id or existing["source_order_id"] != draft_id:
                raise CStoreError("IDEMPOTENCY_CONFLICT", "request_id 已用于其他订单")
            return _order_payload(conn, existing)

        draft = conn.execute(
            "SELECT * FROM c_order WHERE order_id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise CStoreError("ORDER_NOT_FOUND", "订单草稿不存在")
        if draft["buyer_id"] != buyer_id:
            raise CStoreError("ORDER_FORBIDDEN", "不能确认其他用户的订单")
        if draft["status"] != "DRAFT":
            raise CStoreError("ORDER_NOT_DRAFT", "订单已经处理，不能重复确认")
        if draft["confirmation_hash"] != _sha256(confirmation_token):
            raise CStoreError("INVALID_CONFIRMATION", "确认凭证无效")

        product_rows = conn.execute(
            "SELECT * FROM c_product WHERE product_id IN "
            "(SELECT product_id FROM c_order_item WHERE order_id = ?)",
            (draft_id,),
        ).fetchall()
        current = {row["product_id"]: row for row in product_rows}
        expected = json.loads(draft["snapshot_json"])
        expected_by_id = {item["product_id"]: item for item in expected}

        for item in expected:
            row = current.get(item["product_id"])
            if row is None or row["status"] != "ACTIVE":
                raise CStoreError("ORDER_CHANGED", "订单商品已下架，请重新准备订单")
            if float(row["price"]) != float(item["unit_price"]):
                raise CStoreError("ORDER_CHANGED", "订单价格已变化，请重新准备并确认")
            if row["stock"] < item["quantity"]:
                raise CStoreError("INSUFFICIENT_STOCK", f"库存不足：{row['title']}")

        for item in expected:
            conn.execute(
                "UPDATE c_product SET stock = stock - ? WHERE product_id = ?",
                (item["quantity"], item["product_id"]),
            )

        order_id = "order_" + uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO c_order(order_id, buyer_id, status, total_amount, snapshot_json, "
            "idempotency_key, source_order_id, created_at, confirmed_at) "
            "VALUES (?, ?, 'CONFIRMED', ?, ?, ?, ?, ?, ?)",
            (order_id, buyer_id, draft["total_amount"], draft["snapshot_json"], request_id, draft_id, _now(), _now()),
        )
        conn.executemany(
            "INSERT INTO c_order_item(order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            [(order_id, item["product_id"], item["quantity"], item["unit_price"]) for item in expected],
        )
        # 草稿只标记终态，不重复占用 idempotency_key（唯一约束在正式订单上）。
        conn.execute(
            "UPDATE c_order SET status = 'CONFIRMED' WHERE order_id = ?",
            (draft_id,),
        )
        conn.commit()
        order = conn.execute("SELECT * FROM c_order WHERE order_id = ?", (order_id,)).fetchone()
        return _order_payload(conn, order)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _order_payload(conn: sqlite3.Connection, order: sqlite3.Row) -> dict[str, Any]:
    items = conn.execute(
        "SELECT product_id, quantity, unit_price FROM c_order_item WHERE order_id = ?",
        (order["order_id"],),
    ).fetchall()
    titles = {
        row["product_id"]: row["title"]
        for row in conn.execute(
            "SELECT product_id, title FROM c_product WHERE product_id IN "
            "(SELECT product_id FROM c_order_item WHERE order_id = ?)",
            (order["order_id"],),
        ).fetchall()
    }
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "buyer_id": order["buyer_id"],
        "total_amount": float(order["total_amount"]),
        "items": [
            {
                "product_id": item["product_id"],
                "title": titles.get(item["product_id"], ""),
                "quantity": item["quantity"],
                "unit_price": float(item["unit_price"]),
            }
            for item in items
        ],
        "idempotency_key": order["idempotency_key"],
        "source_order_id": order["source_order_id"],
        "created_at": order["created_at"],
        "confirmed_at": order["confirmed_at"],
    }


def get_order(order_id: str) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        order = conn.execute("SELECT * FROM c_order WHERE order_id = ?", (order_id,)).fetchone()
        return _order_payload(conn, order) if order is not None else None
    finally:
        conn.close()
