"""PostgreSQL 商家 adapter 契约测试（真实 PG；无 PG 自动 skip）。

隔离策略
--------
- 每个测试用唯一 schema（``qianke_merchant_test_<uuid>``），测试结束 ``DROP SCHEMA CASCADE``；
- 不读写 public / vec_db 其它表，不依赖生产数据；
- 未安装 psycopg2 或连接不上 PostgreSQL 时整模块 skip，不影响离线 SQLite 套件。
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from rag_demo.merchant import (
    MerchantConflictError,
    MerchantDataError,
    MerchantInvalidError,
    MerchantNotFoundError,
    MerchantStockError,
    PostgresMerchantRepository,
    default_backend,
    get_merchant_repository,
    get_merchant_write_repository,
    load_seed_data,
    reset_merchant_repository_cache,
)
from rag_demo.merchant.postgres_repository import _settings


def _admin_connect():
    settings = _settings()
    return psycopg2.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        dbname=settings["dbname"],
        connect_timeout=5,
    )


def _pg_available() -> bool:
    try:
        conn = _admin_connect()
        conn.close()
        return True
    except Exception:  # noqa: BLE001 测试环境探测：任何连接失败都 skip
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="PostgreSQL 不可用（未启动/未安装 psycopg2/配置不可连）"
)


@pytest.fixture()
def pg_schema():
    schema = f"qianke_merchant_test_{uuid.uuid4().hex[:12]}"
    yield schema
    conn = _admin_connect()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        conn.close()


@pytest.fixture()
def repo(pg_schema):
    repository = PostgresMerchantRepository(schema=pg_schema, seed=True)
    try:
        yield repository
    finally:
        repository.close()


@pytest.fixture(scope="module")
def seed():
    return load_seed_data()


def _pick_sku(seed, min_available: int = 3):
    for record in seed.inventory_records:
        if record.available_qty >= min_available:
            return record.merchant_id, record.sku
    raise AssertionError("种子中没有可用 SKU")


def test_postgres_uses_connection_pool_and_closes(repo):
    assert repo._pool is not None
    assert repo._pool.maxconn <= repo._settings["pool_max"]
    for _ in range(5):
        assert repo.list_products("m_gear_002")
    # 所有读连接都归还连接池，不应无限增长。
    assert len(repo._pool._pool) <= repo._pool.maxconn
    repo.close()
    assert repo._pool is None


def _sku_price(seed, sku: str) -> Decimal:
    return next(item.price for item in seed.skus if item.sku == sku)


def _seed_order(seed, status: str):
    for order in seed.orders:
        if order.status == status:
            return order
    raise AssertionError(f"种子里没有 {status} 订单")


def _available(repo, sku: str) -> int:
    inventory = repo.get_inventory(sku)
    assert inventory is not None
    return sum(warehouse.available_qty for warehouse in inventory.warehouses)


def _reserved(repo, sku: str) -> int:
    inventory = repo.get_inventory(sku)
    assert inventory is not None
    return sum(warehouse.reserved_qty for warehouse in inventory.warehouses)


def _scalar(schema: str, sql: str, params: tuple = ()):
    conn = _admin_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql.replace("{schema}", f'"{schema}"'), params)
            row = cur.fetchone()
        conn.commit()
        return None if row is None else row[0]
    finally:
        conn.close()


def test_postgres_seed_and_describe(repo, seed):
    assert repo.backend == "postgres"
    assert repo.stats() == seed.counts()
    described = repo.describe()
    assert described["backend"] == "postgres"
    assert described["schema"] == repo.schema
    assert described["counts"] == seed.counts()
    assert described["write_capable"] is True
    assert described["seed"]["seed_version"] == "v1"
    assert "password" not in described and "123456" not in str(described)
    # schema 幂等：重复构造不会重复灌种子
    second = PostgresMerchantRepository(schema=repo.schema, seed=True)
    try:
        assert second.stats() == seed.counts()
    finally:
        second.close()


def test_postgres_schema_isolation(repo, seed):
    conn = _admin_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename",
                (repo.schema,),
            )
            tables = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    assert tables == [
        "m_inventory",
        "m_meta",
        "m_order",
        "m_order_item",
        "m_product",
        "m_reservation",
        "m_sku",
    ]
    # 所有数据确实落在独立 schema 内
    assert _scalar(
        repo.schema, "SELECT COUNT(*) FROM {schema}.m_product"
    ) == seed.counts()["products"]


def test_postgres_reads_products_inventory_orders(repo, seed):
    products = repo.list_products("m_gear_002")
    assert products and all(item.merchant_id == "m_gear_002" for item in products)
    assert len(repo.list_products("m_gear_002", limit=1)) == 1
    assert len(repo.list_products("m_gear_002", limit=1000)) <= 100

    sku = repo.get_product_sku("SKU-GEAR-P001-STD", merchant_id="m_gear_002")
    assert sku is not None and sku.product_id == "P001"
    assert repo.get_product_sku("SKU-GEAR-P001-STD", merchant_id="m_tea_001") is None
    assert {item.sku for item in repo.list_product_skus("P001", merchant_id="m_gear_002")} == {
        "SKU-GEAR-P001-STD"
    }

    inventory = repo.get_inventory("SKU-GEAR-P001-STD")
    assert inventory is not None
    assert sum(item.available_qty for item in inventory.warehouses) == 20
    assert repo.get_inventory("SKU-NOT-EXIST") is None

    shipped = [order for order in seed.orders if order.status == "SHIPPED"]
    orders = repo.list_orders("m_gear_002", status="SHIPPED")
    assert {order.order_id for order in orders} == {
        order.order_id for order in shipped if order.merchant_id == "m_gear_002"
    }
    target = orders[0]
    fetched = repo.get_order(target.order_id, merchant_id="m_gear_002")
    assert fetched is not None
    assert fetched.items and fetched.tracking_no
    assert repo.get_order(target.order_id, merchant_id="m_tea_001") is None


def test_postgres_tenant_isolation_and_empty_scopes(repo):
    for merchant_id in ("", "   ", None):
        with pytest.raises(MerchantDataError):
            repo.list_products(merchant_id)
        with pytest.raises(MerchantDataError):
            repo.list_orders(merchant_id)
    assert repo.list_products("m_missing") == []
    assert repo.list_orders("m_missing") == []
    assert repo.get_product_sku("SKU-GEAR-P001-STD", merchant_id="m_missing") is None
    assert repo.get_order("ORD-MISSING") is None


def test_postgres_reserve_commit_release(repo, seed):
    merchant_id, sku = _pick_sku(seed)
    baseline = _available(repo, sku)
    baseline_reserved = _reserved(repo, sku)

    reservation = repo.reserve_inventory(
        merchant_id, "RSV-PG-1", [{"sku": sku, "quantity": 2}], buyer_id="b_pg"
    )
    assert reservation.status == "RESERVED"
    assert _available(repo, sku) == baseline - 2
    assert _reserved(repo, sku) == baseline_reserved + 2

    # 幂等重放：不再扣库存
    replay = repo.reserve_inventory(
        merchant_id, "RSV-PG-1", [{"sku": sku, "quantity": 2}], buyer_id="b_pg"
    )
    assert replay.reservation_id == reservation.reservation_id
    assert _available(repo, sku) == baseline - 2

    committed = repo.commit_reservation(merchant_id, "RSV-PG-1", order_id="ORD-PG-1")
    assert committed.status == "COMMITTED" and committed.order_id == "ORD-PG-1"
    assert _available(repo, sku) == baseline - 2
    assert _reserved(repo, sku) == baseline_reserved
    assert (
        repo.commit_reservation(merchant_id, "RSV-PG-1", order_id="ORD-PG-1").status
        == "COMMITTED"
    )

    second = repo.reserve_inventory(merchant_id, "RSV-PG-2", [{"sku": sku, "quantity": 1}])
    assert second.status == "RESERVED"
    released = repo.release_reservation(merchant_id, "RSV-PG-2")
    assert released.status == "RELEASED"
    assert _available(repo, sku) == baseline - 2
    assert _reserved(repo, sku) == baseline_reserved

    with pytest.raises(MerchantNotFoundError):
        repo.release_reservation(merchant_id, "RSV-PG-MISSING")
    with pytest.raises(MerchantStockError):
        repo.reserve_inventory(
            merchant_id, "RSV-PG-TOO-MUCH", [{"sku": sku, "quantity": baseline}]
        )
    assert _available(repo, sku) == baseline - 2


def test_postgres_create_order_and_read_back(repo, seed):
    merchant_id, sku = _pick_sku(seed)
    price = _sku_price(seed, sku)

    order = repo.create_order(
        merchant_id, "ORD-PG-CREATE", "b_pg",
        [{"sku": sku, "quantity": 2, "unit_price": str(price)}],
        str(price * 2), source_ref="pg-smoke",
    )
    assert order.status == "CREATED"
    assert order.total_amount == price * 2
    assert order.source_ref == "pg-smoke"
    assert order.items[0].sku == sku

    replay = repo.create_order(
        merchant_id, "ORD-PG-CREATE", "b_pg",
        [{"sku": sku, "quantity": 2, "unit_price": str(price)}],
        str(price * 2),
    )
    assert replay.order_id == order.order_id
    assert repo.get_order("ORD-PG-CREATE", merchant_id=merchant_id).source_ref == "pg-smoke"

    with pytest.raises(MerchantInvalidError):
        repo.create_order(
            merchant_id, "ORD-PG-BAD-AMOUNT", "b_pg",
            [{"sku": sku, "quantity": 1}], "0.01",
        )


def test_postgres_order_status_machine(repo, seed):
    created_seed = _seed_order(seed, "CREATED")
    item = created_seed.items[0]
    order = repo.create_order(
        created_seed.merchant_id,
        "ORD-PG-STATUS", "b_pg",
        [{"sku": item.sku, "quantity": 1}],
        str(item.unit_price),
    )
    paid = repo.update_order_status(order.merchant_id, order.order_id, "PAID")
    assert paid.status == "PAID" and paid.paid_at
    assert (
        repo.update_order_status(order.merchant_id, order.order_id, "PAID").paid_at
        == paid.paid_at
    )
    shipped = repo.update_order_status(
        order.merchant_id, order.order_id, "SHIPPED",
        tracking_no="SF1234567890", carrier="顺丰速运",
    )
    assert shipped.tracking_no == "SF1234567890" and shipped.shipped_at
    completed = repo.update_order_status(order.merchant_id, order.order_id, "COMPLETED")
    assert completed.status == "COMPLETED" and completed.completed_at

    with pytest.raises(MerchantInvalidError):
        repo.update_order_status(order.merchant_id, order.order_id, "REFUNDED")
    with pytest.raises(MerchantConflictError):
        repo.update_order_status(order.merchant_id, order.order_id, "PAID")


def test_postgres_cancel_order_restores_stock(repo, seed):
    merchant_id, sku = _pick_sku(seed)
    price = _sku_price(seed, sku)
    baseline = _available(repo, sku)
    repo.reserve_inventory(merchant_id, "RSV-PG-CANCEL", [{"sku": sku, "quantity": 2}])
    repo.create_order(
        merchant_id, "ORD-PG-CANCEL", "b_pg",
        [{"sku": sku, "quantity": 2}], str(price * 2),
    )
    repo.commit_reservation(merchant_id, "RSV-PG-CANCEL", order_id="ORD-PG-CANCEL")
    assert _available(repo, sku) == baseline - 2

    cancelled = repo.cancel_order(merchant_id, "ORD-PG-CANCEL")
    assert cancelled.status == "CANCELLED"
    assert cancelled.refund_amount == Decimal("0")
    assert _available(repo, sku) == baseline
    assert (
        _scalar(
            repo.schema,
            "SELECT status FROM {schema}.m_reservation WHERE reservation_id = %s",
            ("RSV-PG-CANCEL",),
        )
        == "REVERSED"
    )
    # 重复取消幂等，不重复恢复库存
    assert repo.cancel_order(merchant_id, "ORD-PG-CANCEL").status == "CANCELLED"
    assert _available(repo, sku) == baseline


def test_postgres_refund_order(repo, seed):
    shipped = [order for order in seed.orders if order.status == "SHIPPED"]
    assert len(shipped) >= 2
    first = shipped[0]
    before_inventory = {
        record.sku: _available(repo, record.sku)
        for record in seed.inventory_records
    }

    refunded = repo.refund_order(
        first.merchant_id, first.order_id,
        amount=Decimal("100.00"), request_id="req-pg-refund",
    )
    assert refunded.status == "REFUNDED"
    assert refunded.refund_amount == Decimal("100.00")
    assert refunded.refunded_at
    assert refunded.cancelled_at is None
    # 默认不恢复库存
    assert {
        record.sku: _available(repo, record.sku)
        for record in seed.inventory_records
    } == before_inventory
    # 幂等重放
    replay = repo.refund_order(
        first.merchant_id, first.order_id,
        amount=Decimal("100.00"), request_id="req-pg-refund",
    )
    assert replay.refunded_at == refunded.refunded_at
    with pytest.raises(MerchantConflictError):
        repo.refund_order(first.merchant_id, first.order_id, amount=Decimal("50.00"))
    with pytest.raises(MerchantInvalidError):
        repo.refund_order(
            first.merchant_id, first.order_id,
            amount=first.total_amount + Decimal("1.00"),
        )
    # request_id 跨订单冲突
    with pytest.raises(MerchantConflictError):
        repo.refund_order(
            shipped[1].merchant_id, shipped[1].order_id,
            request_id="req-pg-refund",
        )


def test_postgres_cancel_refund_invalid_states(repo, seed):
    created = [order for order in seed.orders if order.status == "CREATED"][0]
    with pytest.raises(MerchantConflictError):
        repo.refund_order(created.merchant_id, created.order_id)
    shipped = _seed_order(seed, "SHIPPED")
    with pytest.raises(MerchantConflictError):
        repo.cancel_order(shipped.merchant_id, shipped.order_id)
    repo.refund_order(shipped.merchant_id, shipped.order_id)
    with pytest.raises(MerchantConflictError):
        repo.cancel_order(shipped.merchant_id, shipped.order_id)


def test_postgres_factory_env_switch(pg_schema, monkeypatch, seed):
    monkeypatch.setenv("QIANKE_MERCHANT_BACKEND", "postgres")
    monkeypatch.setenv("QIANKE_MERCHANT_PG_SCHEMA", pg_schema)
    reset_merchant_repository_cache()
    try:
        repository = get_merchant_repository()
        assert repository.backend == "postgres"
        assert repository.stats() == seed.counts()
        writer = get_merchant_write_repository()
        assert writer is repository
        # 环境变量缺省时 PostgreSQL 为默认
        monkeypatch.delenv("QIANKE_MERCHANT_BACKEND")
        reset_merchant_repository_cache()
        assert default_backend() == "postgres"
    finally:
        reset_merchant_repository_cache()


def test_postgres_seed_force_resets(repo, seed):
    merchant_id, sku = _pick_sku(seed)
    price = _sku_price(seed, sku)
    repo.create_order(
        merchant_id, "ORD-PG-FORCE", "b_pg",
        [{"sku": sku, "quantity": 1}], str(price),
    )
    assert repo.stats()["orders"] == seed.counts()["orders"] + 1
    counts = repo.seed(force=True)
    assert counts == seed.counts()
    assert repo.get_order("ORD-PG-FORCE") is None
    assert repo.stats() == seed.counts()


def test_postgres_concurrent_reservations_no_oversell(pg_schema, seed):
    merchant_id, sku = _pick_sku(seed)
    repositories = [
        PostgresMerchantRepository(schema=pg_schema, seed=True) for _ in range(2)
    ]
    # 第二实例初始化时种子已存在，不会重复插入
    stock = _available(repositories[0], sku)
    baseline_reserved = _reserved(repositories[0], sku)
    try:
        def attempt(index):
            try:
                return repositories[index].reserve_inventory(
                    merchant_id, f"RSV-PG-CONCURRENT-{index}",
                    [{"sku": sku, "quantity": stock}], buyer_id="b_pg",
                )
            except MerchantStockError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        successes = [item for item in results if not isinstance(item, Exception)]
        failures = [item for item in results if isinstance(item, MerchantStockError)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert _available(repositories[0], sku) == 0
        assert _reserved(repositories[0], sku) == baseline_reserved + stock
    finally:
        for repository in repositories:
            repository.close()


# ==================== 退货验收入库 receive_return（task-54） ====================
def _setup_pg_shipped_order(repo, seed, *, tag: str, complete: bool = False) -> dict:
    merchant_id, sku = _pick_sku(seed)
    price = _sku_price(seed, sku)
    baseline_available = _available(repo, sku)
    baseline_reserved = _reserved(repo, sku)
    repo.reserve_inventory(
        merchant_id, f"RSV-{tag}", [{"sku": sku, "quantity": 2}], buyer_id="b_pg"
    )
    repo.create_order(
        merchant_id, f"ORD-{tag}", "b_pg",
        [{"sku": sku, "quantity": 2}], str(price * 2),
    )
    repo.commit_reservation(merchant_id, f"RSV-{tag}", order_id=f"ORD-{tag}")
    repo.update_order_status(merchant_id, f"ORD-{tag}", "PAID")
    repo.update_order_status(
        merchant_id, f"ORD-{tag}", "SHIPPED",
        tracking_no="SF1234567890", carrier="顺丰速运",
    )
    if complete:
        repo.update_order_status(merchant_id, f"ORD-{tag}", "COMPLETED")
    return {
        "merchant_id": merchant_id,
        "sku": sku,
        "baseline_available": baseline_available,
        "baseline_reserved": baseline_reserved,
        "reservation_id": f"RSV-{tag}",
        "order_id": f"ORD-{tag}",
        "final_status": "COMPLETED" if complete else "SHIPPED",
    }


def test_postgres_receive_return_restores_stock(repo, seed):
    setup = _setup_pg_shipped_order(repo, seed, tag="PG-RETURN")
    assert _available(repo, setup["sku"]) == setup["baseline_available"] - 2

    returned = repo.receive_return(setup["merchant_id"], setup["order_id"])

    assert returned.status == "SHIPPED"
    assert returned.returned_at
    assert returned.refund_amount is None
    assert _available(repo, setup["sku"]) == setup["baseline_available"]
    assert _reserved(repo, setup["sku"]) == setup["baseline_reserved"]
    assert (
        _scalar(
            repo.schema,
            "SELECT status FROM {schema}.m_reservation WHERE reservation_id = %s",
            (setup["reservation_id"],),
        )
        == "REVERSED"
    )
    # 幂等：重复调用不重复恢复库存
    replay = repo.receive_return(setup["merchant_id"], setup["order_id"])
    assert replay.returned_at == returned.returned_at
    assert _available(repo, setup["sku"]) == setup["baseline_available"]

    completed = _setup_pg_shipped_order(repo, seed, tag="PG-RETURN-COMPLETE", complete=True)
    result = repo.receive_return(completed["merchant_id"], completed["order_id"])
    assert result.status == "COMPLETED"  # 订单状态不变


def test_postgres_receive_return_request_id_conflict(repo, seed):
    first = _setup_pg_shipped_order(repo, seed, tag="PG-RETURN-X1")
    second = _setup_pg_shipped_order(repo, seed, tag="PG-RETURN-X2")

    repo.receive_return(
        first["merchant_id"], first["order_id"], request_id="req-pg-return"
    )
    with pytest.raises(MerchantConflictError):
        repo.receive_return(
            second["merchant_id"], second["order_id"], request_id="req-pg-return"
        )
    assert repo.get_order(second["order_id"]).returned_at is None
    assert (
        _scalar(
            repo.schema,
            "SELECT status FROM {schema}.m_reservation WHERE reservation_id = %s",
            (second["reservation_id"],),
        )
        == "COMMITTED"
    )
    result = repo.receive_return(
        second["merchant_id"], second["order_id"], request_id="req-pg-return-2"
    )
    assert result.returned_at
    assert _available(repo, second["sku"]) == first["baseline_available"]


def test_postgres_receive_return_invalid_states_and_no_reservation(repo, seed):
    before = {record.sku: _available(repo, record.sku) for record in seed.inventory_records}
    for status in ("SHIPPED", "COMPLETED"):
        order = _seed_order(seed, status)
        with pytest.raises(MerchantConflictError):
            repo.receive_return(order.merchant_id, order.order_id)
        assert repo.get_order(order.order_id).returned_at is None
    assert {
        record.sku: _available(repo, record.sku) for record in seed.inventory_records
    } == before

    created = _seed_order(seed, "CREATED")
    with pytest.raises(MerchantConflictError):
        repo.receive_return(created.merchant_id, created.order_id)

    # REFUNDED 后拒绝（推荐顺序：receive_return → refund_order）
    setup = _setup_pg_shipped_order(repo, seed, tag="PG-RETURN-REFUNDED")
    repo.refund_order(setup["merchant_id"], setup["order_id"], amount=Decimal("10.00"))
    with pytest.raises(MerchantConflictError):
        repo.receive_return(setup["merchant_id"], setup["order_id"])


def test_postgres_receive_return_migration_and_tenant(repo, seed):
    # 模拟旧 schema：删掉 task-54 两列与索引后重新初始化，迁移应幂等补回
    conn = _admin_connect()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                f'DROP INDEX IF EXISTS "{repo.schema}".idx_m_order_restock_request'
            )
            cur.execute(
                f'ALTER TABLE "{repo.schema}".m_order DROP COLUMN returned_at'
            )
            cur.execute(
                f'ALTER TABLE "{repo.schema}".m_order DROP COLUMN restock_request_id'
            )
    finally:
        conn.close()

    upgraded = PostgresMerchantRepository(schema=repo.schema, seed=False)
    try:
        conn = _admin_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'm_order'",
                    (repo.schema,),
                )
                columns = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()
        assert {"returned_at", "restock_request_id"} <= columns

        setup = _setup_pg_shipped_order(upgraded, seed, tag="PG-RETURN-MIGRATED")
        returned = upgraded.receive_return(
            setup["merchant_id"], setup["order_id"], request_id="req-pg-return-migrated"
        )
        assert returned.returned_at

        # 租户隔离 / 未知订单 / merchant_id 必填
        other = "m_tea_001" if setup["merchant_id"] != "m_tea_001" else "m_gear_002"
        with pytest.raises(MerchantNotFoundError):
            upgraded.receive_return(other, setup["order_id"])
        with pytest.raises(MerchantNotFoundError):
            upgraded.receive_return(setup["merchant_id"], "ORD-PG-MISSING")
        for merchant_id in ("", "   ", None):
            with pytest.raises(MerchantDataError):
                upgraded.receive_return(merchant_id, setup["order_id"])
    finally:
        upgraded.close()
