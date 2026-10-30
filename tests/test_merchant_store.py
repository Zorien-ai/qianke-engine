# -*- coding: utf-8 -*-
"""商家数据层 v1 单测（SQLite 种子库，离线，不连 PG / 不加载模型）。

覆盖：
- 种子数据规模下限（≥8 商品 / ≥20 库存记录 / ≥5 订单）与完整性；
- Repository 初始化灌种子、缓存/重置、env 路径覆盖；
- 商品 / SKU / 库存 / 订单 查询；
- **租户隔离**（跨商家查不到、get_* 的作用域校验、缺 merchant_id 失败关闭）；
- 无库存 vs 不存在、limit 钳制（纯函数 + 查询路径）；
- 可替换后端注册（Fake adapter 走同一协议）；
- 坏种子（引用缺失 / 规模不足 / 目录不存在）被结构化错误拒绝。
"""
from __future__ import annotations

import shutil
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from rag_demo.merchant import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MerchantConfigurationError,
    MerchantDataError,
    MerchantRepository,
    MerchantSeedError,
    MerchantUnavailableError,
    clamp_limit,
    default_db_path,
    get_merchant_repository,
    load_seed_data,
    register_repository_backend,
    reset_merchant_repository_cache,
)
from rag_demo.merchant import seeds as merchant_seeds


# ==================== fixtures ====================
@pytest.fixture()
def merchant_db(tmp_path, monkeypatch):
    """每个测试一个隔离的 SQLite 文件；结束后清掉工厂缓存。"""
    db_path = tmp_path / "merchant.sqlite"
    monkeypatch.setenv("QIANKE_MERCHANT_DB", str(db_path))
    reset_merchant_repository_cache()
    try:
        yield db_path
    finally:
        reset_merchant_repository_cache()


@pytest.fixture()
def repo(merchant_db):
    repository = get_merchant_repository()
    try:
        yield repository
    finally:
        repository.close()


@pytest.fixture(scope="module")
def seed():
    """真实种子文件（data/merchant）加载一次。"""
    return load_seed_data()


def _merchants(seed) -> list[str]:
    return sorted({product.merchant_id for product in seed.products})


# ==================== 1. 种子数据：规模下限 + 完整性 ====================
def test_seed_meets_v1_minimums(seed):
    counts = seed.counts()
    assert counts["products"] >= merchant_seeds.MIN_PRODUCTS >= 8
    assert counts["inventory_records"] >= merchant_seeds.MIN_INVENTORY_RECORDS >= 20
    assert counts["orders"] >= merchant_seeds.MIN_ORDERS >= 5
    # SKU 与订单行是派生实体，至少不能为空
    assert counts["skus"] > 0
    assert counts["order_items"] >= counts["orders"]
    # 5 份种子文件都读到了（用于 diagnostics 的指纹）
    assert len(seed.file_sha256) == 5


def test_seed_order_totals_are_internally_consistent(seed):
    """订单总额 == 各订单行小计之和；行小计 == 单价 × 数量（Decimal 精确比较）。"""
    for order in seed.orders:
        assert order.items, f"订单 {order.order_id} 没有订单行"
        line_sum = sum((item.line_amount for item in order.items), Decimal("0"))
        assert line_sum == order.total_amount
        for item in order.items:
            assert item.line_amount == item.unit_price * item.quantity
            assert item.quantity > 0


def test_seed_has_two_tenants_for_isolation_tests(seed):
    merchants = _merchants(seed)
    assert len(merchants) >= 2, "租户隔离测试至少需要两个商家"


# ==================== 2. 初始化 / 规模 / 缓存 / env ====================
def test_repository_seeds_all_entities(repo, seed):
    assert repo.backend == "sqlite"
    assert repo.stats() == seed.counts()
    described = repo.describe()
    assert described["backend"] == "sqlite"
    assert described["counts"] == seed.counts()
    assert described["seed"]["seed_version"] == "v1"


def test_env_override_creates_database_at_path(repo, merchant_db):
    assert Path(repo.db_path) == merchant_db
    assert merchant_db.is_file()


def test_default_db_path_is_var_merchant_v1(monkeypatch):
    monkeypatch.delenv("QIANKE_MERCHANT_DB", raising=False)
    path = default_db_path()
    assert path.name == "merchant_v1.sqlite"
    assert path.parent.name == "var"


def test_factory_cache_returns_same_instance_then_reset(merchant_db):
    first = get_merchant_repository()
    second = get_merchant_repository()
    assert first is second
    first_stats = first.stats()

    reset_merchant_repository_cache()
    # reset 会关闭旧实例（防止切换后端后旧连接仍被误用）
    with pytest.raises(MerchantUnavailableError):
        first.stats()

    third = get_merchant_repository()
    assert third is not first
    # 重新初始化是幂等的：不会把种子灌两遍
    assert third.stats() == first_stats and third.stats()["products"] > 0
    third.close()


def test_force_reseed_keeps_counts(repo, seed):
    assert repo.seed(force=True) == seed.counts()
    assert repo.stats() == seed.counts()


# ==================== 3. 商品查询 ====================
def test_list_products_tenant_isolation(repo, seed):
    merchants = _merchants(seed)
    seen: dict[str, set[str]] = {}
    for merchant_id in merchants:
        products = repo.list_products(merchant_id, limit=MAX_LIST_LIMIT)
        assert products, f"商家 {merchant_id} 应该至少有一个商品"
        assert all(product.merchant_id == merchant_id for product in products)
        seen[merchant_id] = {product.product_id for product in products}

    # 两个商家的商品集合不相交，且并集 == 种子全集（没有串租户、没有漏）
    assert not (seen[merchants[0]] & seen[merchants[1]])
    assert set().union(*seen.values()) == {product.product_id for product in seed.products}


def test_list_products_keyword_filters_within_tenant(repo, seed):
    sample = seed.products[0]
    keyword = sample.title[:2]
    hits = repo.list_products(sample.merchant_id, keyword=keyword, limit=MAX_LIST_LIMIT)
    assert sample.product_id in {product.product_id for product in hits}
    assert all(product.merchant_id == sample.merchant_id for product in hits)

    # LIKE 通配符必须被转义：关键词 "%" 不应退化成「匹配所有商品」
    assert repo.list_products(sample.merchant_id, keyword="%", limit=MAX_LIST_LIMIT) == []
    assert repo.list_products(sample.merchant_id, keyword="_", limit=MAX_LIST_LIMIT) == []


def test_list_products_limit_clamp_on_query_path(repo, seed):
    merchant_id = _merchants(seed)[0]
    total = len([p for p in seed.products if p.merchant_id == merchant_id])
    assert len(repo.list_products(merchant_id, limit=0)) == 1
    assert len(repo.list_products(merchant_id, limit=-5)) == 1
    assert len(repo.list_products(merchant_id, limit=10**9)) == min(total, MAX_LIST_LIMIT)
    assert 1 <= len(repo.list_products(merchant_id, limit=None)) <= MAX_LIST_LIMIT


def test_get_product_sku_and_tenant_scope(repo, seed):
    sku = seed.skus[0]
    found = repo.get_product_sku(sku.sku)
    assert found is not None
    assert found.sku == sku.sku
    assert found.price == sku.price
    assert found.to_dict()["price"] == format(sku.price, "f")

    # 正确租户可读；错误租户 / 不存在 一律 None（失败关闭）
    assert repo.get_product_sku(sku.sku, merchant_id=sku.merchant_id) is not None
    wrong = next(m for m in _merchants(seed) if m != sku.merchant_id)
    assert repo.get_product_sku(sku.sku, merchant_id=wrong) is None
    assert repo.get_product_sku("SKU-NOT-EXIST") is None
    assert repo.get_product_sku("") is None


def test_list_product_skus(repo, seed):
    product = seed.products[0]
    expected = {
        sku.sku for sku in seed.skus if sku.product_id == product.product_id
    }
    got = repo.list_product_skus(product.product_id)
    assert {sku.sku for sku in got} == expected
    assert all(sku.product_id == product.product_id for sku in got)

    wrong = next(m for m in _merchants(seed) if m != product.merchant_id)
    assert repo.list_product_skus(product.product_id, merchant_id=wrong) == []


# ==================== 4. 库存查询 ====================
def test_get_inventory_multi_warehouse_aggregates(repo, seed):
    # 找一个在种子里有多仓记录的 SKU
    by_sku: dict[str, list] = {}
    for record in seed.inventory_records:
        by_sku.setdefault(record.sku, []).append(record)
    multi = next(sku for sku, rows in by_sku.items() if len(rows) >= 2)

    inventory = repo.get_inventory(multi)
    assert inventory is not None
    rows = by_sku[multi]
    assert len(inventory.warehouses) == len(rows) >= 2
    assert inventory.available_qty == sum(r.available_qty for r in rows)
    assert inventory.reserved_qty == sum(r.reserved_qty for r in rows)
    assert inventory.in_stock is True
    assert {w.warehouse_id for w in inventory.warehouses} == {r.warehouse_id for r in rows}


def test_zero_stock_vs_missing_sku(repo, seed):
    """有库存记录但可售 0 ≠ 没有该 SKU 的库存记录。"""
    zero = next(r for r in seed.inventory_records if r.available_qty == 0)
    inventory = repo.get_inventory(zero.sku)
    assert inventory is not None
    assert inventory.available_qty == 0
    assert inventory.in_stock is False
    assert inventory.to_dict()["in_stock"] is False

    assert repo.get_inventory("SKU-NOT-EXIST") is None
    assert repo.get_inventory("") is None


def test_get_inventory_tenant_scope(repo, seed):
    record = seed.inventory_records[0]
    assert repo.get_inventory(record.sku, merchant_id=record.merchant_id) is not None
    wrong = next(m for m in _merchants(seed) if m != record.merchant_id)
    assert repo.get_inventory(record.sku, merchant_id=wrong) is None


# ==================== 5. 订单查询 ====================
def test_list_orders_tenant_isolation_and_filters(repo, seed):
    merchants = _merchants(seed)
    for merchant_id in merchants:
        orders = repo.list_orders(merchant_id, limit=MAX_LIST_LIMIT)
        expected = {o.order_id for o in seed.orders if o.merchant_id == merchant_id}
        assert {o.order_id for o in orders} == expected
        assert all(o.merchant_id == merchant_id for o in orders)
        assert all(o.items for o in orders), "列表查询也必须带订单行（一次 IN 查询，无 N+1）"

    # 跨商家订单号不能通过列表串出去
    all_ids: set[str] = set()
    for merchant_id in merchants:
        all_ids |= {o.order_id for o in repo.list_orders(merchant_id, limit=MAX_LIST_LIMIT)}
    assert all_ids == {o.order_id for o in seed.orders}


def test_list_orders_buyer_and_status_filters(repo, seed):
    sample = seed.orders[0]
    by_buyer = repo.list_orders(sample.merchant_id, buyer_id=sample.buyer_id)
    assert by_buyer and all(o.buyer_id == sample.buyer_id for o in by_buyer)

    by_status = repo.list_orders(sample.merchant_id, status=sample.status.lower())
    assert by_status and all(o.status == sample.status for o in by_status)

    assert repo.list_orders(sample.merchant_id, status="NOT_A_STATUS") == []


def test_list_orders_limit_clamp(repo, seed):
    merchant_id = _merchants(seed)[0]
    assert len(repo.list_orders(merchant_id, limit=0)) == 1
    total = len([o for o in seed.orders if o.merchant_id == merchant_id])
    assert len(repo.list_orders(merchant_id, limit=10**9)) == min(total, MAX_LIST_LIMIT)


def test_get_order_and_scope(repo, seed):
    order = seed.orders[0]
    found = repo.get_order(order.order_id)
    assert found is not None
    assert found.order_id == order.order_id
    assert found.total_amount == order.total_amount
    assert len(found.items) == len(order.items)
    payload = found.to_dict()
    assert payload["total_amount"] == format(order.total_amount, "f")
    assert isinstance(payload["items"], list) and payload["items"]

    assert repo.get_order(order.order_id, merchant_id=order.merchant_id) is not None
    wrong_merchant = next(m for m in _merchants(seed) if m != order.merchant_id)
    assert repo.get_order(order.order_id, merchant_id=wrong_merchant) is None
    assert repo.get_order(order.order_id, buyer_id="buyer-not-exist") is None
    assert repo.get_order(order.order_id, buyer_id=order.buyer_id) is not None
    assert repo.get_order("ORD-NOT-EXIST") is None
    assert repo.get_order("") is None


def test_order_item_totals_and_snapshot(repo, seed):
    order = max(seed.orders, key=lambda o: len(o.items))
    found = repo.get_order(order.order_id)
    assert found.item_count == sum(item.quantity for item in order.items)
    assert sum((item.line_amount for item in found.items), Decimal("0")) == found.total_amount
    for item in found.items:
        assert item.title  # 下单快照标题
        assert item.unit_price == item.line_amount / item.quantity


# ==================== 6. 租户隔离：缺租户失败关闭 ====================
def test_missing_merchant_id_fails_closed(repo):
    for merchant_id in ("", "   ", None):
        with pytest.raises(MerchantDataError) as excinfo:
            repo.list_products(merchant_id)  # type: ignore[arg-type]
        assert excinfo.value.code == "MERCHANT_DATA"
        with pytest.raises(MerchantDataError):
            repo.list_orders(merchant_id)  # type: ignore[arg-type]


# ==================== 7. limit 钳制纯函数 ====================
@pytest.mark.parametrize(
    "value, expected",
    [
        (None, DEFAULT_LIST_LIMIT),
        (0, 1),
        (-3, 1),
        (5, 5),
        ("7", 7),
        (MAX_LIST_LIMIT + 1, MAX_LIST_LIMIT),
        (10**9, MAX_LIST_LIMIT),
        (True, DEFAULT_LIST_LIMIT),  # bool 无业务含义 → 默认值
        ("not-a-number", DEFAULT_LIST_LIMIT),
    ],
)
def test_clamp_limit_pure(value, expected):
    assert clamp_limit(value) == expected


def test_clamp_limit_custom_bounds_and_invalid_maximum():
    assert clamp_limit(None, default=50) == 50
    assert clamp_limit(80, maximum=30) == 30
    assert clamp_limit(0, maximum=3) == 1
    with pytest.raises(ValueError):
        clamp_limit(5, maximum=0)


# ==================== 8. 可替换后端 ====================
class _FakeMemoryRepository:
    """内存 Fake：验证业务层不绑死 SQLite，只依赖 MerchantRepository 协议。"""

    backend = "memory-fake"

    def __init__(self) -> None:
        self.closed = False

    def describe(self):
        return {"backend": self.backend, "db_path": ":memory:"}

    def list_products(self, merchant_id, keyword=None, limit=DEFAULT_LIST_LIMIT):
        return []

    def get_product_sku(self, sku, *, merchant_id=None):
        return None

    def list_product_skus(self, product_id, *, merchant_id=None):
        return []

    def get_inventory(self, sku, *, merchant_id=None):
        return None

    def list_orders(self, merchant_id, buyer_id=None, status=None, limit=DEFAULT_LIST_LIMIT):
        return []

    def get_order(self, order_id, *, merchant_id=None, buyer_id=None):
        return None

    def close(self):
        self.closed = True


def test_replaceable_backend_registry(merchant_db):
    backend_name = f"memory-{uuid.uuid4().hex[:8]}"
    register_repository_backend(backend_name, lambda **kwargs: _FakeMemoryRepository())
    fake = get_merchant_repository(backend=backend_name)
    assert isinstance(fake, MerchantRepository)  # 运行时协议匹配
    assert isinstance(fake, _FakeMemoryRepository)
    assert fake.describe()["backend"] == "memory-fake"


def test_unknown_backend_raises_configuration_error():
    with pytest.raises(MerchantConfigurationError) as excinfo:
        get_merchant_repository(backend=f"missing-{uuid.uuid4().hex[:8]}")
    assert excinfo.value.code == "MERCHANT_CONFIG"
    assert "已注册" in excinfo.value.message


# ==================== 9. 坏种子被结构化拒绝 ====================
def _write_minimal_seed(directory: Path) -> None:
    """写一份自洽但**低于规模下限**的种子（1 商品 / 1 SKU / 1 库存 / 1 订单）。"""
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "products.csv": (
            "merchant_id,product_id,title,category,brand,status,created_at\n"
            "m_test,P-1,测试商品,测试类目,测试品牌,ACTIVE,2026-01-01T00:00:00+08:00\n"
        ),
        "skus.csv": (
            "merchant_id,sku,product_id,spec,price,status,barcode\n"
            "m_test,SKU-1,P-1,默认,10.00,ACTIVE,\n"
        ),
        "inventory.csv": (
            "merchant_id,sku,warehouse_id,available_qty,reserved_qty,safety_stock,updated_at\n"
            "m_test,SKU-1,WH-1,5,0,1,2026-01-02T00:00:00+08:00\n"
        ),
        "orders.csv": (
            "merchant_id,order_id,buyer_id,status,total_amount,currency,channel,created_at,paid_at\n"
            "m_test,O-1,b_1,PAID,20.00,CNY,app,2026-01-03T00:00:00+08:00,\n"
        ),
        "order_items.csv": (
            "order_id,sku,title,quantity,unit_price,line_amount\n"
            "O-1,SKU-1,测试商品,2,10.00,20.00\n"
        ),
    }
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")


def test_seed_below_minimums_is_rejected(tmp_path):
    seed_dir = tmp_path / "tiny-seed"
    _write_minimal_seed(seed_dir)
    with pytest.raises(MerchantSeedError) as excinfo:
        load_seed_data(seed_dir)
    assert excinfo.value.code == "MERCHANT_SEED"
    assert "商品数量不足" in excinfo.value.message


def test_seed_with_dangling_inventory_reference_is_rejected(tmp_path):
    real_dir = Path(load_seed_data().source_dir)
    broken = tmp_path / "broken-seed"
    shutil.copytree(real_dir, broken)
    with (broken / "inventory.csv").open("a", encoding="utf-8") as handle:
        handle.write("m_tea_001,SKU-NOT-EXIST,WH-X,1,0,0,2026-10-20T08:00:00+08:00\n")
    with pytest.raises(MerchantSeedError) as excinfo:
        load_seed_data(broken)
    assert "不存在的 SKU" in excinfo.value.message


def test_missing_seed_dir_is_rejected(tmp_path):
    with pytest.raises(MerchantSeedError) as excinfo:
        load_seed_data(tmp_path / "no-such-dir")
    assert "不存在" in excinfo.value.message


# ==================== 10. 关闭后的行为 ====================
def test_closed_repository_raises_unavailable(merchant_db):
    repository = get_merchant_repository()
    repository.close()
    with pytest.raises(MerchantUnavailableError) as excinfo:
        repository.list_products("m_tea_001")
    assert excinfo.value.code == "MERCHANT_UNAVAILABLE"


# ==================== 11. 订单生命周期 / 物流字段（task-45） ====================
def test_order_status_transitions_contract():
    """状态机是公开契约：CREATED→PAID→SHIPPED→COMPLETED，及取消/售后退款迁移。"""
    from rag_demo.merchant import ORDER_STATUS_REFUNDED, ORDER_STATUS_TRANSITIONS

    assert ORDER_STATUS_REFUNDED == "REFUNDED"
    assert ORDER_STATUS_TRANSITIONS["CREATED"] == {"PAID", "CANCELLED"}
    assert ORDER_STATUS_TRANSITIONS["PAID"] == {"SHIPPED", "CANCELLED"}
    assert ORDER_STATUS_TRANSITIONS["SHIPPED"] == {"COMPLETED", "REFUNDED"}
    assert ORDER_STATUS_TRANSITIONS["COMPLETED"] == {"REFUNDED"}
    assert ORDER_STATUS_TRANSITIONS["CANCELLED"] == set()
    assert ORDER_STATUS_TRANSITIONS["REFUNDED"] == set()


def test_seed_shipped_and_completed_orders_have_logistics(seed):
    """种子 CSV 的 SHIPPED/COMPLETED 订单必须带物流单号、承运商与发货时间。"""
    shipped = [order for order in seed.orders if order.status == "SHIPPED"]
    completed = [order for order in seed.orders if order.status == "COMPLETED"]
    assert shipped and completed, "种子需要同时有 SHIPPED 与 COMPLETED 订单覆盖状态机"
    for order in shipped + completed:
        assert order.tracking_no, f"{order.order_id} 缺少 tracking_no"
        assert order.carrier, f"{order.order_id} 缺少 carrier"
        assert order.shipped_at, f"{order.order_id} 缺少 shipped_at"
    for order in completed:
        assert order.completed_at, f"{order.order_id} 缺少 completed_at"
        assert order.completed_at >= order.shipped_at
    # 未发货状态允许没有物流字段（解析兼容缺省空值）
    for order in seed.orders:
        if order.status in ("CREATED", "PAID", "CANCELLED"):
            assert order.tracking_no is None
            assert order.shipped_at is None


def test_order_model_exposes_lifecycle_fields(repo, seed):
    shipped = next(order for order in seed.orders if order.status == "SHIPPED")
    fetched = repo.get_order(shipped.order_id, merchant_id=shipped.merchant_id)
    payload = fetched.to_dict()
    assert payload["status"] == "SHIPPED"
    assert payload["tracking_no"] == shipped.tracking_no
    assert payload["carrier"] == shipped.carrier
    assert payload["shipped_at"] == shipped.shipped_at
    assert payload["completed_at"] is None
    assert payload["paid_at"] == shipped.paid_at

    created = next(order for order in seed.orders if order.status == "CREATED")
    created_payload = repo.get_order(created.order_id).to_dict()
    assert created_payload["tracking_no"] is None
    assert created_payload["carrier"] is None
    assert created_payload["shipped_at"] is None
    assert created_payload["completed_at"] is None


def test_seed_shipped_order_without_tracking_is_rejected(tmp_path):
    """seeds 校验：SHIPPED 订单缺物流单号必须被结构化拒绝（不允许脏种子进库）。"""
    real_dir = Path(load_seed_data().source_dir)
    broken = tmp_path / "broken-logistics-seed"
    shutil.copytree(real_dir, broken)
    orders_path = broken / "orders.csv"
    lines = orders_path.read_text(encoding="utf-8-sig").splitlines()
    header = lines[0].split(",")
    tracking_index = header.index("tracking_no")
    status_index = header.index("status")
    changed = False
    for index in range(1, len(lines)):
        parts = lines[index].split(",")
        if parts[status_index] == "SHIPPED":
            parts[tracking_index] = ""
            lines[index] = ",".join(parts)
            changed = True
            break
    assert changed, "测试需要至少一条 SHIPPED 种子订单"
    orders_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(MerchantSeedError) as excinfo:
        load_seed_data(broken)
    assert "tracking_no" in excinfo.value.message


# ==================== 12. 取消/模拟退款字段兼容（task-47） ====================
def test_reservation_status_reversed_contract():
    from rag_demo.merchant import RESERVATION_STATUSES, RESERVATION_STATUS_REVERSED

    assert RESERVATION_STATUS_REVERSED == "REVERSED"
    assert "REVERSED" in RESERVATION_STATUSES


def test_order_model_exposes_cancellation_fields(repo, seed):
    """Order.to_dict 始终输出取消/退款字段；未取消订单为 None（前端可稳定读取）。"""
    cancelled = next(order for order in seed.orders if order.status == "CANCELLED")
    payload = repo.get_order(
        cancelled.order_id, merchant_id=cancelled.merchant_id
    ).to_dict()
    assert "cancelled_at" in payload
    assert "refund_amount" in payload
    assert "refunded_at" in payload
    assert payload["cancelled_at"] is None
    assert payload["refund_amount"] is None
    assert payload["refunded_at"] is None

    paid = next(order for order in seed.orders if order.status == "PAID")
    paid_payload = repo.get_order(paid.order_id, merchant_id=paid.merchant_id).to_dict()
    assert paid_payload["cancelled_at"] is None
    assert paid_payload["refund_amount"] is None
    assert paid_payload["refunded_at"] is None


def test_seed_orders_parse_without_cancellation_columns(tmp_path):
    """seeds 兼容旧种子文件：orders.csv 没有取消/退款列时解析为 None，不报错。"""
    real_dir = Path(load_seed_data().source_dir)
    legacy = tmp_path / "legacy-cancel-seed"
    shutil.copytree(real_dir, legacy)
    orders_path = legacy / "orders.csv"
    lines = orders_path.read_text(encoding="utf-8-sig").splitlines()
    header = lines[0].split(",")
    dropped = {"cancelled_at", "refund_amount", "refunded_at"}
    keep = [index for index, name in enumerate(header) if name not in dropped]
    rebuilt = [",".join(parts[index] for index in keep) for parts in (line.split(",") for line in lines)]
    orders_path.write_text("\n".join(rebuilt) + "\n", encoding="utf-8")

    data = load_seed_data(legacy)

    assert data.orders
    cancelled = next(order for order in data.orders if order.status == "CANCELLED")
    assert cancelled.cancelled_at is None
    assert cancelled.refund_amount is None
    assert cancelled.refunded_at is None
