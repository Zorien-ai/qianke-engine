"""SQLite 实现的商家数据层（v1 默认 adapter：只读查询 + 库存预占/订单写入）。

定位：**可替换的数据层默认实现**，不是真实 OMS 对接。
- 数据来自 ``data/merchant/*.csv`` 种子；``QIANKE_MERCHANT_DB`` 指定 SQLite 文件，
  默认 ``<仓库根>/var/merchant_v1.sqlite``（``var/`` 已被 .gitignore 忽略）。
- 表名统一加 ``m_`` 前缀，避免与既有 c_end/b_end 的 mock 表混在一起。
- 金额列存 TEXT（十进制字符串），读写都走 ``Decimal``，不经过 float。
- 所有查询**参数化**、所有列表查询统一过 ``clamp_limit``；多租户查询缺 merchant_id
  时失败关闭（``MerchantDataError``），绝不退化成全表读。
- 写操作（``reserve_inventory`` / ``commit_reservation`` / ``release_reservation`` /
  ``create_order``）全部走 ``BEGIN IMMEDIATE`` 事务：库存扣减/恢复与预占记录同事务，
  幂等、参数化、租户必填；库存不足等异常整体回滚。**这不是真实 OMS 写通道**。

未来接真实 OMS/PG 时：实现 ``MerchantRepository``（只读）与
``MerchantWriteRepository``（写）两个协议并把工厂注册到
:mod:`rag_demo.merchant.factory` 即可替换本文件，本类不需要改动。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from . import seeds
from .errors import (
    MerchantConflictError,
    MerchantDataError,
    MerchantExpiredError,
    MerchantInternalError,
    MerchantInvalidError,
    MerchantNotFoundError,
    MerchantStockError,
    MerchantUnavailableError,
)
from .limits import DEFAULT_LIST_LIMIT, clamp_limit
from .models import (
    DEFAULT_CURRENCY,
    ORDER_STATUS_CREATED,
    PRODUCT_STATUS_ACTIVE,
    RESERVATION_STATUS_COMMITTED,
    RESERVATION_STATUS_EXPIRED,
    RESERVATION_STATUS_RELEASED,
    RESERVATION_STATUS_RESERVED,
    Inventory,
    Order,
    OrderItem,
    Product,
    Reservation,
    ReservationAllocation,
    ReservationItem,
    SKU,
    WarehouseStock,
    money_text,
)

# 仓库根：merchant/sqlite_repository.py -> merchant -> rag_demo -> src -> 根
_ROOT_DIR = Path(__file__).resolve().parents[3]

DEFAULT_DB_FILENAME = "merchant_v1.sqlite"
_ENV_DB = "QIANKE_MERCHANT_DB"
_ENV_SEED_DIR = "QIANKE_MERCHANT_SEED_DIR"

# 写操作边界（预占 TTL / 单次写行数上限）；校验函数在模块底部
DEFAULT_RESERVATION_TTL_SECONDS = 900
MAX_RESERVATION_TTL_SECONDS = 7 * 24 * 3600  # 预占最多保留 7 天
MAX_WRITE_ITEMS = 50                          # 单次预占/订单最多 50 行

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
    paid_at      TEXT,
    source_ref   TEXT
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

-- 库存预占（task-43）：
--   items_json 同时存「请求行」与「实际扣减的仓库明细(allocations)」，
--   release / commit 必须按 allocations 精确回滚，不能重新按当前库存猜。
CREATE TABLE IF NOT EXISTS m_reservation (
    reservation_id TEXT PRIMARY KEY,
    merchant_id    TEXT NOT NULL,
    buyer_id       TEXT,
    status         TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    items_json     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    order_id       TEXT
);

CREATE INDEX IF NOT EXISTS idx_m_reservation_merchant
    ON m_reservation (merchant_id, status);
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
    """商家数据层的 SQLite 实现（初始化时按种子数据落库；读查询 + 库存预占/订单写入）。"""

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
            self._migrate_schema(conn)
            conn.commit()
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

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """写事务：``BEGIN IMMEDIATE`` 立刻拿写锁，异常整体回滚。

        为什么不用 ``_connect`` + 隐式事务：
        - 预占要「先查库存、再按仓库扣减、再写 reservation」，任何一步失败都必须整体回滚，
          不能留下「库存扣了但 reservation 没写」的中间态；
        - ``BEGIN IMMEDIATE`` 让并发写串行化（SQLite 只有单写者），配合 10s busy timeout，
          避免两个预占同时读到同一份 available 后都判定「够用」而超卖。

        ``isolation_level=None`` 关闭 sqlite3 模块的隐式事务，由我们显式控制
        BEGIN/COMMIT/ROLLBACK；连接用完即关，不跨线程复用。
        """
        conn = sqlite3.connect(
            str(self._db_path), timeout=10.0, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass  # 事务可能已经因错误自动回滚；不要掩盖原始异常
            raise
        finally:
            conn.close()

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection) -> None:
        """轻量迁移：``CREATE TABLE IF NOT EXISTS`` 不会给**已存在**的表补列。

        老库（v1 已上线/本地 var 库）需要补 ``m_order.source_ref``；
        新库在建表时已包含该列，这里的 PRAGMA 检查是幂等的。
        """
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(m_order)")}
        if "source_ref" not in columns:
            conn.execute("ALTER TABLE m_order ADD COLUMN source_ref TEXT")

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
            # 子表先删（foreign_keys=ON，顺序不能反）；预占记录随数据一起重置
            conn.execute("DELETE FROM m_reservation")
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
        """后端自描述：backend / 位置 / 规模 / 种子元信息 / 写能力。"""
        self._ensure_open()
        with self._lock, self._connect() as conn:
            counts = self._counts(conn)
            reservations = int(
                conn.execute("SELECT COUNT(*) FROM m_reservation").fetchone()[0]
            )
            meta_rows = conn.execute("SELECT key, value FROM m_meta").fetchall()
        meta = {row["key"]: row["value"] for row in meta_rows}
        return {
            "backend": self.backend,
            "db_path": str(self._db_path),
            "seed_dir": str(self._seed_dir),
            # counts 保持 v1 口径（种子实体）；预占数量单独给出，避免破坏既有调用方断言
            "counts": counts,
            "reservations": reservations,
            "write_capable": True,
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
            "channel, created_at, paid_at, source_ref FROM m_order WHERE merchant_id = ?"
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
            "channel, created_at, paid_at, source_ref FROM m_order WHERE order_id = ?"
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

    # ---------- 写操作：库存预占 / 订单写入（task-43） ----------
    def reserve_inventory(
        self,
        merchant_id: str,
        reservation_id: str,
        items: list[dict[str, Any]],
        ttl_seconds: int = DEFAULT_RESERVATION_TTL_SECONDS,
        *,
        buyer_id: str | None = None,
    ) -> Reservation:
        """按当前库存预占（available 扣减、reserved 增加），库存不足失败关闭。

        幂等语义：
        - 同 ``reservation_id`` + 同 payload → 直接返回已存在的预占，**不重复扣库存**；
        - 同 id + 不同 payload → ``MERCHANT_CONFLICT``（不能悄悄改成另一笔预占）；
        - 已释放/已提交的 id 不可复用（``MERCHANT_CONFLICT``）；
        - 同 id 的 RESERVED 预占已过期 → 先恢复旧库存，再按新请求重新预占
          （过期预占已不成立，复用 id 不会造成双重扣减）。
        """
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        reservation = _required_text(reservation_id, "reservation_id")
        buyer = _clean_optional(buyer_id)
        ttl = _normalize_ttl(ttl_seconds)
        requested = _normalize_write_items(items)

        with self._lock, self._transaction() as conn:
            lines = self._resolve_write_lines(conn, merchant, requested)
            existing_row = conn.execute(
                "SELECT * FROM m_reservation WHERE reservation_id = ?", (reservation,)
            ).fetchone()
            now = _now()

            if existing_row is not None:
                existing = self._reservation_from_row(existing_row)
                if existing.merchant_id != merchant:
                    # 防跨租户探测：不说明该 id 属于谁，也不返回对方数据
                    raise MerchantConflictError(
                        f"reservation_id 已被占用: {reservation}"
                    )
                if existing.status == RESERVATION_STATUS_RESERVED:
                    if not _is_expired(existing.expires_at, now):
                        if self._reservation_matches(existing, lines, buyer):
                            return existing  # 幂等重放：不再扣库存
                        raise MerchantConflictError(
                            "reservation_id 已被不同的预占请求使用；请使用新的 reservation_id"
                        )
                    # 过期复用：先恢复旧预占，再按新请求重新扣减
                    self._restore_allocations(conn, existing, now)
                    allocations = self._allocate_stock(conn, merchant, lines, now)
                    expires_at = _future_iso(ttl)
                    conn.execute(
                        "UPDATE m_reservation SET buyer_id = ?, status = ?, expires_at = ?, "
                        "items_json = ?, created_at = ?, updated_at = ?, order_id = NULL "
                        "WHERE reservation_id = ? AND merchant_id = ?",
                        (
                            buyer,
                            RESERVATION_STATUS_RESERVED,
                            expires_at,
                            _reservation_payload_json(lines, allocations),
                            now,
                            now,
                            reservation,
                            merchant,
                        ),
                    )
                    return self._require_reservation_row(conn, reservation)
                raise MerchantConflictError(
                    f"reservation 已处于终态 {existing.status}，不能复用；"
                    f"请使用新的 reservation_id"
                )

            allocations = self._allocate_stock(conn, merchant, lines, now)
            expires_at = _future_iso(ttl)
            conn.execute(
                "INSERT INTO m_reservation "
                "(reservation_id, merchant_id, buyer_id, status, expires_at, items_json, "
                " created_at, updated_at, order_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    reservation,
                    merchant,
                    buyer,
                    RESERVATION_STATUS_RESERVED,
                    expires_at,
                    _reservation_payload_json(lines, allocations),
                    now,
                    now,
                ),
            )
            return self._require_reservation_row(conn, reservation)

    def commit_reservation(
        self,
        merchant_id: str,
        reservation_id: str,
        order_id: str | None = None,
    ) -> Reservation:
        """把预占提交为订单占用：available 保持扣减、reserved 转出；重复提交幂等。"""
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        reservation = _required_text(reservation_id, "reservation_id")
        order = _clean_optional(order_id)
        if order is not None:
            order = _required_text(order, "order_id")

        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM m_reservation WHERE reservation_id = ?", (reservation,)
            ).fetchone()
            if row is None:
                raise MerchantNotFoundError(f"预占不存在: {reservation}")
            existing = self._reservation_from_row(row)
            if existing.merchant_id != merchant:
                # 租户隔离：其他商家的预占一律按「不存在」处理，不泄露存在性
                raise MerchantNotFoundError(f"预占不存在: {reservation}")

            now = _now()
            if existing.status == RESERVATION_STATUS_COMMITTED:
                if order is None or existing.order_id == order:
                    return existing  # 幂等重放：不重复转库存
                raise MerchantConflictError(
                    f"预占已提交为订单 {existing.order_id}，不能重复提交为其他订单"
                )
            if existing.status == RESERVATION_STATUS_RELEASED:
                raise MerchantConflictError("预占已释放，不能提交")
            if existing.status == RESERVATION_STATUS_EXPIRED:
                raise MerchantExpiredError("预占已过期，不能提交；请重新预占")
            if existing.status != RESERVATION_STATUS_RESERVED:
                raise MerchantInternalError(
                    f"预占状态非法: {existing.status!r}（reservation={reservation}）"
                )
            if _is_expired(existing.expires_at, now):
                # 过期：把旧预占的库存还回去并标记 EXPIRED。注意**不能在这里直接 raise**：
                # 异常会触发事务回滚，库存恢复就白做了。先把释放写入同一事务提交，
                # 出了 with 再抛结构化错误，调用方据此重新预占。
                self._restore_allocations(conn, existing, now)
                conn.execute(
                    "UPDATE m_reservation SET status = ?, updated_at = ? WHERE reservation_id = ?",
                    (RESERVATION_STATUS_EXPIRED, now, reservation),
                )
            else:
                self._consume_allocations(conn, existing, now)
                conn.execute(
                    "UPDATE m_reservation SET status = ?, order_id = ?, updated_at = ? "
                    "WHERE reservation_id = ? AND merchant_id = ?",
                    (RESERVATION_STATUS_COMMITTED, order, now, reservation, merchant),
                )
                return self._require_reservation_row(conn, reservation)

        # 事务已提交：过期预占的库存已释放，再向调用方报“过期”
        raise MerchantExpiredError("预占已过期，库存已释放；请重新预占后再提交")

    def release_reservation(self, merchant_id: str, reservation_id: str) -> Reservation:
        """释放预占并恢复库存；重复释放幂等；已提交的预占拒绝释放。"""
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        reservation = _required_text(reservation_id, "reservation_id")

        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM m_reservation WHERE reservation_id = ?", (reservation,)
            ).fetchone()
            if row is None:
                raise MerchantNotFoundError(f"预占不存在: {reservation}")
            existing = self._reservation_from_row(row)
            if existing.merchant_id != merchant:
                raise MerchantNotFoundError(f"预占不存在: {reservation}")

            now = _now()
            if existing.status in (
                RESERVATION_STATUS_RELEASED,
                RESERVATION_STATUS_EXPIRED,
            ):
                return existing  # 幂等：终态直接返回，绝不二次恢复库存
            if existing.status == RESERVATION_STATUS_COMMITTED:
                raise MerchantConflictError("预占已提交为订单，不能释放")
            if existing.status != RESERVATION_STATUS_RESERVED:
                raise MerchantInternalError(
                    f"预占状态非法: {existing.status!r}（reservation={reservation}）"
                )

            # 过期预占释放时库存要还回去，但状态记为 EXPIRED（不是 RELEASED）
            final_status = (
                RESERVATION_STATUS_EXPIRED
                if _is_expired(existing.expires_at, now)
                else RESERVATION_STATUS_RELEASED
            )
            self._restore_allocations(conn, existing, now)
            conn.execute(
                "UPDATE m_reservation SET status = ?, updated_at = ? "
                "WHERE reservation_id = ? AND merchant_id = ?",
                (final_status, now, reservation, merchant),
            )
            return self._require_reservation_row(conn, reservation)

    def create_order(
        self,
        merchant_id: str,
        order_id: str,
        buyer_id: str,
        items: list[dict[str, Any]],
        total_amount: Any,
        source_ref: str | None = None,
    ) -> Order:
        """幂等写入订单（同 order_id 返回已有订单，不重复写）。

        - **不改库存**：库存控制走 reserve → commit；create_order 只负责订单记录。
        - 订单行：``sku`` 或 ``product_id`` + 正整数 ``quantity``；``unit_price`` 可覆盖
          （促销价），缺省用 SKU 当前价；标题用「商品标题 + 规格」快照。
        - 校验：传入 ``total_amount`` 必须精确等于 Σ(数量 × 单价)，否则
          ``MERCHANT_INVALID``，一行都不写。
        - 幂等：同 order_id 重复调用返回首次写入的订单；若 order_id 已属于**其他商家**，
          抛 ``MERCHANT_CONFLICT``（绝不返回别人的订单）。
        """
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        order = _required_text(order_id, "order_id")
        buyer = _required_text(buyer_id, "buyer_id")
        source = _clean_optional(source_ref)
        requested = _normalize_write_items(items)
        total = _parse_money(total_amount, "total_amount")

        with self._lock, self._transaction() as conn:
            existing_row = conn.execute(
                "SELECT * FROM m_order WHERE order_id = ?", (order,)
            ).fetchone()
            if existing_row is not None:
                if str(existing_row["merchant_id"]) != merchant:
                    raise MerchantConflictError(f"order_id 已被占用: {order}")
                return self._hydrate_orders(conn, [existing_row])[0]

            lines = self._resolve_write_lines(conn, merchant, requested, with_price=True)
            computed = sum(
                (line["unit_price"] * line["quantity"] for line in lines),
                Decimal("0"),
            )
            if computed != total:
                raise MerchantInvalidError(
                    f"订单金额不一致：传入 {money_text(total)}，"
                    f"订单行合计 {money_text(computed)}"
                )

            now = _now()
            conn.execute(
                "INSERT INTO m_order "
                "(order_id, merchant_id, buyer_id, status, total_amount, currency, channel, "
                " created_at, paid_at, source_ref) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)",
                (
                    order,
                    merchant,
                    buyer,
                    ORDER_STATUS_CREATED,
                    money_text(total),
                    DEFAULT_CURRENCY,
                    now,
                    source,
                ),
            )
            for line_no, line in enumerate(lines, start=1):
                line_amount = line["unit_price"] * line["quantity"]
                conn.execute(
                    "INSERT INTO m_order_item "
                    "(order_id, line_no, sku, product_id, title, quantity, unit_price, line_amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        order,
                        line_no,
                        line["sku"],
                        line["product_id"],
                        line["title"],
                        line["quantity"],
                        money_text(line["unit_price"]),
                        money_text(line_amount),
                    ),
                )
            row = conn.execute(
                "SELECT * FROM m_order WHERE order_id = ?", (order,)
            ).fetchone()
            return self._hydrate_orders(conn, [row])[0]

    # ---------- 写操作：内部辅助 ----------
    def _resolve_write_lines(
        self,
        conn: sqlite3.Connection,
        merchant: str,
        requested: list[dict[str, Any]],
        *,
        with_price: bool = False,
    ) -> list[dict[str, Any]]:
        """把请求行解析成可写入的行（SKU 归属/状态校验 + 标题与单价快照）。"""
        resolved: list[dict[str, Any]] = []
        seen_skus: set[str] = set()
        for item in requested:
            sku_value = item["sku"]
            product_value = item["product_id"]
            if sku_value:
                row = conn.execute(
                    "SELECT s.sku, s.product_id, s.spec, s.price, s.status, "
                    "       p.title, p.status AS product_status "
                    "FROM m_sku s JOIN m_product p ON p.product_id = s.product_id "
                    "WHERE s.sku = ? AND s.merchant_id = ?",
                    (sku_value, merchant),
                ).fetchone()
                if row is None:
                    raise MerchantNotFoundError(
                        f"SKU 不存在或不属于该商家: {sku_value}"
                    )
            else:
                rows = conn.execute(
                    "SELECT s.sku, s.product_id, s.spec, s.price, s.status, "
                    "       p.title, p.status AS product_status "
                    "FROM m_sku s JOIN m_product p ON p.product_id = s.product_id "
                    "WHERE s.product_id = ? AND s.merchant_id = ? "
                    "ORDER BY s.sku ASC",
                    (product_value, merchant),
                ).fetchall()
                if not rows:
                    raise MerchantNotFoundError(
                        f"商品不存在、没有 SKU 或不属于该商家: {product_value}"
                    )
                active = [
                    candidate
                    for candidate in rows
                    if str(candidate["status"]).upper() == PRODUCT_STATUS_ACTIVE
                ]
                if len(active) != 1:
                    # 商品多规格时必须显式选 SKU：替用户挑一个是越权/猜测
                    raise MerchantInvalidError(
                        f"商品 {product_value} 有 {len(active)} 个可售 SKU，"
                        f"请显式指定 sku（禁止按价格/库存自动挑选）"
                    )
                row = active[0]

            resolved_sku = str(row["sku"])
            if resolved_sku in seen_skus:
                raise MerchantInvalidError(f"items 中 SKU 重复: {resolved_sku}")
            if str(row["status"]).upper() != PRODUCT_STATUS_ACTIVE:
                raise MerchantInvalidError(f"SKU 已停用，不能预占或下单: {resolved_sku}")
            if str(row["product_status"]).upper() != PRODUCT_STATUS_ACTIVE:
                raise MerchantInvalidError(
                    f"商品已停用，不能预占或下单: {row['product_id']}"
                )
            seen_skus.add(resolved_sku)

            unit_price: Decimal | None = None
            if with_price:
                provided = item.get("unit_price")
                unit_price = (
                    _as_decimal(provided)
                    if provided is not None
                    else _as_decimal(row["price"])
                )
            title = f"{row['title']} {row['spec']}".strip()
            resolved.append(
                {
                    "sku": resolved_sku,
                    "product_id": str(row["product_id"]),
                    "quantity": int(item["quantity"]),
                    "unit_price": unit_price,
                    "title": title,
                }
            )
        return resolved

    def _allocate_stock(
        self,
        conn: sqlite3.Connection,
        merchant: str,
        lines: list[dict[str, Any]],
        now: str,
    ) -> list[ReservationAllocation]:
        """按仓库顺序扣减 available 并增加 reserved；总量不足直接失败并回滚。"""
        allocations: list[ReservationAllocation] = []
        for line in lines:
            sku = line["sku"]
            need = int(line["quantity"])
            rows = conn.execute(
                "SELECT warehouse_id, available_qty FROM m_inventory "
                "WHERE sku = ? AND merchant_id = ? ORDER BY warehouse_id ASC",
                (sku, merchant),
            ).fetchall()
            total_available = sum(int(row["available_qty"]) for row in rows)
            if total_available < need:
                raise MerchantStockError(
                    f"库存不足：SKU {sku} 需要 {need}，当前可用 {total_available}",
                    details={
                        "sku": sku,
                        "requested": need,
                        "available": total_available,
                    },
                )
            for row in rows:
                if need <= 0:
                    break
                take = min(need, int(row["available_qty"]))
                if take <= 0:
                    continue
                cursor = conn.execute(
                    "UPDATE m_inventory SET available_qty = available_qty - ?, "
                    "reserved_qty = reserved_qty + ?, updated_at = ? "
                    "WHERE sku = ? AND warehouse_id = ? AND merchant_id = ? "
                    "AND available_qty >= ?",
                    (take, take, now, sku, row["warehouse_id"], merchant, take),
                )
                if cursor.rowcount != 1:
                    # 理论不可达（BEGIN IMMEDIATE 已串行化写者），保留为账实一致性的硬防线
                    raise MerchantInternalError(
                        f"库存扣减失败（并发冲突或账实不一致）: {sku} @ {row['warehouse_id']}"
                    )
                allocations.append(
                    ReservationAllocation(
                        sku=sku, warehouse_id=str(row["warehouse_id"]), quantity=take
                    )
                )
                need -= take
            if need > 0:
                raise MerchantStockError(
                    f"库存不足：SKU {sku} 还差 {need}",
                    details={"sku": sku, "requested": line["quantity"], "shortfall": need},
                )
        return allocations

    def _restore_allocations(
        self, conn: sqlite3.Connection, reservation: Reservation, now: str
    ) -> None:
        """按预占快照精确恢复库存（release / 过期使用）。"""
        if not reservation.allocations:
            raise MerchantInternalError(
                f"预占缺少仓库扣减明细，无法恢复库存: {reservation.reservation_id}"
            )
        for allocation in reservation.allocations:
            cursor = conn.execute(
                "UPDATE m_inventory SET available_qty = available_qty + ?, "
                "reserved_qty = reserved_qty - ?, updated_at = ? "
                "WHERE sku = ? AND warehouse_id = ? AND merchant_id = ? "
                "AND reserved_qty >= ?",
                (
                    allocation.quantity,
                    allocation.quantity,
                    now,
                    allocation.sku,
                    allocation.warehouse_id,
                    reservation.merchant_id,
                    allocation.quantity,
                ),
            )
            if cursor.rowcount != 1:
                raise MerchantInternalError(
                    f"库存恢复失败（账实不一致）: {allocation.sku} @ "
                    f"{allocation.warehouse_id}（reservation={reservation.reservation_id}）"
                )

    def _consume_allocations(
        self, conn: sqlite3.Connection, reservation: Reservation, now: str
    ) -> None:
        """commit 时把 reserved 转出（available 已扣减，保持不动）。"""
        if not reservation.allocations:
            raise MerchantInternalError(
                f"预占缺少仓库扣减明细，无法提交: {reservation.reservation_id}"
            )
        for allocation in reservation.allocations:
            cursor = conn.execute(
                "UPDATE m_inventory SET reserved_qty = reserved_qty - ?, updated_at = ? "
                "WHERE sku = ? AND warehouse_id = ? AND merchant_id = ? "
                "AND reserved_qty >= ?",
                (
                    allocation.quantity,
                    now,
                    allocation.sku,
                    allocation.warehouse_id,
                    reservation.merchant_id,
                    allocation.quantity,
                ),
            )
            if cursor.rowcount != 1:
                raise MerchantInternalError(
                    f"预占转出失败（账实不一致）: {allocation.sku} @ "
                    f"{allocation.warehouse_id}（reservation={reservation.reservation_id}）"
                )

    @staticmethod
    def _reservation_matches(
        existing: Reservation, lines: list[dict[str, Any]], buyer: str | None
    ) -> bool:
        """幂等重放判定：买家 + 规范化后的 (sku, quantity) 多集完全一致。"""
        if existing.buyer_id != buyer:
            return False
        requested = sorted((line["sku"], line["quantity"]) for line in lines)
        stored = sorted((item.sku, item.quantity) for item in existing.items)
        return requested == stored

    @staticmethod
    def _reservation_from_row(row: sqlite3.Row) -> Reservation:
        try:
            payload = json.loads(row["items_json"] or "{}")
        except (TypeError, ValueError) as exc:
            raise MerchantInternalError(
                f"预占记录损坏（items_json 不是合法 JSON）: {row['reservation_id']}"
            ) from exc
        if not isinstance(payload, dict):
            raise MerchantInternalError(
                f"预占记录损坏（items_json 结构非法）: {row['reservation_id']}"
            )
        items = tuple(
            ReservationItem(
                sku=str(item.get("sku") or ""),
                product_id=str(item.get("product_id") or ""),
                quantity=int(item.get("quantity") or 0),
            )
            for item in payload.get("items") or []
        )
        allocations = tuple(
            ReservationAllocation(
                sku=str(allocation.get("sku") or ""),
                warehouse_id=str(allocation.get("warehouse_id") or ""),
                quantity=int(allocation.get("quantity") or 0),
            )
            for allocation in payload.get("allocations") or []
        )
        return Reservation(
            merchant_id=str(row["merchant_id"]),
            reservation_id=str(row["reservation_id"]),
            status=str(row["status"]),
            expires_at=str(row["expires_at"]),
            created_at=str(row["created_at"]),
            items=items,
            allocations=allocations,
            buyer_id=row["buyer_id"],
            order_id=row["order_id"],
        )

    def _require_reservation_row(
        self, conn: sqlite3.Connection, reservation_id: str
    ) -> Reservation:
        row = conn.execute(
            "SELECT * FROM m_reservation WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if row is None:  # 理论不可达：刚写入/更新的行读不回来属于内部错误
            raise MerchantInternalError(f"预占记录读取失败: {reservation_id}")
        return self._reservation_from_row(row)

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
                    source_ref=(
                        row["source_ref"] if "source_ref" in row.keys() else None
                    ),
                )
            )
        return orders


# ==================== 写操作参数校验（纯函数，便于测试） ====================
# 这些函数不碰数据库：把「调用方输入」变成规范化值，非法输入一律抛结构化错误。
# 写路径宁可拒绝，也不做「猜测性修正」——金额/数量猜错的代价是真实库存与对账数据。


def _required_text(value: Any, field: str, *, max_length: int = 128) -> str:
    """必填字符串：去空白后不能为空，且不超过长度上限。"""
    if value is None:
        raise MerchantInvalidError(f"{field} 不能为空")
    text = str(value).strip()
    if not text:
        raise MerchantInvalidError(f"{field} 不能为空")
    if len(text) > max_length:
        raise MerchantInvalidError(f"{field} 过长（最多 {max_length} 字符）")
    return text


def _positive_int(value: Any, field: str, *, maximum: int = 1_000_000) -> int:
    """正整数（数量类字段）：bool 不算数字，0/负数/小数一律拒绝。"""
    if isinstance(value, bool):
        raise MerchantInvalidError(f"{field} 必须是正整数（收到 bool）")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise MerchantInvalidError(f"{field} 必须是整数（收到 {value!r}）") from None
    if isinstance(value, float) and not value.is_integer():
        raise MerchantInvalidError(f"{field} 必须是整数（收到 {value!r}）")
    if number <= 0:
        raise MerchantInvalidError(f"{field} 必须大于 0（收到 {number}）")
    if number > maximum:
        raise MerchantInvalidError(f"{field} 过大（最多 {maximum}）")
    return number


def _parse_money(value: Any, field: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    """金额解析：只接受有限十进制，拒绝负数/NaN/Infinity（不经过 float 中转）。"""
    if value is None:
        raise MerchantInvalidError(f"{field} 不能为空")
    if isinstance(value, bool):
        raise MerchantInvalidError(f"{field} 不是合法金额（收到 bool）")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise MerchantInvalidError(f"{field} 不是合法金额（收到 {value!r}）") from None
    if not amount.is_finite():
        raise MerchantInvalidError(f"{field} 必须是有限金额（收到 {value!r}）")
    if amount < minimum:
        raise MerchantInvalidError(f"{field} 不能小于 {money_text(minimum)}")
    return amount


def _normalize_ttl(value: Any) -> int:
    """预占有效期：正整数秒，默认 900，上限 7 天；非法值失败关闭。"""
    ttl = _positive_int(value, "ttl_seconds", maximum=MAX_RESERVATION_TTL_SECONDS)
    return ttl


def _normalize_write_items(items: Any) -> list[dict[str, Any]]:
    """规范化写请求的 items（至少包含 sku 或 product_id + 正整数 quantity）。"""
    if not isinstance(items, (list, tuple)) or not items:
        raise MerchantInvalidError("items 不能为空，至少包含一个商品行")
    if len(items) > MAX_WRITE_ITEMS:
        raise MerchantInvalidError(f"items 行数过多（最多 {MAX_WRITE_ITEMS} 行）")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise MerchantInvalidError(f"items[{index}] 必须是对象（dict）")
        quantity = _positive_int(item.get("quantity"), f"items[{index}].quantity")
        sku = _clean_optional(item.get("sku"))
        product_id = _clean_optional(item.get("product_id"))
        if not sku and not product_id:
            raise MerchantInvalidError(
                f"items[{index}] 必须包含 sku 或 product_id（至少一个）"
            )
        unit_price_raw = item.get("unit_price")
        unit_price = (
            None
            if unit_price_raw is None or str(unit_price_raw).strip() == ""
            else _parse_money(unit_price_raw, f"items[{index}].unit_price")
        )
        normalized.append(
            {
                "sku": sku,
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": unit_price,
            }
        )
    return normalized


def _reservation_payload_json(
    lines: list[dict[str, Any]], allocations: list[ReservationAllocation]
) -> str:
    """预占落库的 JSON：请求行 + 实际扣减明细（释放/提交必须按后者精确回滚）。"""
    payload = {
        "items": [
            {"sku": line["sku"], "product_id": line["product_id"], "quantity": line["quantity"]}
            for line in lines
        ],
        "allocations": [allocation.to_dict() for allocation in allocations],
    }
    return json.dumps(payload, ensure_ascii=False)


def _future_iso(ttl_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_expired(expires_at: str, now_iso: str) -> bool:
    """预占是否过期。时间格式异常按「已过期」处理（失败关闭，宁可多释放一次）。"""
    try:
        return _parse_iso(expires_at) <= _parse_iso(now_iso)
    except (TypeError, ValueError):
        return True


def _escape_like(term: str) -> str:
    """转义 LIKE 通配符：用户关键词里的 % / _ 不应被当成通配（与 ESCAPE '\\' 配合）。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "DEFAULT_DB_FILENAME",
    "DEFAULT_RESERVATION_TTL_SECONDS",
    "MAX_RESERVATION_TTL_SECONDS",
    "MAX_WRITE_ITEMS",
    "SqliteMerchantRepository",
    "default_db_path",
]
