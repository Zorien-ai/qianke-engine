"""商家种子数据的读取、解析与校验（v1）。

数据属于**数据，不属于业务代码**：商品/库存/订单的数量、价格、状态全部来自
``data/merchant/*.csv``，业务函数里不写任何「8 个商品」「20 条库存」这样的常量。
本模块只负责「把文件读成模型，并把明显的坏数据挡在入库之前」。

校验清单（任何一条不满足都抛 :class:`MerchantSeedError`，错误里带文件名与行号）：
  1. 文件/列齐全，数字与金额可解析，数量非负、订单数量为正；
  2. 主键唯一：product_id / sku / order_id；
  3. 引用完整：SKU→商品、库存→SKU、订单行→SKU、订单行→订单；且商家归属一致；
  4. 每个商品至少一个 SKU；
  5. 订单金额 == 所有订单行小计之和；行小计 == 数量 × 单价（Decimal 精确比较）；
  6. 规模下限：至少 8 个商品、20 条库存记录、5 个订单（v1 验收要求）。

为什么校验放在「读种子」这一层而不是 Repository：
   真实 OMS 适配器不会读这些 CSV，但**同一套模型/契约**要成立。校验只有种子路径需要，
   放在这里可以让 SQLite adapter 保持薄，也让测试可以脱离数据库直接验证坏数据会被拒绝。
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .errors import MerchantSeedError
from .models import (
    DEFAULT_CURRENCY,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_SHIPPED,
    PRODUCT_STATUS_ACTIVE,
    InventoryRecord,
    Order,
    OrderItem,
    Product,
    SKU,
)

# ---- v1 验收要求的种子规模下限（数据在工作区 data/merchant，不写进业务函数）----
MIN_PRODUCTS = 8
MIN_INVENTORY_RECORDS = 20
MIN_ORDERS = 5

# 仓库根：merchant/seeds.py -> merchant -> rag_demo -> src -> 根
_ROOT_DIR = Path(__file__).resolve().parents[3]

_SEED_FILES: dict[str, str] = {
    "products": "products.csv",
    "skus": "skus.csv",
    "inventory": "inventory.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
}

_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "products": (
        "merchant_id", "product_id", "title", "category", "brand", "status", "created_at",
    ),
    "skus": (
        "merchant_id", "sku", "product_id", "spec", "price", "status", "barcode",
    ),
    "inventory": (
        "merchant_id", "sku", "warehouse_id", "available_qty", "reserved_qty",
        "safety_stock", "updated_at",
    ),
    "orders": (
        "merchant_id", "order_id", "buyer_id", "status", "total_amount", "currency",
        "channel", "created_at", "paid_at",
    ),
    "order_items": (
        "order_id", "sku", "title", "quantity", "unit_price", "line_amount",
    ),
}


def default_seed_dir() -> Path:
    """种子目录：``QIANKE_MERCHANT_SEED_DIR`` 可覆盖，默认 ``<仓库根>/data/merchant``。"""
    raw = (os.environ.get("QIANKE_MERCHANT_SEED_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _ROOT_DIR / "data" / "merchant"


@dataclass(frozen=True)
class SeedData:
    """一份种子数据的完整快照（模型对象，不含数据库概念）。"""

    products: tuple[Product, ...]
    skus: tuple[SKU, ...]
    inventory_records: tuple[InventoryRecord, ...]
    orders: tuple[Order, ...]
    source_dir: str
    file_sha256: dict[str, str] = field(default_factory=dict)

    @property
    def order_items(self) -> tuple[OrderItem, ...]:
        """所有订单行（按订单聚合后的展平视图，便于计数/插入）。"""
        return tuple(item for order in self.orders for item in order.items)

    def counts(self) -> dict[str, int]:
        """各实体数量（全部来自数据本身，不写死）。"""
        return {
            "products": len(self.products),
            "skus": len(self.skus),
            "inventory_records": len(self.inventory_records),
            "orders": len(self.orders),
            "order_items": len(self.order_items),
        }


# ==================== CSV 读取 ====================
def _read_rows(path: Path, required: Iterable[str], kind: str) -> list[dict[str, str]]:
    filename = _SEED_FILES[kind]
    if not path.is_file():
        raise MerchantSeedError(f"商家种子文件缺失: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:  # 文件被占用/权限不足
        raise MerchantSeedError(f"读取商家种子文件失败（{filename}）: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise MerchantSeedError(f"商家种子文件为空或没有表头: {filename}")
    missing = [column for column in required if column not in reader.fieldnames]
    if missing:
        raise MerchantSeedError(f"{filename} 缺少必需列: {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    for line_no, row in enumerate(reader, start=2):
        # DictReader 会把空行读成 {None: [...]} 或全空值，跳过
        if not row or all((value or "").strip() == "" for value in row.values()):
            continue
        cleaned = {str(key).strip(): (value or "").strip() for key, value in row.items() if key}
        cleaned["__line__"] = str(line_no)
        rows.append(cleaned)
    if not rows:
        raise MerchantSeedError(f"{filename} 没有数据行")
    return rows


# ==================== 字段解析（错误带文件+行号） ====================
def _text(row: dict[str, str], column: str, filename: str, *, required: bool = True) -> str:
    value = row.get(column, "")
    if required and not value:
        raise MerchantSeedError(f"{filename} 第 {row['__line__']} 行: 列「{column}」不能为空")
    return value


def _optional_text(row: dict[str, str], column: str) -> str | None:
    value = (row.get(column) or "").strip()
    return value or None


def _whole_number(row: dict[str, str], column: str, filename: str, *, minimum: int = 0) -> int:
    raw = _text(row, column, filename)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise MerchantSeedError(
            f"{filename} 第 {row['__line__']} 行: 列「{column}」不是整数（收到 {raw!r}）"
        ) from None
    if value < minimum:
        raise MerchantSeedError(
            f"{filename} 第 {row['__line__']} 行: 列「{column}」不能小于 {minimum}（收到 {value}）"
        )
    return value


def _money(row: dict[str, str], column: str, filename: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    raw = _text(row, column, filename)
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        raise MerchantSeedError(
            f"{filename} 第 {row['__line__']} 行: 列「{column}」不是合法金额（收到 {raw!r}）"
        ) from None
    if not value.is_finite():
        raise MerchantSeedError(
            f"{filename} 第 {row['__line__']} 行: 列「{column}」不是有限金额（收到 {raw!r}）"
        )
    if value < minimum:
        raise MerchantSeedError(
            f"{filename} 第 {row['__line__']} 行: 列「{column}」不能小于 {minimum}（收到 {value}）"
        )
    return value


# ==================== 各类实体解析 ====================
def _parse_products(rows: list[dict[str, str]]) -> list[Product]:
    filename = _SEED_FILES["products"]
    products = [
        Product(
            merchant_id=_text(row, "merchant_id", filename),
            product_id=_text(row, "product_id", filename),
            title=_text(row, "title", filename),
            category=_text(row, "category", filename),
            brand=_optional_text(row, "brand"),
            status=_text(row, "status", filename).upper(),
            created_at=_optional_text(row, "created_at"),
        )
        for row in rows
    ]
    return products


def _parse_skus(rows: list[dict[str, str]]) -> list[SKU]:
    filename = _SEED_FILES["skus"]
    skus = []
    for row in rows:
        status = (_optional_text(row, "status") or PRODUCT_STATUS_ACTIVE).upper()
        skus.append(
            SKU(
                merchant_id=_text(row, "merchant_id", filename),
                sku=_text(row, "sku", filename),
                product_id=_text(row, "product_id", filename),
                spec=_text(row, "spec", filename),
                price=_money(row, "price", filename),
                status=status,
                barcode=_optional_text(row, "barcode"),
            )
        )
    return skus


def _parse_inventory(rows: list[dict[str, str]]) -> list[InventoryRecord]:
    filename = _SEED_FILES["inventory"]
    return [
        InventoryRecord(
            merchant_id=_text(row, "merchant_id", filename),
            sku=_text(row, "sku", filename),
            warehouse_id=_text(row, "warehouse_id", filename),
            available_qty=_whole_number(row, "available_qty", filename),
            reserved_qty=_whole_number(row, "reserved_qty", filename),
            safety_stock=_whole_number(row, "safety_stock", filename),
            updated_at=_text(row, "updated_at", filename),
        )
        for row in rows
    ]


def _optional_timestamp(row: dict[str, str], column: str, filename: str) -> str | None:
    """可选 ISO-8601 时间列（paid_at / shipped_at / completed_at）：空值允许，非空必须可解析。"""
    raw = _optional_text(row, column)
    if raw is None:
        return None
    try:
        datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        raise MerchantSeedError(
            f"{filename} 第 {row['__line__']} 行: 列「{column}」不是合法 ISO-8601 时间（收到 {raw!r}）"
        ) from None
    return raw


def _parse_order_header(row: dict[str, str]) -> dict[str, Any]:
    filename = _SEED_FILES["orders"]
    return {
        "merchant_id": _text(row, "merchant_id", filename),
        "order_id": _text(row, "order_id", filename),
        "buyer_id": _text(row, "buyer_id", filename),
        "status": _text(row, "status", filename).upper(),
        "total_amount": _money(row, "total_amount", filename),
        "currency": (_optional_text(row, "currency") or DEFAULT_CURRENCY).upper(),
        "channel": _optional_text(row, "channel"),
        "created_at": _text(row, "created_at", filename),
        "paid_at": _optional_timestamp(row, "paid_at", filename),
        # 物流/生命周期字段（task-45）：可选列，缺省空值兼容旧种子文件
        "tracking_no": _optional_text(row, "tracking_no"),
        "carrier": _optional_text(row, "carrier"),
        "shipped_at": _optional_timestamp(row, "shipped_at", filename),
        "completed_at": _optional_timestamp(row, "completed_at", filename),
    }


def _parse_order_item(row: dict[str, str]) -> tuple[str, OrderItem]:
    filename = _SEED_FILES["order_items"]
    order_id = _text(row, "order_id", filename)
    quantity = _whole_number(row, "quantity", filename, minimum=1)
    unit_price = _money(row, "unit_price", filename)
    line_amount = _money(row, "line_amount", filename)
    if line_amount != unit_price * quantity:
        raise MerchantSeedError(
            f"{filename} 第 {row['__line__']} 行: 行小计 {line_amount} != 单价 {unit_price} × 数量 {quantity}"
        )
    item = OrderItem(
        sku=_text(row, "sku", filename),
        product_id="",  # 由 sku 反查补齐（见 _build_orders）
        title=_text(row, "title", filename),
        quantity=quantity,
        unit_price=unit_price,
        line_amount=line_amount,
    )
    return order_id, item


def _build_orders(
    header_rows: list[dict[str, str]],
    item_rows: list[dict[str, str]],
    sku_by_id: dict[str, SKU],
) -> list[Order]:
    headers = [_parse_order_header(row) for row in header_rows]
    items_by_order: dict[str, list[OrderItem]] = {}
    for row in item_rows:
        order_id, item = _parse_order_item(row)
        sku = sku_by_id.get(item.sku)
        if sku is not None:
            item = OrderItem(
                sku=item.sku,
                product_id=sku.product_id,
                title=item.title,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_amount=item.line_amount,
            )
        items_by_order.setdefault(order_id, []).append(item)

    orders: list[Order] = []
    for header in headers:
        items = tuple(items_by_order.get(header["order_id"], ()))
        orders.append(
            Order(
                merchant_id=header["merchant_id"],
                order_id=header["order_id"],
                buyer_id=header["buyer_id"],
                status=header["status"],
                total_amount=header["total_amount"],
                currency=header["currency"],
                channel=header["channel"],
                created_at=header["created_at"],
                paid_at=header["paid_at"],
                items=items,
                tracking_no=header["tracking_no"],
                carrier=header["carrier"],
                shipped_at=header["shipped_at"],
                completed_at=header["completed_at"],
            )
        )
    return orders


# ==================== 校验 ====================
def _validate(
    products: list[Product],
    skus: list[SKU],
    inventory_records: list[InventoryRecord],
    orders: list[Order],
) -> None:
    issues: list[str] = []

    product_by_id: dict[str, Product] = {}
    for product in products:
        if product.product_id in product_by_id:
            issues.append(f"商品 ID 重复: {product.product_id}")
        product_by_id[product.product_id] = product

    sku_by_id: dict[str, SKU] = {}
    skus_per_product: dict[str, int] = {}
    for sku in skus:
        if sku.sku in sku_by_id:
            issues.append(f"SKU 重复: {sku.sku}")
            continue
        sku_by_id[sku.sku] = sku
        product = product_by_id.get(sku.product_id)
        if product is None:
            issues.append(f"SKU {sku.sku} 引用了不存在的商品 {sku.product_id}")
        elif product.merchant_id != sku.merchant_id:
            issues.append(
                f"SKU {sku.sku} 的商家 {sku.merchant_id} 与商品 {sku.product_id} 的商家 "
                f"{product.merchant_id} 不一致"
            )
        skus_per_product[sku.product_id] = skus_per_product.get(sku.product_id, 0) + 1

    for product in products:
        if skus_per_product.get(product.product_id, 0) == 0:
            issues.append(f"商品 {product.product_id} 没有任何 SKU")

    inventory_keys: set[tuple[str, str]] = set()
    for record in inventory_records:
        key = (record.sku, record.warehouse_id)
        if key in inventory_keys:
            issues.append(f"库存记录重复: {record.sku} @ {record.warehouse_id}")
        inventory_keys.add(key)
        sku = sku_by_id.get(record.sku)
        if sku is None:
            issues.append(f"库存记录引用了不存在的 SKU: {record.sku}")
        elif sku.merchant_id != record.merchant_id:
            issues.append(
                f"库存记录 {record.sku} 的商家 {record.merchant_id} 与 SKU 的商家 "
                f"{sku.merchant_id} 不一致"
            )

    order_by_id: dict[str, Order] = {}
    # 物流单号全局唯一（同一单号不能挂在两笔订单上）——真实面单号天然唯一
    seen_tracking: dict[str, str] = {}
    for order in orders:
        if order.order_id in order_by_id:
            issues.append(f"订单 ID 重复: {order.order_id}")
            continue
        order_by_id[order.order_id] = order
        if not order.items:
            issues.append(f"订单 {order.order_id} 没有任何订单行")
            continue
        line_sum = Decimal("0")
        for item in order.items:
            sku = sku_by_id.get(item.sku)
            if sku is None:
                issues.append(f"订单 {order.order_id} 的订单行引用了不存在的 SKU: {item.sku}")
                continue
            if sku.merchant_id != order.merchant_id:
                issues.append(
                    f"订单 {order.order_id} 的商家 {order.merchant_id} 与商品 {item.sku} 的商家 "
                    f"{sku.merchant_id} 不一致"
                )
            line_sum += item.line_amount
        if line_sum != order.total_amount:
            issues.append(
                f"订单 {order.order_id} 金额不一致: 订单总额 {order.total_amount} != "
                f"订单行合计 {line_sum}"
            )

        # ---- 状态机 / 物流字段一致性（task-45）----
        # SHIPPED / COMPLETED 必须有物流单号与发货时间；COMPLETED 还必须有完成时间。
        # 其它状态允许物流字段为空（旧种子只有 PAID/CREATED/CANCELLED 时完全兼容）。
        status = (order.status or "").upper()
        if status in (ORDER_STATUS_SHIPPED, ORDER_STATUS_COMPLETED):
            if not order.tracking_no:
                issues.append(f"订单 {order.order_id} 状态 {status} 必须有 tracking_no")
            else:
                previous = seen_tracking.get(order.tracking_no)
                if previous is not None and previous != order.order_id:
                    issues.append(
                        f"物流单号重复: {order.tracking_no}（订单 {previous} 与 {order.order_id}）"
                    )
                seen_tracking[order.tracking_no] = order.order_id
            if not order.shipped_at:
                issues.append(f"订单 {order.order_id} 状态 {status} 必须有 shipped_at")
        if status == ORDER_STATUS_COMPLETED and not order.completed_at:
            issues.append(f"订单 {order.order_id} 状态 COMPLETED 必须有 completed_at")
        if order.shipped_at and order.completed_at:
            try:
                shipped = datetime.fromisoformat(order.shipped_at)
                completed = datetime.fromisoformat(order.completed_at)
                if completed < shipped:
                    issues.append(
                        f"订单 {order.order_id} completed_at 早于 shipped_at"
                    )
            except (TypeError, ValueError):
                pass  # 时间格式问题已由 _optional_timestamp 在解析阶段报错

    if len(products) < MIN_PRODUCTS:
        issues.append(f"商品数量不足: {len(products)} < {MIN_PRODUCTS}（v1 种子要求）")
    if len(inventory_records) < MIN_INVENTORY_RECORDS:
        issues.append(
            f"库存记录不足: {len(inventory_records)} < {MIN_INVENTORY_RECORDS}（v1 种子要求）"
        )
    if len(orders) < MIN_ORDERS:
        issues.append(f"订单数量不足: {len(orders)} < {MIN_ORDERS}（v1 种子要求）")

    if issues:
        preview = "；".join(issues[:10])
        more = f"（另有 {len(issues) - 10} 条问题未展示）" if len(issues) > 10 else ""
        raise MerchantSeedError("商家种子数据校验失败：" + preview + more)


# ==================== 入口 ====================
def load_seed_data(seed_dir: str | Path | None = None) -> SeedData:
    """读取并校验一份种子数据，返回模型快照。

    参数:
        seed_dir: 种子目录；None → :func:`default_seed_dir`
    异常:
        MerchantSeedError: 文件缺失/列缺失/解析失败/引用不一致/金额不一致/规模不足
    """
    directory = Path(seed_dir).expanduser() if seed_dir else default_seed_dir()
    if not directory.is_dir():
        raise MerchantSeedError(f"商家种子目录不存在: {directory}")

    file_sha256: dict[str, str] = {}
    rows_by_kind: dict[str, list[dict[str, str]]] = {}
    for kind, filename in _SEED_FILES.items():
        path = directory / filename
        if not path.is_file():
            raise MerchantSeedError(f"商家种子文件缺失: {path}")
        try:
            file_sha256[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise MerchantSeedError(f"读取商家种子文件失败（{filename}）: {exc}") from exc
        rows_by_kind[kind] = _read_rows(path, _REQUIRED_COLUMNS[kind], kind)

    # 订单行必须挂在存在的订单上（_build_orders 只按 header 聚合，孤立行会被静默丢弃，先检查）
    known_order_ids = {
        (row.get("order_id") or "").strip() for row in rows_by_kind["orders"]
    }
    orphan_order_lines = sorted(
        {
            (row.get("order_id") or "").strip()
            for row in rows_by_kind["order_items"]
            if (row.get("order_id") or "").strip() not in known_order_ids
        }
    )
    if orphan_order_lines:
        raise MerchantSeedError(
            "order_items.csv 引用了不存在的订单: " + ", ".join(orphan_order_lines[:5])
        )

    products = _parse_products(rows_by_kind["products"])
    skus = _parse_skus(rows_by_kind["skus"])
    inventory_records = _parse_inventory(rows_by_kind["inventory"])
    sku_by_id = {sku.sku: sku for sku in skus}
    orders = _build_orders(rows_by_kind["orders"], rows_by_kind["order_items"], sku_by_id)
    _validate(products, skus, inventory_records, orders)

    return SeedData(
        products=tuple(products),
        skus=tuple(skus),
        inventory_records=tuple(inventory_records),
        orders=tuple(orders),
        source_dir=str(directory),
        file_sha256=file_sha256,
    )


__all__ = [
    "MIN_INVENTORY_RECORDS",
    "MIN_ORDERS",
    "MIN_PRODUCTS",
    "SeedData",
    "default_seed_dir",
    "load_seed_data",
]
