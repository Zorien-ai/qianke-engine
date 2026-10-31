"""商家数据层 v1（可替换的 Merchant Repository：只读查询 + 受控写入）。

一句话定位
----------
这是**独立、可测试、可替换的商家数据层**：商品 / SKU / 库存 / 订单查询，
以及幂等的**库存预占（reserve/commit/release）、订单写入（create_order）、
订单生命周期（paid/shipped/completed/refunded）、取消（cancel_order）、
售后退款（refund_order，默认不恢复库存）与退货验收入库
（receive_return，按已提交预占恢复库存）**。
默认落在 SQLite（``QIANKE_MERCHANT_DB``），接口面向未来的真实 OMS / PostgreSQL。

⚠ 它**不是**真实 OMS：没有商家鉴权/支付对账；SQLite 写通道只是本地演示/测试实现。
生产接入必须实现 ``MerchantRepository``（只读）与 ``MerchantWriteRepository``（写）
两个协议并注册新的 adapter（见 ``docs/merchant-integration-v1.md``）。
真实交易写必须走 OMS 的受控接口 + 人工确认，不能由 Agent 直接写库。

快速使用
--------
    from rag_demo.merchant import get_merchant_repository, get_merchant_write_repository

    repo = get_merchant_repository()          # 只读：默认 SQLite，自动灌种子
    products = repo.list_products("m_tea_001", keyword="龙井", limit=10)

    writer = get_merchant_write_repository()  # 写：同一个 SQLite adapter（显式取写能力）
    held = writer.reserve_inventory(
        "m_tea_001", "RSV-1", [{"sku": "SKU-TEA-001-250G", "quantity": 2}], ttl_seconds=900
    )
    order = writer.create_order(
        "m_tea_001", "ORD-1", "b_1001",
        [{"sku": "SKU-TEA-001-250G", "quantity": 2}], "596.00",
    )
    writer.commit_reservation("m_tea_001", "RSV-1", order_id=order.order_id)
    writer.update_order_status("m_tea_001", order.order_id, "PAID")
    cancelled = writer.cancel_order("m_tea_001", order.order_id)

模块划分
--------
    models.py             数据模型（Product / SKU / Inventory / Reservation / Order…，金额 Decimal）
    limits.py             limit 钳制纯函数
    errors.py             结构化错误（稳定 code，写操作有 MERCHANT_STOCK / CONFLICT / EXPIRED…）
    repository.py         MerchantRepository（只读）+ MerchantWriteRepository（写）协议
    seeds.py              data/merchant/*.csv 读取 + 校验 + 规模下限
    sqlite_repository.py  默认 SQLite 实现（读查询 + 事务化预占/订单写入/状态机/取消退款）
    factory.py            后端注册 / 选择 / 缓存 / 写能力检查
"""
from __future__ import annotations

from .errors import (
    MerchantConfigurationError,
    MerchantConflictError,
    MerchantDataError,
    MerchantError,
    MerchantExpiredError,
    MerchantInternalError,
    MerchantInvalidError,
    MerchantNotFoundError,
    MerchantSeedError,
    MerchantStockError,
    MerchantUnavailableError,
)
from .factory import (
    available_backends,
    default_backend,
    get_merchant_repository,
    get_merchant_write_repository,
    register_repository_backend,
    reset_merchant_repository_cache,
)
from .limits import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, clamp_limit
from .models import (
    DEFAULT_CURRENCY,
    ORDER_STATUSES,
    ORDER_STATUS_REFUNDED,
    ORDER_STATUS_TRANSITIONS,
    RESERVATION_STATUSES,
    RESERVATION_STATUS_COMMITTED,
    RESERVATION_STATUS_EXPIRED,
    RESERVATION_STATUS_RELEASED,
    RESERVATION_STATUS_RESERVED,
    RESERVATION_STATUS_REVERSED,
    Inventory,
    InventoryRecord,
    Order,
    OrderItem,
    Product,
    Reservation,
    ReservationAllocation,
    ReservationItem,
    SKU,
    WarehouseStock,
)
from .repository import MerchantRepository, MerchantWriteRepository
from .seeds import SeedData, default_seed_dir, load_seed_data
from .postgres_repository import DEFAULT_SCHEMA as DEFAULT_PG_SCHEMA
from .postgres_repository import PostgresMerchantRepository
from .sqlite_repository import (
    DEFAULT_DB_FILENAME,
    DEFAULT_RESERVATION_TTL_SECONDS,
    MAX_RESERVATION_TTL_SECONDS,
    MAX_WRITE_ITEMS,
    SqliteMerchantRepository,
    default_db_path,
)

__all__ = [
    "DEFAULT_CURRENCY",
    "DEFAULT_DB_FILENAME",
    "DEFAULT_LIST_LIMIT",
    "DEFAULT_PG_SCHEMA",
    "DEFAULT_RESERVATION_TTL_SECONDS",
    "MAX_LIST_LIMIT",
    "MAX_RESERVATION_TTL_SECONDS",
    "MAX_WRITE_ITEMS",
    "ORDER_STATUSES",
    "ORDER_STATUS_REFUNDED",
    "ORDER_STATUS_TRANSITIONS",
    "RESERVATION_STATUSES",
    "RESERVATION_STATUS_COMMITTED",
    "RESERVATION_STATUS_EXPIRED",
    "RESERVATION_STATUS_RELEASED",
    "RESERVATION_STATUS_RESERVED",
    "RESERVATION_STATUS_REVERSED",
    "Inventory",
    "InventoryRecord",
    "MerchantConfigurationError",
    "MerchantConflictError",
    "MerchantDataError",
    "MerchantError",
    "MerchantExpiredError",
    "MerchantInternalError",
    "MerchantInvalidError",
    "MerchantNotFoundError",
    "MerchantRepository",
    "MerchantSeedError",
    "MerchantStockError",
    "MerchantUnavailableError",
    "MerchantWriteRepository",
    "Order",
    "OrderItem",
    "PostgresMerchantRepository",
    "Product",
    "Reservation",
    "ReservationAllocation",
    "ReservationItem",
    "SKU",
    "SeedData",
    "SqliteMerchantRepository",
    "WarehouseStock",
    "available_backends",
    "clamp_limit",
    "default_backend",
    "default_db_path",
    "default_seed_dir",
    "get_merchant_repository",
    "get_merchant_write_repository",
    "load_seed_data",
    "register_repository_backend",
    "reset_merchant_repository_cache",
]
