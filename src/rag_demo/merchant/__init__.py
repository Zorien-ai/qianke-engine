"""商家数据层 v1（可替换的 Merchant Repository）。

一句话定位
----------
这是**独立、可测试、可替换的商家数据层**：商品 / SKU / 库存 / 订单的只读查询，
默认落在 SQLite 种子库（``QIANKE_MERCHANT_DB``），接口面向未来的真实 OMS / PostgreSQL。

⚠ 它**不是**真实 OMS 对接：没有商家鉴权、没有订单写入、没有库存预占，
种子数据是工作区里的确定性样例。生产接入必须实现 ``MerchantRepository`` 协议并注册
新的 adapter（见 ``docs/merchant-integration-v1.md``）。

快速使用
--------
    from rag_demo.merchant import get_merchant_repository

    repo = get_merchant_repository()          # 默认 SQLite，自动灌种子
    products = repo.list_products("m_tea_001", keyword="龙井", limit=10)
    sku = repo.get_product_sku("SKU-TEA-001-250G")
    inventory = repo.get_inventory("SKU-GEAR-002-PRO")   # available_qty == 0
    orders = repo.list_orders("m_tea_001", status="PAID", limit=20)
    order = repo.get_order("ORD-20261001-0001", merchant_id="m_tea_001")

模块划分
--------
    models.py             数据模型（frozen dataclass，金额 Decimal）
    limits.py             limit 钳制纯函数
    errors.py             结构化错误（稳定 code）
    repository.py         MerchantRepository 协议（跨 adapter 契约）
    seeds.py              data/merchant/*.csv 读取 + 校验 + 规模下限
    sqlite_repository.py  默认 SQLite 实现（只读查询 + 种子初始化）
    factory.py            后端注册 / 选择 / 缓存
"""
from __future__ import annotations

from .errors import (
    MerchantConfigurationError,
    MerchantDataError,
    MerchantError,
    MerchantSeedError,
    MerchantUnavailableError,
)
from .factory import (
    available_backends,
    default_backend,
    get_merchant_repository,
    register_repository_backend,
    reset_merchant_repository_cache,
)
from .limits import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, clamp_limit
from .models import (
    DEFAULT_CURRENCY,
    ORDER_STATUSES,
    Inventory,
    InventoryRecord,
    Order,
    OrderItem,
    Product,
    SKU,
    WarehouseStock,
)
from .repository import MerchantRepository
from .seeds import SeedData, default_seed_dir, load_seed_data
from .sqlite_repository import DEFAULT_DB_FILENAME, SqliteMerchantRepository, default_db_path

__all__ = [
    "DEFAULT_CURRENCY",
    "DEFAULT_DB_FILENAME",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "ORDER_STATUSES",
    "Inventory",
    "InventoryRecord",
    "MerchantConfigurationError",
    "MerchantDataError",
    "MerchantError",
    "MerchantRepository",
    "MerchantSeedError",
    "MerchantUnavailableError",
    "Order",
    "OrderItem",
    "Product",
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
    "load_seed_data",
    "register_repository_backend",
    "reset_merchant_repository_cache",
]
