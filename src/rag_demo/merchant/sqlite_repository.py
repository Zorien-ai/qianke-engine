"""SQLite 实现的商家数据层（v1 默认 adapter）。

定位：**可替换的数据层默认实现**，不是真实 OMS 对接。
- 数据来自 ``data/merchant/*.csv`` 种子；``QIANKE_MERCHANT_DB`` 指定 SQLite 文件，
  默认 ``<仓库根>/var/merchant_v1.sqlite``（``var/`` 已被 .gitignore 忽略）。
- 表名统一加 ``m_`` 前缀，避免与既有 c_end/b_end 的 mock 表混在一起。
- 金额列存 TEXT（十进制字符串），读写都走 ``Decimal``，不经过 float。
- 所有查询**参数化**、所有列表查询统一过 ``clamp_limit``；多租户查询缺 merchant_id
  时失败关闭（``MerchantDataError``），绝不退化成全表读。

未来接真实 OMS/PG 时：实现 ``MerchantRepository`` 协议并把工厂注册到
:mod:`rag_demo.merchant.factory` 即可替换本文件，本类不需要改动。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from . import seeds
from .errors import MerchantDataError, MerchantUnavailableError
from .limits import DEFAULT_LIST_LIMIT, clamp_limit
from .models import (
    DEFAULT_CURRENCY,
    Inventory,
    Order,
    OrderItem,
    Product,
    SKU,
    WarehouseStock,
    money_text,
)

# 仓库根：merchant/sqlite_repository.py -> merchant -> rag_demo -> src -> 根
_ROOT_DIR = Path(__file__).resolve().parents[3]

DEFAULT_DB_FILENAME = "merchant_v1.sqlite"
_ENV_DB = "QIANKE_MERCHANT_DB"
_ENV_SEED_DIR = "QIANKE_MERCHANT_SEED_DIR"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS m_product (
    product_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    brand       TEXT,
    status      TEXT NOT NULL,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_m_product_merchant ON m_product (merchant_id);

CREATE TABLE IF NOT EXISTS m_sku (
    sku         TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    product_id  TEXT NOT NULL REFERENCES m_product (product_id),
    spec        TEXT NOT NULL,
    price       TEXT NOT NULL,
    status      TEXT NOT NULL,
    barcode     TEXT
);

CREATE INDEX IF NOT EXISTS idx_m_sku_merchant ON m_sku (merchant_id);
CREATE INDEX IF NOT EXISTS idx_m_sku_product ON m_sku (product_id);

CREATE TABLE IF NOT EXISTS m_inventory (
    sku           TEXT NOT NULL REFERENCES m_sku (sku),
    warehouse_id  TEXT NOT NULL,
    merchant_id   TEXT NOT NULL,
    available_qty INTEGER NOT NULL,
    reserved_qty  INTEGER NOT NULL,
    safety_stock  INTEGER NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (sku, warehouse_id)
);

CREATE INDEX IF NOT EXISTS idx_m_inventory_merchant ON m_inventory (merchant_id);

CREATE TABLE IF NOT EXISTS m_order (
    order_id     TEXT PRIMARY KEY,
    merchant_id  TEXT NOT NULL,
    buyer_id     TEXT NOT NULL,
    status       TEXT NOT NULL,
    total_amount TEXT NOT NULL,
    currency     TEXT NOT NULL,
    channel      TEXT,
    created_at   TEXT NOT NULL,
    paid_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_m_order_merchant ON m_order (merchant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_m_order_buyer ON m_order (buyer_id);

CREATE TABLE IF NOT EXISTS m_order_item (
    order_id    TEXT NOT NULL REFERENCES m_order (order_id) ON DELETE CASCADE,
    line_no     INTEGER NOT NULL,
    sku         TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    title       TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    unit_price  TEXT NOT NULL,
    line_amount TEXT NOT NULL,
    PRIMARY KEY (order_id, line_no)
);

CREATE TABLE IF NOT EXISTS m_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    """默认 SQLite 文件：``QIANKE_MERCHANT_DB`` 覆盖，否则 ``<仓库根>/var/merchant_v1.sqlite``。"""
    raw = (os.environ.get(_ENV_DB) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _ROOT_DIR / "var" / DEFAULT_DB_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class SqliteMerchantRepository:
    """商家数据层的 SQLite 只读实现（初始化时按种子数据落库）。"""

    backend = "sqlite"

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        seed: bool = True,
        seed_dir: str | Path | None = None,
    ) -> None:
        self._db_path = Path(db_path).expanduser() if db_path else default_db_path()
        self._seed_dir = Path(seed_dir).expanduser() if seed_dir else seeds.default_seed_dir()
        self._lock = threading.RLock()
        self._closed = False
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MerchantUnavailableError(f"无法创建商家数据库目录（{self._db_path.parent}）: {exc}") from exc

        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
        if seed:
            self._ensure_seeded()

    # ---------- 连接 / 生命周期 ----------
    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def seed_dir(self) -> Path:
        return self._seed_dir

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise MerchantUnavailableError("商家数据层已关闭（close() 之后不能再查询）")

    def close(self) -> None:
        """关闭数据层标记（每次查询独立开连接，这里主要防止误用已释放实例）。"""
        self._closed = True

    def __enter__(self) -> "SqliteMerchantRepository":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------- 种子初始化 ----------
    def _ensure_seeded(self) -> None:
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM m_product").fetchone()[0]
        if existing == 0:
            self.seed()

    def seed(self, *, force: bool = False) -> dict[str, int]:
        """按种子文件初始化/重置数据；返回各表行数（全部来自实际写入结果）。

        - 默认幂等：库中已有商品时直接返回现有计数，不重复插入；
        - ``force=True``：清空 m_* 业务表后按种子重灌（用于本地重置，不供 API 调用）。
        """
        self._ensure_open()
        data = seeds.load_seed_data(self._seed_dir)
        with self._lock, self._connect() as conn:
            if not force:
                existing = conn.execute("SELECT COUNT(*) FROM m_product").fetchone()[0]
                if existing > 0:
                    return self._counts(conn)
            # 子表先删（foreign_keys=ON，顺序不能反）
            conn.execute("DELETE FROM m_order_item")
            conn.execute("DELETE FROM m_order")
            conn.execute("DELETE FROM m_inventory")
            conn.execute("DELETE FROM m_sku")
            conn.execute("DELETE FROM m_product")
            self._insert_seed(conn, data)
            meta = {
                "seed_version": "v1",
                "seed_dir": str(self._seed_dir),
                "seeded_at": _now(),
                "seed_counts": json.dumps(data.counts(), ensure_ascii=False),
                "seed_files_sha256": json.dumps(data.file_sha256, ensure_ascii=False),
            }
            for key, value in meta.items():
                conn.execute(
                    "INSERT INTO m_meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            conn.commit()
            return self._counts(conn)

    def _insert_seed(self, conn: sqlite3.Connection, data: seeds.SeedData) -> None:
        conn.executemany(
            "INSERT INTO m_product "
            "(product_id, merchant_id, title, category, brand, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    p.product_id, p.merchant_id, p.title, p.category,
                    p.brand, p.status, p.created_at,
                )
                for p in data.products
            ],
        )
        conn.executemany(
            "INSERT INTO m_sku "
            "(sku, merchant_id, product_id, spec, price, status, barcode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s.sku, s.merchant_id, s.product_id, s.spec,
                    money_text(s.price), s.status, s.barcode,
                )
                for s in data.skus
            ],
        )
        conn.executemany(
            "INSERT INTO m_inventory "
            "(sku, warehouse_id, merchant_id, available_qty, reserved_qty, safety_stock, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r.sku, r.warehouse_id, r.merchant_id, r.available_qty,
                    r.reserved_qty, r.safety_stock, r.updated_at,
                )
                for r in data.inventory_records
            ],
        )
        conn.executemany(
            "INSERT INTO m_order "
            "(order_id, merchant_id, buyer_id, status, total_amount, currency, channel, created_at, paid_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    o.order_id, o.merchant_id, o.buyer_id, o.status,
                    money_text(o.total_amount), o.currency, o.channel,
                    o.created_at, o.paid_at,
                )
                for o in data.orders
            ],
        )
        rows = []
        for order in data.orders:
            for line_no, item in enumerate(order.items, start=1):
                rows.append(
                    (
                        order.order_id, line_no, item.sku, item.product_id, item.title,
                        item.quantity, money_text(item.unit_price),
                        money_text(item.line_amount),
                    )
                )
        conn.executemany(
            "INSERT INTO m_order_item "
            "(order_id, line_no, sku, product_id, title, quantity, unit_price, line_amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    # ---------- 统计 ----------
    def _counts(self, conn: sqlite3.Connection) -> dict[str, int]:
        return {
            "products": int(conn.execute("SELECT COUNT(*) FROM m_product").fetchone()[0]),
            "skus": int(conn.execute("SELECT COUNT(*) FROM m_sku").fetchone()[0]),
            "inventory_records": int(
                conn.execute("SELECT COUNT(*) FROM m_inventory").fetchone()[0]
            ),
            "orders": int(conn.execute("SELECT COUNT(*) FROM m_order").fetchone()[0]),
            "order_items": int(
                conn.execute("SELECT COUNT(*) FROM m_order_item").fetchone()[0]
            ),
        }

    def stats(self) -> dict[str, int]:
        """各表行数（诊断/测试用，不涉及业务逻辑）。"""
        self._ensure_open()
        with self._lock, self._connect() as conn:
            return self._counts(conn)

    def describe(self) -> dict[str, Any]:
        """后端自描述：backend / 位置 / 规模 / 种子元信息。"""
        self._ensure_open()
        with self._lock, self._connect() as conn:
            counts = self._counts(conn)
            meta_rows = conn.execute("SELECT key, value FROM m_meta").fetchall()
        meta = {row["key"]: row["value"] for row in meta_rows}
        return {
            "backend": self.backend,
            "db_path": str(self._db_path),
            "seed_dir": str(self._seed_dir),
            "counts": counts,
            "seed": {
                "seed_version": meta.get("seed_version"),
                "seeded_at": meta.get("seeded_at"),
            },
        }

    # ---------- 商品 ----------
    def list_products(
        self,
        merchant_id: str,
        keyword: str | None = None,
        limit: int | None = DEFAULT_LIST_LIMIT,
    ) -> list[Product]:
        """按商家列商品；keyword 对标题/类目/品牌做大小写不敏感的子串匹配。"""
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        bounded = clamp_limit(limit)

        sql = (
            "SELECT product_id, merchant_id, title, category, brand, status, created_at "
            "FROM m_product WHERE merchant_id = ?"
        )
        params: list[Any] = [merchant]
        needle = _clean_optional(keyword)
        if needle:
            pattern = f"%{_escape_like(needle.lower())}%"
            sql += (
                " AND (lower(title) LIKE ? ESCAPE '\\'"
                " OR lower(category) LIKE ? ESCAPE '\\'"
                " OR lower(COALESCE(brand, '')) LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY product_id ASC LIMIT ?"
        params.append(bounded)

        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._product_from_row(row) for row in rows]

    def get_product_sku(self, sku: str, *, merchant_id: str | None = None) -> SKU | None:
        """按 SKU 取规格；传 merchant_id 时同时校验租户归属。"""
        self._ensure_open()
        sku_id = _clean_optional(sku)
        if not sku_id:
            return None
        sql = (
            "SELECT sku, merchant_id, product_id, spec, price, status, barcode "
            "FROM m_sku WHERE sku = ?"
        )
        params: list[Any] = [sku_id]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = ?"
            params.append(merchant)
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._sku_from_row(row) if row is not None else None

    def list_product_skus(
        self, product_id: str, *, merchant_id: str | None = None
    ) -> list[SKU]:
        """列出一个商品下的全部 SKU（按 SKU 升序）。"""
        self._ensure_open()
        product = _clean_optional(product_id)
        if not product:
            return []
        sql = (
            "SELECT sku, merchant_id, product_id, spec, price, status, barcode "
            "FROM m_sku WHERE product_id = ?"
        )
        params: list[Any] = [product]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = ?"
            params.append(merchant)
        sql += " ORDER BY sku ASC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._sku_from_row(row) for row in rows]

    # ---------- 库存 ----------
    def get_inventory(self, sku: str, *, merchant_id: str | None = None) -> Inventory | None:
        """SKU 的跨仓库存汇总；没有库存记录或租户不匹配返回 None。"""
        self._ensure_open()
        sku_id = _clean_optional(sku)
        if not sku_id:
            return None
        sql = (
            "SELECT sku, warehouse_id, merchant_id, available_qty, reserved_qty, "
            "safety_stock, updated_at FROM m_inventory WHERE sku = ?"
        )
        params: list[Any] = [sku_id]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = ?"
            params.append(merchant)
        sql += " ORDER BY warehouse_id ASC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        if not rows:
            return None
        return Inventory(
            merchant_id=str(rows[0]["merchant_id"]),
            sku=str(rows[0]["sku"]),
            warehouses=tuple(
                WarehouseStock(
                    warehouse_id=str(row["warehouse_id"]),
                    available_qty=int(row["available_qty"]),
                    reserved_qty=int(row["reserved_qty"]),
                    safety_stock=int(row["safety_stock"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in rows
            ),
        )

    # ---------- 订单 ----------
    def list_orders(
        self,
        merchant_id: str,
        buyer_id: str | None = None,
        status: str | None = None,
        limit: int | None = DEFAULT_LIST_LIMIT,
    ) -> list[Order]:
        """按商家列订单（可再按买家/状态过滤），按创建时间倒序。"""
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        bounded = clamp_limit(limit)

        sql = (
            "SELECT order_id, merchant_id, buyer_id, status, total_amount, currency, "
            "channel, created_at, paid_at FROM m_order WHERE merchant_id = ?"
        )
        params: list[Any] = [merchant]
        buyer = _clean_optional(buyer_id)
        if buyer is not None:
            sql += " AND buyer_id = ?"
            params.append(buyer)
        status_value = _clean_optional(status)
        if status_value is not None:
            sql += " AND status = ?"
            params.append(status_value.upper())
        sql += " ORDER BY created_at DESC, order_id DESC LIMIT ?"
        params.append(bounded)

        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return self._hydrate_orders(conn, rows)

    def get_order(
        self,
        order_id: str,
        *,
        merchant_id: str | None = None,
        buyer_id: str | None = None,
    ) -> Order | None:
        """按订单号取订单；传 merchant_id / buyer_id 时同时校验作用域。"""
        self._ensure_open()
        order = _clean_optional(order_id)
        if not order:
            return None
        sql = (
            "SELECT order_id, merchant_id, buyer_id, status, total_amount, currency, "
            "channel, created_at, paid_at FROM m_order WHERE order_id = ?"
        )
        params: list[Any] = [order]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = ?"
            params.append(merchant)
        buyer = _clean_optional(buyer_id)
        if buyer is not None:
            sql += " AND buyer_id = ?"
            params.append(buyer)
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            if row is None:
                return None
            hydrated = self._hydrate_orders(conn, [row])
        return hydrated[0] if hydrated else None

    # ---------- 行 → 模型 ----------
    @staticmethod
    def _require_merchant(merchant_id: str | None) -> str:
        merchant = _clean_optional(merchant_id)
        if merchant is None:
            # 多租户数据层：缺商家 = 想读全表，直接失败关闭（不是返回空列表）
            raise MerchantDataError(
                "merchant_id 不能为空：商家数据查询必须显式指定租户，禁止跨租户/全表读取"
            )
        return merchant

    @staticmethod
    def _product_from_row(row: sqlite3.Row) -> Product:
        return Product(
            merchant_id=str(row["merchant_id"]),
            product_id=str(row["product_id"]),
            title=str(row["title"]),
            category=str(row["category"]),
            brand=row["brand"],
            status=str(row["status"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _sku_from_row(row: sqlite3.Row) -> SKU:
        return SKU(
            merchant_id=str(row["merchant_id"]),
            sku=str(row["sku"]),
            product_id=str(row["product_id"]),
            spec=str(row["spec"]),
            price=_as_decimal(row["price"]),
            status=str(row["status"]),
            barcode=row["barcode"],
        )

    def _hydrate_orders(
        self, conn: sqlite3.Connection, order_rows: list[sqlite3.Row]
    ) -> list[Order]:
        """批量补订单行（一次 IN 查询，避免 N+1）。"""
        if not order_rows:
            return []
        order_ids = [str(row["order_id"]) for row in order_rows]
        placeholders = ", ".join("?" for _ in order_ids)
        item_rows = conn.execute(
            "SELECT order_id, sku, product_id, title, quantity, unit_price, line_amount "
            f"FROM m_order_item WHERE order_id IN ({placeholders}) "
            "ORDER BY order_id ASC, line_no ASC",
            order_ids,
        ).fetchall()
        items_by_order: dict[str, list[OrderItem]] = {}
        for row in item_rows:
            items_by_order.setdefault(str(row["order_id"]), []).append(
                OrderItem(
                    sku=str(row["sku"]),
                    product_id=str(row["product_id"]),
                    title=str(row["title"]),
                    quantity=int(row["quantity"]),
                    unit_price=_as_decimal(row["unit_price"]),
                    line_amount=_as_decimal(row["line_amount"]),
                )
            )
        orders: list[Order] = []
        for row in order_rows:
            order_id = str(row["order_id"])
            orders.append(
                Order(
                    merchant_id=str(row["merchant_id"]),
                    order_id=order_id,
                    buyer_id=str(row["buyer_id"]),
                    status=str(row["status"]),
                    total_amount=_as_decimal(row["total_amount"]),
                    currency=str(row["currency"] or DEFAULT_CURRENCY),
                    channel=row["channel"],
                    created_at=str(row["created_at"]),
                    paid_at=row["paid_at"],
                    items=tuple(items_by_order.get(order_id, ())),
                )
            )
        return orders


def _escape_like(term: str) -> str:
    """转义 LIKE 通配符：用户关键词里的 % / _ 不应被当成通配（与 ESCAPE '\\' 配合）。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "DEFAULT_DB_FILENAME",
    "SqliteMerchantRepository",
    "default_db_path",
]
