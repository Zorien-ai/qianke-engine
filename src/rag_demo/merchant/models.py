"""商家数据层 v1 的数据模型：商品 / SKU / 库存 / 订单。

设计约定
--------
1. **只读快照**：所有 dataclass 都是 ``frozen=True``。查询结果代表「查的那一刻的数据」，
   调用方不应在内存里修改它（真实库存/订单状态由 OMS 负责写，v1 数据层明确只读）。
2. **金额用 Decimal**：单价、订单金额、行小计一律 ``Decimal``，不经过 float。
   金额一旦变成二进制浮点，对账时会出现 0.1+0.2 类误差；商家数据层必须能逐分核对。
   ``to_dict()`` 统一输出十进制字符串（如 ``"298.00"``），交给 API / LLM 不丢精度。
3. **时间用 ISO-8601 文本**：v1 不建 datetime 对象、不做时区换算，字段原样来自 OMS 映射
   （种子数据带 ``+08:00``）。排序由 adapter 在 SQL 层完成。
4. **模型不碰数据库**：本模块只定义结构，adapter（SQLite / 未来 PG/OMS）负责映射。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# ---------- 商品状态 ----------
PRODUCT_STATUS_ACTIVE = "ACTIVE"
PRODUCT_STATUS_INACTIVE = "INACTIVE"

# ---------- 订单状态（常见值；v1 不强制白名单，真实 OMS 可能自有关单/退款态） ----------
ORDER_STATUS_CREATED = "CREATED"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_SHIPPED = "SHIPPED"
ORDER_STATUS_COMPLETED = "COMPLETED"
ORDER_STATUS_CANCELLED = "CANCELLED"
ORDER_STATUSES: tuple[str, ...] = (
    ORDER_STATUS_CREATED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_SHIPPED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_CANCELLED,
)

DEFAULT_CURRENCY = "CNY"

# ---------- 库存预占状态（task-43） ----------
# RESERVED  : 预占中（available 已扣、reserved 已加），可 release 或 commit
# COMMITTED : 已提交为订单（available 保持扣减，reserved 已转出）
# RELEASED  : 已主动释放（库存已恢复）
# EXPIRED   : 已过期（库存已恢复；由 commit/reserve/release 懒触发）
RESERVATION_STATUS_RESERVED = "RESERVED"
RESERVATION_STATUS_COMMITTED = "COMMITTED"
RESERVATION_STATUS_RELEASED = "RELEASED"
RESERVATION_STATUS_EXPIRED = "EXPIRED"
RESERVATION_STATUSES: tuple[str, ...] = (
    RESERVATION_STATUS_RESERVED,
    RESERVATION_STATUS_COMMITTED,
    RESERVATION_STATUS_RELEASED,
    RESERVATION_STATUS_EXPIRED,
)



def money_text(value: Decimal) -> str:
    """Decimal 金额 → 十进制字符串（保留最小位数，例如 Decimal('298.00') → '298.00'）。"""
    return format(value, "f")


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class Product:
    """商家商品（SPU 粒度；具体规格/价格在 SKU 上）。"""

    merchant_id: str
    product_id: str
    title: str
    category: str
    brand: str | None
    status: str
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "product_id": self.product_id,
            "title": self.title,
            "category": self.category,
            "brand": self.brand,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SKU:
    """可售单元：一个商品下的一档规格（50g 罐装 / M 码 / 专业版…）。"""

    merchant_id: str
    sku: str
    product_id: str
    spec: str
    price: Decimal
    status: str = PRODUCT_STATUS_ACTIVE
    barcode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "sku": self.sku,
            "product_id": self.product_id,
            "spec": self.spec,
            "price": money_text(self.price),
            "status": self.status,
            "barcode": self.barcode,
        }


@dataclass(frozen=True)
class InventoryRecord:
    """单个仓库下某个 SKU 的库存记录（v1 库存表的一行）。"""

    merchant_id: str
    sku: str
    warehouse_id: str
    available_qty: int
    reserved_qty: int
    safety_stock: int
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "sku": self.sku,
            "warehouse_id": self.warehouse_id,
            "available_qty": self.available_qty,
            "reserved_qty": self.reserved_qty,
            "safety_stock": self.safety_stock,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class WarehouseStock:
    """聚合视图里的单仓库存。"""

    warehouse_id: str
    available_qty: int
    reserved_qty: int
    safety_stock: int
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "warehouse_id": self.warehouse_id,
            "available_qty": self.available_qty,
            "reserved_qty": self.reserved_qty,
            "safety_stock": self.safety_stock,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Inventory:
    """某个 SKU 的跨仓库存汇总（``get_inventory(sku)`` 的返回）。"""

    merchant_id: str
    sku: str
    warehouses: tuple[WarehouseStock, ...]

    @property
    def available_qty(self) -> int:
        """可售总量（各仓 available 之和）。"""
        return sum(w.available_qty for w in self.warehouses)

    @property
    def reserved_qty(self) -> int:
        """已锁定/占用总量（各仓 reserved 之和）。"""
        return sum(w.reserved_qty for w in self.warehouses)

    @property
    def safety_stock(self) -> int:
        """安全库存总量（各仓之和；v1 仅展示，不做自动补货）。"""
        return sum(w.safety_stock for w in self.warehouses)

    @property
    def updated_at(self) -> str:
        """最近更新时间（ISO-8601 文本，取各仓最大值；全为空时返回空串）。"""
        return max((w.updated_at for w in self.warehouses), default="")

    @property
    def in_stock(self) -> bool:
        """是否还有可售库存（``available_qty > 0``）。"""
        return self.available_qty > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "sku": self.sku,
            "available_qty": self.available_qty,
            "reserved_qty": self.reserved_qty,
            "safety_stock": self.safety_stock,
            "in_stock": self.in_stock,
            "updated_at": self.updated_at,
            "warehouses": [w.to_dict() for w in self.warehouses],
        }


@dataclass(frozen=True)
class ReservationItem:
    """预占请求里的一行：SKU + 数量（商品由 SKU 反查）。"""

    sku: str
    product_id: str
    quantity: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "product_id": self.product_id,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class ReservationAllocation:
    """某个仓库被扣减的明细：释放/提交时按它精确回滚。"""

    sku: str
    warehouse_id: str
    quantity: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "warehouse_id": self.warehouse_id,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class Reservation:
    """库存预占记录（可提交为订单 / 主动释放 / 过期自动释放）。"""

    merchant_id: str
    reservation_id: str
    status: str
    expires_at: str
    created_at: str
    items: tuple[ReservationItem, ...] = ()
    allocations: tuple[ReservationAllocation, ...] = ()
    buyer_id: str | None = None
    order_id: str | None = None

    @property
    def item_count(self) -> int:
        """预占商品件数（各行 quantity 之和）。"""
        return sum(item.quantity for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "reservation_id": self.reservation_id,
            "buyer_id": self.buyer_id,
            "status": self.status,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "order_id": self.order_id,
            "item_count": self.item_count,
            "items": [item.to_dict() for item in self.items],
            "allocations": [allocation.to_dict() for allocation in self.allocations],
        }


@dataclass(frozen=True)
class OrderItem:
    """订单行（下单那一刻的快照：标题/单价不会随商品后续改价而变）。"""

    sku: str
    product_id: str
    title: str
    quantity: int
    unit_price: Decimal
    line_amount: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "product_id": self.product_id,
            "title": self.title,
            "quantity": self.quantity,
            "unit_price": money_text(self.unit_price),
            "line_amount": money_text(self.line_amount),
        }


@dataclass(frozen=True)
class Order:
    """商家订单（含订单行快照）。

    ``source_ref``：可选来源引用（如 quote_id / agent action id），便于把订单追回到
    产生它的业务动作；真实 OMS 对接时应映射为对方的来源单号。
    """

    merchant_id: str
    order_id: str
    buyer_id: str
    status: str
    total_amount: Decimal
    currency: str = DEFAULT_CURRENCY
    channel: str | None = None
    created_at: str = ""
    paid_at: str | None = None
    items: tuple[OrderItem, ...] = ()
    source_ref: str | None = None

    @property
    def item_count(self) -> int:
        """商品件数（各行 quantity 之和）。"""
        return sum(item.quantity for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "order_id": self.order_id,
            "buyer_id": self.buyer_id,
            "status": self.status,
            "total_amount": money_text(self.total_amount),
            "currency": self.currency,
            "channel": self.channel,
            "created_at": self.created_at,
            "paid_at": self.paid_at,
            "source_ref": self.source_ref,
            "item_count": self.item_count,
            "items": [item.to_dict() for item in self.items],
        }


__all__ = [
    "DEFAULT_CURRENCY",
    "Inventory",
    "InventoryRecord",
    "ORDER_STATUSES",
    "ORDER_STATUS_CANCELLED",
    "ORDER_STATUS_COMPLETED",
    "ORDER_STATUS_CREATED",
    "ORDER_STATUS_PAID",
    "ORDER_STATUS_SHIPPED",
    "Order",
    "OrderItem",
    "PRODUCT_STATUS_ACTIVE",
    "PRODUCT_STATUS_INACTIVE",
    "Product",
    "RESERVATION_STATUSES",
    "RESERVATION_STATUS_COMMITTED",
    "RESERVATION_STATUS_EXPIRED",
    "RESERVATION_STATUS_RELEASED",
    "RESERVATION_STATUS_RESERVED",
    "Reservation",
    "ReservationAllocation",
    "ReservationItem",
    "SKU",
    "WarehouseStock",
    "money_text",
]
