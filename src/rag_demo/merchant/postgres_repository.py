"""PostgreSQL 实现的商家数据层（v1 PG adapter：与 SQLite 同契约的读写实现）。

定位与边界
----------
- **契约相同**：实现 :class:`rag_demo.merchant.repository.MerchantRepository` +
  :class:`MerchantWriteRepository`，读/写语义（租户隔离、limit 钳制、幂等、
  状态机、取消/退款、错误码）与 SQLite adapter 保持一致；
- **隔离**：所有表都在独立 schema（默认 ``merchant_v1``，``QIANKE_MERCHANT_PG_SCHEMA`` 覆盖），
  绝不写 public 或其他业务表；schema 名严格校验后才拼入 DDL；
- **不是真实 OMS**：和 SQLite adapter 一样是本地演示/集成实现，真实交易必须走 OMS
  受控接口 + 人工确认；
- **psycopg2 延迟导入**：模块顶层不 import psycopg2；只有真正构造/连接 PG 时才导入，
  因此没装驱动或没配 PG 时不会阻断 SQLite 默认路径；
- 连接不做连接池（每次操作短连接、事务结束即关闭，异常必 rollback），
  并发写依赖 PostgreSQL 事务 + ``SELECT ... FOR UPDATE`` / 唯一约束；
- 金额与时间列沿用 SQLite 的 TEXT 存储（十进制字符串 / ISO-8601 文本），
  保证两个 adapter 的 Decimal/时间语义完全一致，不引入 float。

配置（环境变量，``QIANKE_MERCHANT_PG_*`` 优先，其次 ``RAG_PG_*``，最后本机默认）
----------------------------------------------------------------------------------
``QIANKE_MERCHANT_PG_HOST`` / ``PORT`` / ``USER`` / ``PASSWORD`` / ``DBNAME`` / ``SCHEMA``
对应回退 ``RAG_PG_HOST`` / ``RAG_PG_PORT`` / ``RAG_PG_USER`` / ``RAG_PG_PASSWORD``，
dbname 默认 ``vec_db``、schema 默认 ``merchant_v1``。
"""
from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import seeds
from .errors import (
    MerchantConfigurationError,
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
    ORDER_STATUSES,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_CREATED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_REFUNDED,
    ORDER_STATUS_SHIPPED,
    ORDER_STATUS_TRANSITIONS,
    PRODUCT_STATUS_ACTIVE,
    RESERVATION_STATUS_COMMITTED,
    RESERVATION_STATUS_EXPIRED,
    RESERVATION_STATUS_RELEASED,
    RESERVATION_STATUS_RESERVED,
    RESERVATION_STATUS_REVERSED,
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
# 复用写操作的纯校验/时间/幂等辅助函数，保证 SQLite/PG 规则不漂移。
from .sqlite_repository import (
    DEFAULT_RESERVATION_TTL_SECONDS,
    _as_decimal,
    _clean_optional,
    _escape_like,
    _future_iso,
    _is_expired,
    _normalize_carrier,
    _normalize_refund_amount,
    _normalize_ttl,
    _normalize_tracking_no,
    _normalize_write_items,
    _parse_money,
    _reservation_payload_json,
    _required_text,
    _now,
)

DEFAULT_SCHEMA = "merchant_v1"
_ENV = "QIANKE_MERCHANT_PG_"
_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

_TABLES = (
    "m_product",
    "m_sku",
    "m_inventory",
    "m_order",
    "m_order_item",
    "m_meta",
    "m_reservation",
)


def _env_value(name: str, legacy_name: str | None, default: str) -> str:
    """读配置：QIANKE_MERCHANT_PG_* > 兼容 RAG_PG_* > 默认值。"""
    for key in (f"{_ENV}{name}", legacy_name):
        if not key:
            continue
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return default


def _settings(
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    dbname: str | None = None,
    schema: str | None = None,
) -> dict[str, Any]:
    """解析连接配置；显式参数优先于环境变量。不把密码写进任何对外输出。"""
    resolved_schema = (schema or _env_value("SCHEMA", None, DEFAULT_SCHEMA)).strip()
    if not _SCHEMA_PATTERN.match(resolved_schema):
        raise MerchantConfigurationError(
            f"非法 PostgreSQL schema 名: {resolved_schema!r}"
            "（只允许字母/数字/下划线，且不能以数字开头）"
        )
    port_text = str(port) if port is not None else _env_value("PORT", "RAG_PG_PORT", "5432")
    try:
        port_number = int(port_text)
    except (TypeError, ValueError):
        raise MerchantConfigurationError(f"非法 PostgreSQL 端口: {port_text!r}") from None
    if not (1 <= port_number <= 65535):
        raise MerchantConfigurationError(f"非法 PostgreSQL 端口: {port_number}")
    return {
        "host": host or _env_value("HOST", "RAG_PG_HOST", "127.0.0.1"),
        "port": port_number,
        "user": user or _env_value("USER", "RAG_PG_USER", "postgres"),
        "password": password or _env_value("PASSWORD", "RAG_PG_PASSWORD", "123456"),
        "dbname": dbname or _env_value("DBNAME", None, "vec_db"),
        "schema": resolved_schema,
        "connect_timeout": int(_env_value("CONNECT_TIMEOUT", None, "5")),
    }


def _import_psycopg2():
    """延迟导入 psycopg2；未安装时给出结构化配置错误（不影响 SQLite 默认路径）。"""
    try:
        import psycopg2
        import psycopg2.errors
        import psycopg2.extras
    except ImportError as exc:  # pragma: no cover - 本机已安装，保留给精简环境
        raise MerchantConfigurationError(
            "PostgreSQL 商家 adapter 需要 psycopg2-binary：请先安装依赖"
        ) from exc
    return psycopg2, psycopg2.extras, psycopg2.errors


def _quote_ident(name: str) -> str:
    """schema/表名标识符引用；调用前已用正则白名单校验。"""
    return '"' + name.replace('"', '""') + '"'


class PostgresMerchantRepository:
    """PostgreSQL 商家数据层（读写能力与 SQLite adapter 对齐）。"""

    backend = "postgres"

    def __init__(
        self,
        db_path: Any = None,  # 兼容 factory 的统一签名；PG 忽略 SQLite 路径
        *,
        seed: bool = True,
        seed_dir: str | Path | None = None,
        schema: str | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        dbname: str | None = None,
    ) -> None:
        del db_path  # PG adapter 使用自己的连接配置
        self._settings = _settings(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            schema=schema,
        )
        self._schema = str(self._settings["schema"])
        self._seed_dir = (
            Path(seed_dir).expanduser() if seed_dir else seeds.default_seed_dir()
        )
        self._lock = threading.RLock()
        self._closed = False
        with self._lock:
            self._init_schema()
            if seed:
                self._ensure_seeded()

    # ---------- 连接 / 生命周期 ----------
    @property
    def schema(self) -> str:
        return self._schema

    @property
    def dsn(self) -> str:
        """不含密码的 DSN 形式描述（日志/describe 用）。"""
        settings = self._settings
        return (
            f"postgresql://{settings['user']}@{settings['host']}:{settings['port']}"
            f"/{settings['dbname']}#{self._schema}"
        )

    def _connect(self):
        psycopg2, _, _ = _import_psycopg2()
        settings = self._settings
        try:
            conn = psycopg2.connect(
                host=settings["host"],
                port=settings["port"],
                user=settings["user"],
                password=settings["password"],
                dbname=settings["dbname"],
                connect_timeout=settings["connect_timeout"],
                application_name="qianke-merchant-postgres",
            )
        except psycopg2.OperationalError as exc:
            raise MerchantUnavailableError(
                f"无法连接 PostgreSQL 商家库（{settings['host']}:{settings['port']}"
                f"/{settings['dbname']}）: {exc}"
            ) from exc
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SET search_path TO {_quote_ident(self._schema)}, pg_catalog"
                )
            conn.commit()
        except BaseException:
            conn.close()
            raise
        return conn

    def _ensure_open(self) -> None:
        if self._closed:
            raise MerchantUnavailableError(
                "商家数据层已关闭（close() 之后不能再查询）"
            )

    def close(self) -> None:
        """无持久连接；标记关闭，防止误用已释放实例（可重复调用）。"""
        self._closed = True

    def __enter__(self) -> "PostgresMerchantRepository":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @contextmanager
    def _read(self) -> Iterator[Any]:
        self._ensure_open()
        _, extras, _ = _import_psycopg2()
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                yield cur
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        self._ensure_open()
        _, extras, _ = _import_psycopg2()
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                yield cur
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 回滚失败不应掩盖原始异常
                pass
            raise
        finally:
            conn.close()

    # ---------- schema / 种子 ----------
    def _ddl(self) -> str:
        schema = _quote_ident(self._schema)
        return f"""
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.m_product (
    product_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    brand       TEXT,
    status      TEXT NOT NULL,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS {schema}.m_sku (
    sku        TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES {schema}.m_product (product_id),
    spec       TEXT NOT NULL,
    price      TEXT NOT NULL,
    status     TEXT NOT NULL,
    barcode    TEXT
);

CREATE INDEX IF NOT EXISTS idx_m_sku_merchant
    ON {schema}.m_sku (merchant_id);
CREATE INDEX IF NOT EXISTS idx_m_sku_product
    ON {schema}.m_sku (product_id);

CREATE TABLE IF NOT EXISTS {schema}.m_inventory (
    sku           TEXT NOT NULL REFERENCES {schema}.m_sku (sku),
    warehouse_id  TEXT NOT NULL,
    merchant_id   TEXT NOT NULL,
    available_qty INTEGER NOT NULL,
    reserved_qty  INTEGER NOT NULL,
    safety_stock  INTEGER NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (sku, warehouse_id)
);

CREATE INDEX IF NOT EXISTS idx_m_inventory_merchant
    ON {schema}.m_inventory (merchant_id);

CREATE TABLE IF NOT EXISTS {schema}.m_order (
    order_id     TEXT PRIMARY KEY,
    merchant_id  TEXT NOT NULL,
    buyer_id     TEXT NOT NULL,
    status       TEXT NOT NULL,
    total_amount TEXT NOT NULL,
    currency     TEXT NOT NULL,
    channel      TEXT,
    created_at   TEXT NOT NULL,
    paid_at      TEXT,
    source_ref   TEXT,
    tracking_no  TEXT,
    carrier      TEXT,
    shipped_at   TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    refund_amount TEXT,
    refunded_at  TEXT,
    cancel_request_id TEXT,
    refund_request_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_m_order_merchant
    ON {schema}.m_order (merchant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_m_order_buyer
    ON {schema}.m_order (buyer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_m_order_cancel_request
    ON {schema}.m_order (cancel_request_id)
    WHERE cancel_request_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_m_order_refund_request
    ON {schema}.m_order (refund_request_id)
    WHERE refund_request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS {schema}.m_order_item (
    order_id    TEXT NOT NULL REFERENCES {schema}.m_order (order_id) ON DELETE CASCADE,
    line_no     INTEGER NOT NULL,
    sku         TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    title       TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    unit_price  TEXT NOT NULL,
    line_amount TEXT NOT NULL,
    PRIMARY KEY (order_id, line_no)
);

CREATE TABLE IF NOT EXISTS {schema}.m_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS {schema}.m_reservation (
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
    ON {schema}.m_reservation (merchant_id, status);
"""

    def _init_schema(self) -> None:
        self._ensure_open()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(self._ddl())
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_seeded(self) -> None:
        with self._read() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM m_product")
            existing = int(cur.fetchone()["n"])
        if existing == 0:
            self.seed()

    def seed(self, *, force: bool = False) -> dict[str, int]:
        """按种子文件初始化/重置；幂等（重复调用不重复插入），支持 ``force=True`` 重灌。"""
        self._ensure_open()
        data = seeds.load_seed_data(self._seed_dir)
        with self._lock, self._transaction() as cur:
            if not force:
                cur.execute("SELECT COUNT(*) AS n FROM m_product")
                if int(cur.fetchone()["n"]) > 0:
                    return self._counts(cur)
            cur.execute("DELETE FROM m_reservation")
            cur.execute("DELETE FROM m_order_item")
            cur.execute("DELETE FROM m_order")
            cur.execute("DELETE FROM m_inventory")
            cur.execute("DELETE FROM m_sku")
            cur.execute("DELETE FROM m_product")
            self._insert_seed(cur, data)
            meta = {
                "seed_version": "v1",
                "seed_dir": str(self._seed_dir),
                "seeded_at": _now(),
                "seed_counts": json.dumps(data.counts(), ensure_ascii=False),
                "seed_files_sha256": json.dumps(data.file_sha256, ensure_ascii=False),
            }
            for key, value in meta.items():
                cur.execute(
                    "INSERT INTO m_meta (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (key, value),
                )
            return self._counts(cur)

    def _insert_seed(self, cur: Any, data: seeds.SeedData) -> None:
        cur.executemany(
            "INSERT INTO m_product "
            "(product_id, merchant_id, title, category, brand, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    p.product_id, p.merchant_id, p.title, p.category,
                    p.brand, p.status, p.created_at,
                )
                for p in data.products
            ],
        )
        cur.executemany(
            "INSERT INTO m_sku "
            "(sku, merchant_id, product_id, spec, price, status, barcode) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    s.sku, s.merchant_id, s.product_id, s.spec,
                    money_text(s.price), s.status, s.barcode,
                )
                for s in data.skus
            ],
        )
        cur.executemany(
            "INSERT INTO m_inventory "
            "(sku, warehouse_id, merchant_id, available_qty, reserved_qty, "
            " safety_stock, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    r.sku, r.warehouse_id, r.merchant_id, r.available_qty,
                    r.reserved_qty, r.safety_stock, r.updated_at,
                )
                for r in data.inventory_records
            ],
        )
        cur.executemany(
            "INSERT INTO m_order "
            "(order_id, merchant_id, buyer_id, status, total_amount, currency, channel, "
            " created_at, paid_at, tracking_no, carrier, shipped_at, completed_at, "
            " cancelled_at, refund_amount, refunded_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    o.order_id, o.merchant_id, o.buyer_id, o.status,
                    money_text(o.total_amount), o.currency, o.channel,
                    o.created_at, o.paid_at, o.tracking_no, o.carrier,
                    o.shipped_at, o.completed_at, o.cancelled_at,
                    money_text(o.refund_amount) if o.refund_amount is not None else None,
                    o.refunded_at,
                )
                for o in data.orders
            ],
        )
        item_rows = []
        for order in data.orders:
            for line_no, item in enumerate(order.items, start=1):
                item_rows.append(
                    (
                        order.order_id, line_no, item.sku, item.product_id,
                        item.title, item.quantity, money_text(item.unit_price),
                        money_text(item.line_amount),
                    )
                )
        cur.executemany(
            "INSERT INTO m_order_item "
            "(order_id, line_no, sku, product_id, title, quantity, unit_price, line_amount) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            item_rows,
        )

    # ---------- 统计 / describe ----------
    @staticmethod
    def _counts(cur: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in (
            "m_product",
            "m_sku",
            "m_inventory",
            "m_order",
            "m_order_item",
        ):
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            counts[
                {
                    "m_product": "products",
                    "m_sku": "skus",
                    "m_inventory": "inventory_records",
                    "m_order": "orders",
                    "m_order_item": "order_items",
                }[table]
            ] = int(cur.fetchone()["n"])
        return counts

    def stats(self) -> dict[str, int]:
        self._ensure_open()
        with self._lock, self._read() as cur:
            return self._counts(cur)

    def describe(self) -> dict[str, Any]:
        """后端自描述；绝不输出密码。"""
        self._ensure_open()
        with self._lock, self._read() as cur:
            counts = self._counts(cur)
            cur.execute("SELECT COUNT(*) AS n FROM m_reservation")
            reservations = int(cur.fetchone()["n"])
            cur.execute("SELECT key, value FROM m_meta")
            meta = {str(row["key"]): str(row["value"]) for row in cur.fetchall()}
        return {
            "backend": self.backend,
            "db_path": self.dsn,
            "schema": self._schema,
            "host": self._settings["host"],
            "database": self._settings["dbname"],
            "counts": counts,
            "reservations": reservations,
            "write_capable": True,
            "seed": {
                "seed_version": meta.get("seed_version"),
                "seeded_at": meta.get("seeded_at"),
            },
        }

    # ---------- 只读查询 ----------
    @staticmethod
    def _require_merchant(merchant_id: str | None) -> str:
        merchant = _clean_optional(merchant_id)
        if merchant is None:
            raise MerchantDataError(
                "merchant_id 不能为空：商家数据查询必须显式指定租户，禁止跨租户/全表读取"
            )
        return merchant

    @staticmethod
    def _product_from_row(row: Mapping[str, Any]) -> Product:
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
    def _sku_from_row(row: Mapping[str, Any]) -> SKU:
        return SKU(
            merchant_id=str(row["merchant_id"]),
            sku=str(row["sku"]),
            product_id=str(row["product_id"]),
            spec=str(row["spec"]),
            price=_as_decimal(row["price"]),
            status=str(row["status"]),
            barcode=row["barcode"],
        )

    def list_products(
        self,
        merchant_id: str,
        keyword: str | None = None,
        limit: int | None = DEFAULT_LIST_LIMIT,
    ) -> list[Product]:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        bounded = clamp_limit(limit)
        sql = (
            "SELECT product_id, merchant_id, title, category, brand, status, created_at "
            "FROM m_product WHERE merchant_id = %s"
        )
        params: list[Any] = [merchant]
        needle = _clean_optional(keyword)
        if needle:
            pattern = f"%{_escape_like(needle.lower())}%"
            sql += (
                " AND (LOWER(title) LIKE %s ESCAPE '\\'"
                " OR LOWER(category) LIKE %s ESCAPE '\\'"
                " OR LOWER(COALESCE(brand, '')) LIKE %s ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY product_id ASC LIMIT %s"
        params.append(bounded)
        with self._lock, self._read() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [self._product_from_row(row) for row in rows]

    def get_product_sku(
        self, sku: str, *, merchant_id: str | None = None
    ) -> SKU | None:
        self._ensure_open()
        sku_id = _clean_optional(sku)
        if not sku_id:
            return None
        sql = (
            "SELECT sku, merchant_id, product_id, spec, price, status, barcode "
            "FROM m_sku WHERE sku = %s"
        )
        params: list[Any] = [sku_id]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = %s"
            params.append(merchant)
        with self._lock, self._read() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return self._sku_from_row(row) if row is not None else None

    def list_product_skus(
        self, product_id: str, *, merchant_id: str | None = None
    ) -> list[SKU]:
        self._ensure_open()
        product = _clean_optional(product_id)
        if not product:
            return []
        sql = (
            "SELECT sku, merchant_id, product_id, spec, price, status, barcode "
            "FROM m_sku WHERE product_id = %s"
        )
        params: list[Any] = [product]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = %s"
            params.append(merchant)
        sql += " ORDER BY sku ASC"
        with self._lock, self._read() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [self._sku_from_row(row) for row in rows]

    def get_inventory(
        self, sku: str, *, merchant_id: str | None = None
    ) -> Inventory | None:
        self._ensure_open()
        sku_id = _clean_optional(sku)
        if not sku_id:
            return None
        sql = (
            "SELECT sku, warehouse_id, merchant_id, available_qty, reserved_qty, "
            "safety_stock, updated_at FROM m_inventory WHERE sku = %s"
        )
        params: list[Any] = [sku_id]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = %s"
            params.append(merchant)
        sql += " ORDER BY warehouse_id ASC"
        with self._lock, self._read() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
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

    def list_orders(
        self,
        merchant_id: str,
        buyer_id: str | None = None,
        status: str | None = None,
        limit: int | None = DEFAULT_LIST_LIMIT,
    ) -> list[Order]:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        bounded = clamp_limit(limit)
        sql = (
            "SELECT order_id, merchant_id, buyer_id, status, total_amount, currency, "
            "channel, created_at, paid_at, source_ref, tracking_no, carrier, "
            "shipped_at, completed_at, cancelled_at, refund_amount, refunded_at "
            "FROM m_order WHERE merchant_id = %s"
        )
        params: list[Any] = [merchant]
        buyer = _clean_optional(buyer_id)
        if buyer is not None:
            sql += " AND buyer_id = %s"
            params.append(buyer)
        status_value = _clean_optional(status)
        if status_value is not None:
            sql += " AND status = %s"
            params.append(status_value.upper())
        sql += " ORDER BY created_at DESC, order_id DESC LIMIT %s"
        params.append(bounded)
        with self._lock, self._read() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return self._hydrate_orders(cur, rows)

    def get_order(
        self,
        order_id: str,
        *,
        merchant_id: str | None = None,
        buyer_id: str | None = None,
    ) -> Order | None:
        self._ensure_open()
        order = _clean_optional(order_id)
        if not order:
            return None
        sql = (
            "SELECT order_id, merchant_id, buyer_id, status, total_amount, currency, "
            "channel, created_at, paid_at, source_ref, tracking_no, carrier, "
            "shipped_at, completed_at, cancelled_at, refund_amount, refunded_at "
            "FROM m_order WHERE order_id = %s"
        )
        params: list[Any] = [order]
        merchant = _clean_optional(merchant_id)
        if merchant is not None:
            sql += " AND merchant_id = %s"
            params.append(merchant)
        buyer = _clean_optional(buyer_id)
        if buyer is not None:
            sql += " AND buyer_id = %s"
            params.append(buyer)
        with self._lock, self._read() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            hydrated = self._hydrate_orders(cur, [row])
        return hydrated[0] if hydrated else None

    # ---------- 写路径：预占 / 订单 ----------
    @staticmethod
    def _unique_violation(exc: BaseException) -> bool:
        return exc.__class__.__name__ == "UniqueViolation"

    def reserve_inventory(
        self,
        merchant_id: str,
        reservation_id: str,
        items: list[dict[str, Any]],
        ttl_seconds: int = DEFAULT_RESERVATION_TTL_SECONDS,
        *,
        buyer_id: str | None = None,
    ) -> Reservation:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        reservation = _required_text(reservation_id, "reservation_id")
        buyer = _clean_optional(buyer_id)
        ttl = _normalize_ttl(ttl_seconds)
        requested = _normalize_write_items(items)
        last_error: BaseException | None = None
        for _attempt in range(3):
            try:
                with self._lock, self._transaction() as cur:
                    return self._reserve_tx(cur, merchant, reservation, buyer, ttl, requested)
            except BaseException as exc:  # noqa: BLE001 只对唯一冲突重试
                if not self._unique_violation(exc):
                    raise
                last_error = exc
        raise MerchantConflictError(
            "reservation_id 并发写入冲突，请稍后重试"
        ) from last_error

    def _reserve_tx(
        self,
        cur: Any,
        merchant: str,
        reservation: str,
        buyer: str | None,
        ttl: int,
        requested: list[dict[str, Any]],
    ) -> Reservation:
        lines = self._resolve_write_lines(cur, merchant, requested)
        cur.execute(
            "SELECT * FROM m_reservation WHERE reservation_id = %s FOR UPDATE",
            (reservation,),
        )
        existing_row = cur.fetchone()
        now = _now()
        if existing_row is not None:
            existing = self._reservation_from_row(existing_row)
            if existing.merchant_id != merchant:
                raise MerchantConflictError(f"reservation_id 已被占用: {reservation}")
            if existing.status == RESERVATION_STATUS_RESERVED:
                if not _is_expired(existing.expires_at, now):
                    if self._reservation_matches(existing, lines, buyer):
                        return existing
                    raise MerchantConflictError(
                        "reservation_id 已被不同的预占请求使用；请使用新的 reservation_id"
                    )
                self._restore_allocations(cur, existing, now)
                allocations = self._allocate_stock(cur, merchant, lines, now)
                expires_at = _future_iso(ttl)
                cur.execute(
                    "UPDATE m_reservation SET buyer_id = %s, status = %s, expires_at = %s, "
                    "items_json = %s, created_at = %s, updated_at = %s, order_id = NULL "
                    "WHERE reservation_id = %s AND merchant_id = %s",
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
                return self._require_reservation_row(cur, reservation)
            raise MerchantConflictError(
                f"reservation 已处于终态 {existing.status}，不能复用；"
                f"请使用新的 reservation_id"
            )

        allocations = self._allocate_stock(cur, merchant, lines, now)
        expires_at = _future_iso(ttl)
        cur.execute(
            "INSERT INTO m_reservation "
            "(reservation_id, merchant_id, buyer_id, status, expires_at, items_json, "
            " created_at, updated_at, order_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)",
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
        return self._require_reservation_row(cur, reservation)

    def commit_reservation(
        self,
        merchant_id: str,
        reservation_id: str,
        order_id: str | None = None,
    ) -> Reservation:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        reservation = _required_text(reservation_id, "reservation_id")
        order = _clean_optional(order_id)
        if order is not None:
            order = _required_text(order, "order_id")

        now = _now()
        expired = False
        with self._lock, self._transaction() as cur:
            cur.execute(
                "SELECT * FROM m_reservation WHERE reservation_id = %s FOR UPDATE",
                (reservation,),
            )
            row = cur.fetchone()
            if row is None:
                raise MerchantNotFoundError(f"预占不存在: {reservation}")
            existing = self._reservation_from_row(row)
            if existing.merchant_id != merchant:
                raise MerchantNotFoundError(f"预占不存在: {reservation}")
            if existing.status == RESERVATION_STATUS_COMMITTED:
                if order is None or existing.order_id == order:
                    return existing
                raise MerchantConflictError(
                    f"预占已提交为订单 {existing.order_id}，不能重复提交为其他订单"
                )
            if existing.status == RESERVATION_STATUS_RELEASED:
                raise MerchantConflictError("预占已释放，不能提交")
            if existing.status == RESERVATION_STATUS_REVERSED:
                raise MerchantConflictError("预占已因订单取消冲销，不能提交")
            if existing.status == RESERVATION_STATUS_EXPIRED:
                raise MerchantExpiredError("预占已过期，不能提交；请重新预占")
            if existing.status != RESERVATION_STATUS_RESERVED:
                raise MerchantInternalError(
                    f"预占状态非法: {existing.status!r}（reservation={reservation}）"
                )
            if _is_expired(existing.expires_at, now):
                self._restore_allocations(cur, existing, now)
                cur.execute(
                    "UPDATE m_reservation SET status = %s, updated_at = %s "
                    "WHERE reservation_id = %s",
                    (RESERVATION_STATUS_EXPIRED, now, reservation),
                )
                expired = True
            else:
                self._consume_allocations(cur, existing, now)
                cur.execute(
                    "UPDATE m_reservation SET status = %s, order_id = %s, updated_at = %s "
                    "WHERE reservation_id = %s AND merchant_id = %s",
                    (RESERVATION_STATUS_COMMITTED, order, now, reservation, merchant),
                )
                return self._require_reservation_row(cur, reservation)
        if expired:
            raise MerchantExpiredError("预占已过期，库存已释放；请重新预占后再提交")
        raise MerchantInternalError(f"预占提交状态异常: {reservation}")

    def release_reservation(self, merchant_id: str, reservation_id: str) -> Reservation:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        reservation = _required_text(reservation_id, "reservation_id")
        now = _now()
        with self._lock, self._transaction() as cur:
            cur.execute(
                "SELECT * FROM m_reservation WHERE reservation_id = %s FOR UPDATE",
                (reservation,),
            )
            row = cur.fetchone()
            if row is None:
                raise MerchantNotFoundError(f"预占不存在: {reservation}")
            existing = self._reservation_from_row(row)
            if existing.merchant_id != merchant:
                raise MerchantNotFoundError(f"预占不存在: {reservation}")
            if existing.status in (
                RESERVATION_STATUS_RELEASED,
                RESERVATION_STATUS_EXPIRED,
                RESERVATION_STATUS_REVERSED,
            ):
                return existing
            if existing.status == RESERVATION_STATUS_COMMITTED:
                raise MerchantConflictError("预占已提交为订单，不能释放")
            if existing.status != RESERVATION_STATUS_RESERVED:
                raise MerchantInternalError(
                    f"预占状态非法: {existing.status!r}（reservation={reservation}）"
                )
            final_status = (
                RESERVATION_STATUS_EXPIRED
                if _is_expired(existing.expires_at, now)
                else RESERVATION_STATUS_RELEASED
            )
            self._restore_allocations(cur, existing, now)
            cur.execute(
                "UPDATE m_reservation SET status = %s, updated_at = %s "
                "WHERE reservation_id = %s AND merchant_id = %s",
                (final_status, now, reservation, merchant),
            )
            return self._require_reservation_row(cur, reservation)

    def create_order(
        self,
        merchant_id: str,
        order_id: str,
        buyer_id: str,
        items: list[dict[str, Any]],
        total_amount: Any,
        source_ref: str | None = None,
    ) -> Order:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        order = _required_text(order_id, "order_id")
        buyer = _required_text(buyer_id, "buyer_id")
        source = _clean_optional(source_ref)
        requested = _normalize_write_items(items)
        total = _parse_money(total_amount, "total_amount")
        last_error: BaseException | None = None
        for _attempt in range(3):
            try:
                with self._lock, self._transaction() as cur:
                    return self._create_order_tx(
                        cur, merchant, order, buyer, requested, total, source
                    )
            except BaseException as exc:  # noqa: BLE001 只对唯一冲突重试（并发同 order_id）
                if not self._unique_violation(exc):
                    raise
                last_error = exc
        # 重试后仍未成功：说明是其它行的唯一冲突，按冲突结构化返回
        raise MerchantConflictError(f"order_id 并发写入冲突: {order}") from last_error

    def _create_order_tx(
        self,
        cur: Any,
        merchant: str,
        order: str,
        buyer: str,
        requested: list[dict[str, Any]],
        total: Decimal,
        source: str | None,
    ) -> Order:
        cur.execute("SELECT * FROM m_order WHERE order_id = %s", (order,))
        existing_row = cur.fetchone()
        if existing_row is not None:
            if str(existing_row["merchant_id"]) != merchant:
                raise MerchantConflictError(f"order_id 已被占用: {order}")
            return self._hydrate_orders(cur, [existing_row])[0]

        lines = self._resolve_write_lines(cur, merchant, requested, with_price=True)
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
        cur.execute(
            "INSERT INTO m_order "
            "(order_id, merchant_id, buyer_id, status, total_amount, currency, channel, "
            " created_at, paid_at, source_ref) "
            "VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, NULL, %s)",
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
            cur.execute(
                "INSERT INTO m_order_item "
                "(order_id, line_no, sku, product_id, title, quantity, unit_price, line_amount) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
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
        cur.execute("SELECT * FROM m_order WHERE order_id = %s", (order,))
        return self._hydrate_orders(cur, [cur.fetchone()])[0]

    def update_order_status(
        self,
        merchant_id: str,
        order_id: str,
        status: str,
        tracking_no: str | None = None,
        carrier: str | None = None,
    ) -> Order:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        order = _required_text(order_id, "order_id")
        target = _required_text(status, "status", max_length=32).upper()
        if target not in ORDER_STATUSES:
            raise MerchantInvalidError(
                f"未知订单状态: {status}（允许: {', '.join(ORDER_STATUSES)}）"
            )
        if target == ORDER_STATUS_REFUNDED:
            raise MerchantInvalidError(
                "REFUNDED 只能通过 refund_order(merchant_id, order_id, amount=...) 执行；"
                "update_order_status 不允许无金额退款"
            )
        tracking = (
            _normalize_tracking_no(tracking_no) if tracking_no is not None else None
        )
        carrier_value = _normalize_carrier(carrier)
        if target != ORDER_STATUS_SHIPPED and (
            tracking is not None or carrier_value is not None
        ):
            raise MerchantInvalidError("只有 SHIPPED 状态允许携带 tracking_no/carrier")
        if target == ORDER_STATUS_SHIPPED and tracking is None:
            raise MerchantInvalidError("SHIPPED 状态必须提供 tracking_no（物流单号）")

        with self._lock, self._transaction() as cur:
            cur.execute(
                "SELECT * FROM m_order WHERE order_id = %s FOR UPDATE", (order,)
            )
            row = cur.fetchone()
            if row is None or str(row["merchant_id"]) != merchant:
                raise MerchantNotFoundError(f"订单不存在: {order}")
            current = str(row["status"]).upper()
            if current not in ORDER_STATUS_TRANSITIONS:
                raise MerchantInternalError(
                    f"订单 {order} 当前状态非法: {row['status']!r}"
                )
            if target == current:
                if target == ORDER_STATUS_SHIPPED:
                    if tracking is not None and tracking != row["tracking_no"]:
                        raise MerchantConflictError(
                            "订单已发货且物流单号不同，不能修改物流单号"
                        )
                    if carrier_value is not None and carrier_value != row["carrier"]:
                        raise MerchantConflictError(
                            "订单已发货且承运商不同，不能修改承运商"
                        )
                return self._hydrate_orders(cur, [row])[0]
            if target not in ORDER_STATUS_TRANSITIONS[current]:
                allowed = ", ".join(sorted(ORDER_STATUS_TRANSITIONS[current])) or "无（终态）"
                raise MerchantConflictError(
                    f"非法订单状态迁移: {current} -> {target}（当前状态允许: {allowed}）"
                )
            if target == ORDER_STATUS_CANCELLED:
                return self._cancel_order_row(cur, row, now=_now())

            now = _now()
            assignments: dict[str, Any] = {"status": target}
            if target == ORDER_STATUS_PAID:
                assignments["paid_at"] = now
            elif target == ORDER_STATUS_SHIPPED:
                assignments["shipped_at"] = now
                assignments["tracking_no"] = tracking
                assignments["carrier"] = carrier_value
            elif target == ORDER_STATUS_COMPLETED:
                assignments["completed_at"] = now
            set_sql = ", ".join(f"{column} = %s" for column in assignments)
            cur.execute(
                f"UPDATE m_order SET {set_sql} WHERE order_id = %s AND merchant_id = %s",
                (*assignments.values(), order, merchant),
            )
            if cur.rowcount != 1:
                raise MerchantNotFoundError(f"订单不存在: {order}")
            cur.execute("SELECT * FROM m_order WHERE order_id = %s", (order,))
            return self._hydrate_orders(cur, [cur.fetchone()])[0]

    def cancel_order(
        self,
        merchant_id: str,
        order_id: str,
        request_id: str | None = None,
    ) -> Order:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        order = _required_text(order_id, "order_id")
        request = request_id
        if request is not None:
            request = _required_text(request, "request_id", max_length=128)
        try:
            with self._lock, self._transaction() as cur:
                now = _now()
                if request is not None:
                    cur.execute(
                        "SELECT * FROM m_order WHERE cancel_request_id = %s",
                        (request,),
                    )
                    bound = cur.fetchone()
                    if bound is not None:
                        if (
                            str(bound["order_id"]) != order
                            or str(bound["merchant_id"]) != merchant
                        ):
                            raise MerchantConflictError(
                                "request_id 已被用于其他订单的取消，不能跨订单复用"
                            )
                        return self._hydrate_orders(cur, [bound])[0]
                cur.execute(
                    "SELECT * FROM m_order WHERE order_id = %s FOR UPDATE", (order,)
                )
                row = cur.fetchone()
                if row is None or str(row["merchant_id"]) != merchant:
                    raise MerchantNotFoundError(f"订单不存在: {order}")
                current = str(row["status"]).upper()
                if current == ORDER_STATUS_CANCELLED:
                    return self._hydrate_orders(cur, [row])[0]
                if current not in (ORDER_STATUS_CREATED, ORDER_STATUS_PAID):
                    raise MerchantConflictError(
                        f"当前状态 {current} 不允许取消（仅 CREATED/PAID 可取消）"
                    )
                return self._cancel_order_row(cur, row, now=now, request_id=request)
        except BaseException as exc:  # noqa: BLE001 request_id 唯一索引并发兜底
            if not self._unique_violation(exc):
                raise
            raise MerchantConflictError(
                "request_id 已被其他取消请求占用，请重试或换用新的 request_id"
            ) from exc

    def refund_order(
        self,
        merchant_id: str,
        order_id: str,
        amount: Any = None,
        request_id: str | None = None,
    ) -> Order:
        self._ensure_open()
        merchant = self._require_merchant(merchant_id)
        order = _required_text(order_id, "order_id")
        request = request_id
        if request is not None:
            request = _required_text(request, "request_id", max_length=128)
        try:
            with self._lock, self._transaction() as cur:
                now = _now()
                if request is not None:
                    cur.execute(
                        "SELECT * FROM m_order WHERE refund_request_id = %s",
                        (request,),
                    )
                    bound = cur.fetchone()
                    if bound is not None:
                        if (
                            str(bound["order_id"]) != order
                            or str(bound["merchant_id"]) != merchant
                        ):
                            raise MerchantConflictError(
                                "request_id 已被用于其他订单的退款，不能跨订单复用"
                            )
                        bound_total = _as_decimal(bound["total_amount"])
                        candidate = (
                            bound_total
                            if amount is None
                            else _normalize_refund_amount(amount)
                        )
                        stored = (
                            _as_decimal(bound["refund_amount"])
                            if bound["refund_amount"] is not None
                            else None
                        )
                        if stored is None or candidate != stored:
                            raise MerchantConflictError(
                                "request_id 已用于该订单的另一次退款，退款金额不一致；"
                                "请使用新的 request_id"
                            )
                        return self._hydrate_orders(cur, [bound])[0]

                cur.execute(
                    "SELECT * FROM m_order WHERE order_id = %s FOR UPDATE", (order,)
                )
                row = cur.fetchone()
                if row is None or str(row["merchant_id"]) != merchant:
                    raise MerchantNotFoundError(f"订单不存在: {order}")

                current = str(row["status"]).upper()
                total = _as_decimal(row["total_amount"])
                requested_amount = (
                    total if amount is None else _normalize_refund_amount(amount)
                )
                if requested_amount <= 0:
                    raise MerchantInvalidError("退款金额必须大于 0")
                if requested_amount > total:
                    raise MerchantInvalidError(
                        f"退款金额不能超过订单总额: amount={money_text(requested_amount)} "
                        f"> total={money_text(total)}"
                    )
                if current == ORDER_STATUS_REFUNDED:
                    existing_amount = (
                        _as_decimal(row["refund_amount"])
                        if row["refund_amount"] is not None
                        else None
                    )
                    if existing_amount is not None and requested_amount == existing_amount:
                        return self._hydrate_orders(cur, [row])[0]
                    raise MerchantConflictError(
                        "订单已退款"
                        f"（{money_text(existing_amount) if existing_amount is not None else '金额未知'}），"
                        "不能重复退款或改变退款金额"
                    )
                if current == ORDER_STATUS_CANCELLED:
                    raise MerchantConflictError("订单已取消，不能售后退款")
                if current not in (ORDER_STATUS_SHIPPED, ORDER_STATUS_COMPLETED):
                    if current in (ORDER_STATUS_CREATED, ORDER_STATUS_PAID):
                        raise MerchantConflictError(
                            f"当前状态 {current} 未发货，不能售后退款；"
                            "请使用 cancel_order(...) 取消订单（含模拟退款/库存补偿）"
                        )
                    raise MerchantInternalError(
                        f"订单 {order} 当前状态非法: {row['status']!r}"
                    )
                assignments: dict[str, Any] = {
                    "status": ORDER_STATUS_REFUNDED,
                    "refund_amount": money_text(requested_amount),
                    "refunded_at": now,
                }
                if request is not None:
                    assignments["refund_request_id"] = request
                set_sql = ", ".join(f"{column} = %s" for column in assignments)
                cur.execute(
                    f"UPDATE m_order SET {set_sql} WHERE order_id = %s AND merchant_id = %s",
                    (*assignments.values(), order, merchant),
                )
                if cur.rowcount != 1:
                    raise MerchantNotFoundError(f"订单不存在: {order}")
                cur.execute("SELECT * FROM m_order WHERE order_id = %s", (order,))
                return self._hydrate_orders(cur, [cur.fetchone()])[0]
        except BaseException as exc:  # noqa: BLE001 request_id 唯一索引并发兜底
            if not self._unique_violation(exc):
                raise
            raise MerchantConflictError(
                "request_id 已被其他退款请求占用，请重试或换用新的 request_id"
            ) from exc

    # ---------- 写路径：内部辅助 ----------
    def _resolve_write_lines(
        self,
        cur: Any,
        merchant: str,
        requested: list[dict[str, Any]],
        *,
        with_price: bool = False,
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        seen_skus: set[str] = set()
        for item in requested:
            sku_value = item["sku"]
            product_value = item["product_id"]
            if sku_value:
                cur.execute(
                    "SELECT s.sku, s.product_id, s.spec, s.price, s.status, "
                    "       p.title, p.status AS product_status "
                    "FROM m_sku s JOIN m_product p ON p.product_id = s.product_id "
                    "WHERE s.sku = %s AND s.merchant_id = %s",
                    (sku_value, merchant),
                )
                row = cur.fetchone()
                if row is None:
                    raise MerchantNotFoundError(
                        f"SKU 不存在或不属于该商家: {sku_value}"
                    )
            else:
                cur.execute(
                    "SELECT s.sku, s.product_id, s.spec, s.price, s.status, "
                    "       p.title, p.status AS product_status "
                    "FROM m_sku s JOIN m_product p ON p.product_id = s.product_id "
                    "WHERE s.product_id = %s AND s.merchant_id = %s "
                    "ORDER BY s.sku ASC",
                    (product_value, merchant),
                )
                rows = cur.fetchall()
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
        cur: Any,
        merchant: str,
        lines: list[dict[str, Any]],
        now: str,
    ) -> list[ReservationAllocation]:
        """按仓库顺序扣减库存；SELECT FOR UPDATE 锁行，确保并发不超卖。"""
        allocations: list[ReservationAllocation] = []
        # 按 SKU 排序加锁，避免两笔多 SKU 预占以相反顺序加锁造成死锁
        for line in sorted(lines, key=lambda value: value["sku"]):
            sku = line["sku"]
            need = int(line["quantity"])
            cur.execute(
                "SELECT warehouse_id, available_qty FROM m_inventory "
                "WHERE sku = %s AND merchant_id = %s "
                "ORDER BY warehouse_id ASC FOR UPDATE",
                (sku, merchant),
            )
            rows = cur.fetchall()
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
                cur.execute(
                    "UPDATE m_inventory SET available_qty = available_qty - %s, "
                    "reserved_qty = reserved_qty + %s, updated_at = %s "
                    "WHERE sku = %s AND warehouse_id = %s AND merchant_id = %s "
                    "AND available_qty >= %s",
                    (take, take, now, sku, row["warehouse_id"], merchant, take),
                )
                if cur.rowcount != 1:
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
        self, cur: Any, reservation: Reservation, now: str
    ) -> None:
        if not reservation.allocations:
            raise MerchantInternalError(
                f"预占缺少仓库扣减明细，无法恢复库存: {reservation.reservation_id}"
            )
        for allocation in reservation.allocations:
            cur.execute(
                "UPDATE m_inventory SET available_qty = available_qty + %s, "
                "reserved_qty = reserved_qty - %s, updated_at = %s "
                "WHERE sku = %s AND warehouse_id = %s AND merchant_id = %s "
                "AND reserved_qty >= %s",
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
            if cur.rowcount != 1:
                raise MerchantInternalError(
                    f"库存恢复失败（账实不一致）: {allocation.sku} @ "
                    f"{allocation.warehouse_id}（reservation={reservation.reservation_id}）"
                )

    def _consume_allocations(
        self, cur: Any, reservation: Reservation, now: str
    ) -> None:
        if not reservation.allocations:
            raise MerchantInternalError(
                f"预占缺少仓库扣减明细，无法提交: {reservation.reservation_id}"
            )
        for allocation in reservation.allocations:
            cur.execute(
                "UPDATE m_inventory SET reserved_qty = reserved_qty - %s, updated_at = %s "
                "WHERE sku = %s AND warehouse_id = %s AND merchant_id = %s "
                "AND reserved_qty >= %s",
                (
                    allocation.quantity,
                    now,
                    allocation.sku,
                    allocation.warehouse_id,
                    reservation.merchant_id,
                    allocation.quantity,
                ),
            )
            if cur.rowcount != 1:
                raise MerchantInternalError(
                    f"预占转出失败（账实不一致）: {allocation.sku} @ "
                    f"{allocation.warehouse_id}（reservation={reservation.reservation_id}）"
                )

    def _restore_committed_allocations(
        self, cur: Any, reservation: Reservation, now: str
    ) -> None:
        if not reservation.allocations:
            raise MerchantInternalError(
                f"预占缺少仓库扣减明细，无法恢复库存: {reservation.reservation_id}"
            )
        for allocation in reservation.allocations:
            cur.execute(
                "UPDATE m_inventory SET available_qty = available_qty + %s, updated_at = %s "
                "WHERE sku = %s AND warehouse_id = %s AND merchant_id = %s",
                (
                    allocation.quantity,
                    now,
                    allocation.sku,
                    allocation.warehouse_id,
                    reservation.merchant_id,
                ),
            )
            if cur.rowcount != 1:
                raise MerchantInternalError(
                    f"库存补偿失败（账实不一致）: {allocation.sku} @ "
                    f"{allocation.warehouse_id}（reservation={reservation.reservation_id}）"
                )

    def _cancel_order_row(
        self,
        cur: Any,
        row: Mapping[str, Any],
        *,
        now: str,
        request_id: str | None = None,
    ) -> Order:
        order_id = str(row["order_id"])
        merchant = str(row["merchant_id"])
        current = str(row["status"]).upper()
        if current == ORDER_STATUS_CANCELLED:
            return self._hydrate_orders(cur, [row])[0]
        if current not in (ORDER_STATUS_CREATED, ORDER_STATUS_PAID):
            raise MerchantConflictError(
                f"当前状态 {current} 不允许取消（仅 CREATED/PAID 可取消）"
            )

        cur.execute(
            "SELECT * FROM m_reservation "
            "WHERE order_id = %s AND merchant_id = %s AND status = %s "
            "FOR UPDATE",
            (order_id, merchant, RESERVATION_STATUS_COMMITTED),
        )
        reservation_rows = cur.fetchall()
        for reservation_row in reservation_rows:
            reservation = self._reservation_from_row(reservation_row)
            self._restore_committed_allocations(cur, reservation, now)
            cur.execute(
                "UPDATE m_reservation SET status = %s, updated_at = %s "
                "WHERE reservation_id = %s",
                (RESERVATION_STATUS_REVERSED, now, reservation.reservation_id),
            )

        is_paid = current == ORDER_STATUS_PAID
        total = _as_decimal(row["total_amount"])
        refund_amount = money_text(total) if is_paid else money_text(Decimal("0.00"))
        refunded_at = now if is_paid else None
        assignments: dict[str, Any] = {
            "status": ORDER_STATUS_CANCELLED,
            "cancelled_at": now,
            "refund_amount": refund_amount,
            "refunded_at": refunded_at,
        }
        if request_id is not None:
            assignments["cancel_request_id"] = request_id
        set_sql = ", ".join(f"{column} = %s" for column in assignments)
        cur.execute(
            f"UPDATE m_order SET {set_sql} WHERE order_id = %s AND merchant_id = %s",
            (*assignments.values(), order_id, merchant),
        )
        if cur.rowcount != 1:
            raise MerchantNotFoundError(f"订单不存在: {order_id}")
        cur.execute("SELECT * FROM m_order WHERE order_id = %s", (order_id,))
        return self._hydrate_orders(cur, [cur.fetchone()])[0]

    @staticmethod
    def _reservation_matches(
        existing: Reservation, lines: list[dict[str, Any]], buyer: str | None
    ) -> bool:
        if existing.buyer_id != buyer:
            return False
        requested = sorted((line["sku"], line["quantity"]) for line in lines)
        stored = sorted((item.sku, item.quantity) for item in existing.items)
        return requested == stored

    @staticmethod
    def _reservation_from_row(row: Mapping[str, Any]) -> Reservation:
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

    def _require_reservation_row(self, cur: Any, reservation_id: str) -> Reservation:
        cur.execute(
            "SELECT * FROM m_reservation WHERE reservation_id = %s", (reservation_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise MerchantInternalError(f"预占记录读取失败: {reservation_id}")
        return self._reservation_from_row(row)

    def _hydrate_orders(self, cur: Any, order_rows: list[Mapping[str, Any]]) -> list[Order]:
        if not order_rows:
            return []
        order_ids = [str(row["order_id"]) for row in order_rows]
        placeholders = ", ".join("%s" for _ in order_ids)
        cur.execute(
            "SELECT order_id, sku, product_id, title, quantity, unit_price, line_amount "
            f"FROM m_order_item WHERE order_id IN ({placeholders}) "
            "ORDER BY order_id ASC, line_no ASC",
            order_ids,
        )
        item_rows = cur.fetchall()
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
                    source_ref=row.get("source_ref"),
                    tracking_no=row.get("tracking_no"),
                    carrier=row.get("carrier"),
                    shipped_at=row.get("shipped_at"),
                    completed_at=row.get("completed_at"),
                    cancelled_at=row.get("cancelled_at"),
                    refund_amount=(
                        _as_decimal(row["refund_amount"])
                        if row.get("refund_amount") is not None
                        else None
                    ),
                    refunded_at=row.get("refunded_at"),
                )
            )
        return orders


__all__ = [
    "DEFAULT_SCHEMA",
    "PostgresMerchantRepository",
]
