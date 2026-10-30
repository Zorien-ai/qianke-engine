# -*- coding: utf-8 -*-
"""商家数据层写接口单测（库存预占 + 订单写入，SQLite 种子库，离线）。

覆盖任务 task-43 的验收点：
- reserve 成功/库存不足/参数非法/重复预占（幂等与冲突）/过期；
- commit 保留已扣减、reserved 转出、重复提交不重复扣库存；
- release 恢复库存、重复释放幂等、已提交拒绝释放；
- 过期预占的 commit/release 行为明确（库存释放、状态 EXPIRED、可复用 id 重新预占）；
- create_order 幂等、金额不一致拒绝、租户隔离、订单行快照、来源引用；
- 并发场景：同一 reservation 并发只扣一次；两个预占竞争同一库存不能超卖；
- 所有写操作 merchant_id 必填（失败关闭）；写接口协议与只读工厂的能力边界。

不依赖网络/模型/PG；只操作 tmp_path 下的 SQLite 文件。
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from rag_demo.merchant import (
    MerchantConfigurationError,
    MerchantConflictError,
    MerchantDataError,
    MerchantExpiredError,
    MerchantInvalidError,
    MerchantNotFoundError,
    MerchantStockError,
    MerchantWriteRepository,
    SqliteMerchantRepository,
    get_merchant_repository,
    get_merchant_write_repository,
    load_seed_data,
    register_repository_backend,
    reset_merchant_repository_cache,
)


# ==================== fixtures / 动态种子工具 ====================
@pytest.fixture()
def merchant_db(tmp_path, monkeypatch):
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


@pytest.fixture()
def writer(repo):
    """写接口与只读接口是同一个 adapter 实例（能力边界靠协议区分）。"""
    write_repo = get_merchant_write_repository()
    assert write_repo is repo
    return write_repo


@pytest.fixture(scope="module")
def seed():
    return load_seed_data()


def _stock(repo, sku: str):
    inventory = repo.get_inventory(sku)
    assert inventory is not None, f"种子缺少库存记录: {sku}"
    return inventory


def _assert_stock(repo, sku: str, *, available: int, reserved: int) -> None:
    """库存断言只看账目数量：updated_at 会随每次写操作变化，不能作为业务不变量的比较项。"""
    inventory = _stock(repo, sku)
    assert inventory.available_qty == available
    assert inventory.reserved_qty == reserved


def _pick_sku(seed, repo, *, min_available: int = 3) -> tuple[str, str]:
    """从种子里挑一个「同一商家、可售量足够」的 SKU；测试不写死具体 SKU。"""
    per_sku: Counter[str] = Counter()
    merchant_of: dict[str, str] = {}
    for record in seed.inventory_records:
        per_sku[record.sku] += record.available_qty
        merchant_of[record.sku] = record.merchant_id
    for sku, available in per_sku.items():
        if available >= min_available:
            return merchant_of[sku], sku
    raise AssertionError(f"种子中没有可售量 >= {min_available} 的 SKU")


def _other_merchant(seed, merchant_id: str) -> str:
    merchants = sorted({product.merchant_id for product in seed.products})
    return next(m for m in merchants if m != merchant_id)


def _reserve(writer, merchant_id, reservation_id, sku, quantity=2, **kwargs):
    return writer.reserve_inventory(
        merchant_id,
        reservation_id,
        [{"sku": sku, "quantity": quantity}],
        **kwargs,
    )


# ==================== 1. 能力边界 / 协议 ====================
def test_sqlite_adapter_implements_write_protocol(repo, writer):
    assert isinstance(repo, MerchantWriteRepository)
    described = repo.describe()
    assert described["write_capable"] is True
    assert described["reservations"] == 0
    # 原有 counts 口径不变（种子实体），不因新增预占表而破坏
    assert set(described["counts"]) == {
        "products", "skus", "inventory_records", "orders", "order_items",
    }


def test_missing_merchant_fails_closed_for_all_writes(writer, seed):
    _merchant, sku = _pick_sku(seed, get_merchant_repository())
    for merchant_id in ("", "   ", None):
        with pytest.raises(MerchantDataError) as excinfo:
            _reserve(writer, merchant_id, f"RSV-{time.time_ns()}", sku)
        assert excinfo.value.code == "MERCHANT_DATA"
        with pytest.raises(MerchantDataError):
            writer.commit_reservation(merchant_id, "RSV-X")
        with pytest.raises(MerchantDataError):
            writer.release_reservation(merchant_id, "RSV-X")
        with pytest.raises(MerchantDataError):
            writer.create_order(merchant_id, "ORD-X", "b_1", [{"sku": sku, "quantity": 1}], "1.00")


def test_readonly_adapter_is_rejected_by_write_factory(merchant_db):
    """只读 adapter 不会因为「碰巧缺写方法」而在调用时才炸：工厂层就明确拒绝。"""

    class _ReadOnlyAdapter:
        backend = "readonly-fake"

        def describe(self):
            return {"backend": self.backend}

        def close(self):
            pass

    name = f"readonly-{uuid.uuid4().hex[:8]}"
    register_repository_backend(name, lambda **kwargs: _ReadOnlyAdapter())
    with pytest.raises(MerchantConfigurationError) as excinfo:
        get_merchant_write_repository(backend=name)
    assert excinfo.value.code == "MERCHANT_CONFIG"
    assert "只读" in excinfo.value.message or "写" in excinfo.value.message


# ==================== 2. reserve：成功 / 扣减 / 幂等 / 冲突 ====================
def test_reserve_deducts_available_and_increases_reserved(repo, writer, seed, merchant_db):
    merchant_id, sku = _pick_sku(seed, repo)
    before = _stock(repo, sku)

    reservation = _reserve(writer, merchant_id, "RSV-OK-1", sku, 2, buyer_id="b_1001")

    assert reservation.status == "RESERVED"
    assert reservation.merchant_id == merchant_id
    assert reservation.buyer_id == "b_1001"
    assert reservation.item_count == 2
    assert [item.sku for item in reservation.items] == [sku]
    assert sum(a.quantity for a in reservation.allocations) == 2
    assert reservation.expires_at and reservation.created_at
    assert reservation.to_dict()["items"][0]["quantity"] == 2
    # 不泄露内部 order_id（未提交时为空）
    assert reservation.order_id is None

    after = _stock(repo, sku)
    assert after.available_qty == before.available_qty - 2
    assert after.reserved_qty == before.reserved_qty + 2
    assert repo.describe()["reservations"] == 1


def test_reserve_same_payload_is_idempotent(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    before = _stock(repo, sku)

    first = _reserve(writer, merchant_id, "RSV-IDEM", sku, 2, buyer_id="b_1")
    second = _reserve(writer, merchant_id, "RSV-IDEM", sku, 2, buyer_id="b_1")

    assert first.reservation_id == second.reservation_id
    assert second.status == "RESERVED"
    assert second.items == first.items
    assert second.allocations == first.allocations
    after = _stock(repo, sku)
    assert after.available_qty == before.available_qty - 2  # 只扣一次
    assert repo.describe()["reservations"] == 1


def test_reserve_same_id_different_payload_conflicts(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    _reserve(writer, merchant_id, "RSV-CONFLICT", sku, 2)
    before = _stock(repo, sku)

    with pytest.raises(MerchantConflictError) as excinfo:
        _reserve(writer, merchant_id, "RSV-CONFLICT", sku, 3)
    assert excinfo.value.code == "MERCHANT_CONFLICT"
    assert _stock(repo, sku) == before


def test_reserve_insufficient_stock_fails_closed(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    before = _stock(repo, sku)

    with pytest.raises(MerchantStockError) as excinfo:
        _reserve(writer, merchant_id, "RSV-NOSTOCK", sku, before.available_qty + 1)
    assert excinfo.value.code == "MERCHANT_STOCK"
    error = excinfo.value
    assert error.details["sku"] == sku
    assert error.details["requested"] == before.available_qty + 1
    assert error.to_dict()["details"]["available"] == before.available_qty

    # 失败关闭：库存与预占记录都不应变化
    assert _stock(repo, sku) == before
    assert repo.describe()["reservations"] == 0


def test_reserve_unknown_sku_or_product_not_found(writer, seed):
    merchant_id = sorted({p.merchant_id for p in seed.products})[0]
    with pytest.raises(MerchantNotFoundError) as excinfo:
        writer.reserve_inventory(
            merchant_id, "RSV-404", [{"sku": "SKU-NOT-EXIST", "quantity": 1}]
        )
    assert excinfo.value.code == "MERCHANT_NOT_FOUND"
    with pytest.raises(MerchantNotFoundError):
        writer.reserve_inventory(
            merchant_id, "RSV-404B", [{"product_id": "P-NOT-EXIST", "quantity": 1}]
        )


def test_reserve_duplicate_sku_and_invalid_items(writer, seed):
    merchant_id, sku = _pick_sku(seed, get_merchant_repository())
    with pytest.raises(MerchantInvalidError):
        writer.reserve_inventory(
            merchant_id,
            "RSV-DUP",
            [{"sku": sku, "quantity": 1}, {"sku": sku, "quantity": 2}],
        )
    invalid_cases = [
        [],
        [{"sku": sku, "quantity": 0}],
        [{"sku": sku, "quantity": -1}],
        [{"sku": sku, "quantity": True}],
        [{"quantity": 1}],
        [{"sku": sku}],
        "not-a-list",
    ]
    for index, items in enumerate(invalid_cases):
        with pytest.raises(MerchantInvalidError):
            writer.reserve_inventory(merchant_id, f"RSV-BAD-{index}", items)


def test_reserve_invalid_ttl(writer, seed):
    merchant_id, sku = _pick_sku(seed, get_merchant_repository())
    for bad_ttl in (0, -5, "abc", 7 * 24 * 3600 + 1):
        with pytest.raises(MerchantInvalidError):
            _reserve(writer, merchant_id, f"RSV-TTL-{time.time_ns()}", sku, 1, ttl_seconds=bad_ttl)


def test_reserve_product_id_single_sku_resolution(repo, writer, seed):
    """items 允许只给 product_id：仅当该商品只有一个可售 SKU 时才自动解析。"""
    skus_per_product = Counter(sku.product_id for sku in seed.skus)
    single = next(
        (p for p in seed.products if skus_per_product[p.product_id] == 1), None
    )
    if single is None:  # pragma: no cover - 当前种子有单 SKU 商品；防未来种子变化
        pytest.skip("当前种子没有单 SKU 商品")
    product = single
    reservation = writer.reserve_inventory(
        product.merchant_id, "RSV-BY-PRODUCT", [{"product_id": product.product_id, "quantity": 1}]
    )
    assert reservation.items[0].product_id == product.product_id

    multi = next(p for p in seed.products if skus_per_product[p.product_id] > 1)
    with pytest.raises(MerchantInvalidError):
        writer.reserve_inventory(
            multi.merchant_id, "RSV-MULTI", [{"product_id": multi.product_id, "quantity": 1}]
        )


# ==================== 3. release / commit ====================
def test_release_restores_stock_and_is_idempotent(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    baseline = _stock(repo, sku)
    _reserve(writer, merchant_id, "RSV-REL", sku, 2)

    released = writer.release_reservation(merchant_id, "RSV-REL")
    assert released.status == "RELEASED"
    _assert_stock(
        repo, sku, available=baseline.available_qty, reserved=baseline.reserved_qty
    )

    again = writer.release_reservation(merchant_id, "RSV-REL")
    assert again.status == "RELEASED"
    _assert_stock(
        repo, sku, available=baseline.available_qty, reserved=baseline.reserved_qty
    )  # 重复释放不二次加库存


def test_commit_keeps_available_deducted_and_releases_reserved(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    baseline = _stock(repo, sku)
    _reserve(writer, merchant_id, "RSV-COMMIT", sku, 2)

    committed = writer.commit_reservation(merchant_id, "RSV-COMMIT", order_id="ORD-C1")
    assert committed.status == "COMMITTED"
    assert committed.order_id == "ORD-C1"

    after = _stock(repo, sku)
    assert after.available_qty == baseline.available_qty - 2  # 已售出，保持扣减
    assert after.reserved_qty == baseline.reserved_qty        # 预占转出，不再挂账


def test_commit_replay_does_not_double_adjust(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    _reserve(writer, merchant_id, "RSV-REPLAY", sku, 2)
    writer.commit_reservation(merchant_id, "RSV-REPLAY", order_id="ORD-R1")
    stock_after_first = _stock(repo, sku)

    replay = writer.commit_reservation(merchant_id, "RSV-REPLAY", order_id="ORD-R1")
    assert replay.status == "COMMITTED"
    assert _stock(repo, sku) == stock_after_first

    with pytest.raises(MerchantConflictError):
        writer.commit_reservation(merchant_id, "RSV-REPLAY", order_id="ORD-R2")


def test_commit_unknown_or_wrong_tenant_not_found(writer, seed):
    merchant_id, sku = _pick_sku(seed, get_merchant_repository())
    other = _other_merchant(seed, merchant_id)
    _reserve(writer, merchant_id, "RSV-TENANT", sku, 1)

    with pytest.raises(MerchantNotFoundError):
        writer.commit_reservation(other, "RSV-TENANT")   # 跨租户按不存在处理
    with pytest.raises(MerchantNotFoundError):
        writer.release_reservation(other, "RSV-TENANT")
    with pytest.raises(MerchantNotFoundError):
        writer.commit_reservation(merchant_id, "RSV-MISSING")
    with pytest.raises(MerchantNotFoundError):
        writer.release_reservation(merchant_id, "RSV-MISSING")

    # 跨租户尝试不应改动原租户的预占
    assert _stock(get_merchant_repository(), sku).reserved_qty >= 1


def test_release_after_commit_conflicts(writer, seed):
    merchant_id, sku = _pick_sku(seed, get_merchant_repository())
    _reserve(writer, merchant_id, "RSV-REL-COMMITTED", sku, 1)
    writer.commit_reservation(merchant_id, "RSV-REL-COMMITTED", order_id="ORD-X")
    with pytest.raises(MerchantConflictError):
        writer.release_reservation(merchant_id, "RSV-REL-COMMITTED")


def test_reserve_reuse_committed_or_released_id_conflicts(writer, seed):
    merchant_id, sku = _pick_sku(seed, get_merchant_repository())
    _reserve(writer, merchant_id, "RSV-REUSE-REL", sku, 1)
    writer.release_reservation(merchant_id, "RSV-REUSE-REL")
    with pytest.raises(MerchantConflictError):
        _reserve(writer, merchant_id, "RSV-REUSE-REL", sku, 1)

    _reserve(writer, merchant_id, "RSV-REUSE-COM", sku, 1)
    writer.commit_reservation(merchant_id, "RSV-REUSE-COM")
    with pytest.raises(MerchantConflictError):
        _reserve(writer, merchant_id, "RSV-REUSE-COM", sku, 1)


# ==================== 4. 过期语义 ====================
def _expire():
    time.sleep(1.05)  # expires_at = now + 1s（ISO 微秒精度）


def test_expired_reservation_commit_fails_and_restores_stock(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    baseline = _stock(repo, sku)
    _reserve(writer, merchant_id, "RSV-EXP", sku, 2, ttl_seconds=1)
    assert _stock(repo, sku).available_qty == baseline.available_qty - 2

    _expire()
    with pytest.raises(MerchantExpiredError) as excinfo:
        writer.commit_reservation(merchant_id, "RSV-EXP")
    assert excinfo.value.code == "MERCHANT_EXPIRED"
    _assert_stock(
        repo, sku, available=baseline.available_qty, reserved=baseline.reserved_qty
    )  # 过期即释放，库存恢复

    # 已过期预占再次 commit 仍然失败（不能变成已提交）
    with pytest.raises(MerchantExpiredError):
        writer.commit_reservation(merchant_id, "RSV-EXP")


def test_release_expired_reservation_is_idempotent(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    baseline = _stock(repo, sku)
    _reserve(writer, merchant_id, "RSV-EXP-REL", sku, 2, ttl_seconds=1)
    _expire()

    released = writer.release_reservation(merchant_id, "RSV-EXP-REL")
    assert released.status == "EXPIRED"
    _assert_stock(
        repo, sku, available=baseline.available_qty, reserved=baseline.reserved_qty
    )
    again = writer.release_reservation(merchant_id, "RSV-EXP-REL")
    assert again.status == "EXPIRED"
    _assert_stock(
        repo, sku, available=baseline.available_qty, reserved=baseline.reserved_qty
    )  # 不重复恢复


def test_reserve_reuse_expired_id_starts_new_hold(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    baseline = _stock(repo, sku)
    _reserve(writer, merchant_id, "RSV-REUSE-EXP", sku, 2, ttl_seconds=1)
    _expire()

    fresh = _reserve(writer, merchant_id, "RSV-REUSE-EXP", sku, 1)
    assert fresh.status == "RESERVED"
    after = _stock(repo, sku)
    assert after.available_qty == baseline.available_qty - 1
    assert after.reserved_qty == baseline.reserved_qty + 1


# ==================== 5. 并发：不重复扣 / 不超卖 ====================
def _thread_repo(db_path):
    return SqliteMerchantRepository(db_path)


def test_concurrent_same_reservation_deducts_once(repo, writer, seed, merchant_db):
    merchant_id, sku = _pick_sku(seed, repo)
    baseline = _stock(repo, sku)
    repositories = [_thread_repo(merchant_db) for _ in range(3)]

    def attempt(instance):
        return instance.reserve_inventory(
            merchant_id,
            "RSV-CONCURRENT",
            [{"sku": sku, "quantity": 2}],
            buyer_id="b_1",
        )

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(attempt, repositories))
    finally:
        for instance in repositories:
            instance.close()

    assert all(result.reservation_id == "RSV-CONCURRENT" for result in results)
    after = _stock(repo, sku)
    assert after.available_qty == baseline.available_qty - 2  # 只扣一次
    assert repo.describe()["reservations"] == 1


def test_concurrent_competing_reservations_cannot_oversell(repo, seed, merchant_db):
    merchant_id, sku = _pick_sku(seed, repo)
    baseline = _stock(repo, sku)
    available = baseline.available_qty
    repositories = [_thread_repo(merchant_db) for _ in range(2)]

    def attempt(instance, index):
        try:
            reservation = instance.reserve_inventory(
                merchant_id,
                f"RSV-RACE-{index}",
                [{"sku": sku, "quantity": available}],
            )
            return ("ok", reservation.reservation_id)
        except MerchantStockError as exc:
            return ("stock", exc.code)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: attempt(*pair), zip(repositories, range(2))))
    finally:
        for instance in repositories:
            instance.close()

    outcomes = sorted(status for status, _ in results)
    assert outcomes == ["ok", "stock"], f"必须恰好一个成功一个库存不足: {results}"
    _assert_stock(
        repo,
        sku,
        available=0,
        reserved=baseline.reserved_qty + available,
    )


# ==================== 6. create_order ====================
def _order_items(seed, repo, quantity: int = 2):
    merchant_id, sku = _pick_sku(seed, repo)
    sku_row = next(item for item in seed.skus if item.sku == sku)
    total = sku_row.price * quantity
    return merchant_id, sku, quantity, total


def test_create_order_writes_and_reads_back(repo, writer, seed):
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    before_orders = repo.stats()["orders"]

    order = writer.create_order(
        merchant_id,
        "ORD-WRITE-1",
        "b_1001",
        [{"sku": sku, "quantity": quantity}],
        total,
        source_ref="quote-42",
    )

    assert order.order_id == "ORD-WRITE-1"
    assert order.merchant_id == merchant_id
    assert order.buyer_id == "b_1001"
    assert order.status == "CREATED"
    assert order.total_amount == total
    assert order.item_count == quantity
    assert order.source_ref == "quote-42"
    assert order.items[0].sku == sku
    assert order.items[0].unit_price * quantity == total

    fetched = repo.get_order("ORD-WRITE-1", merchant_id=merchant_id)
    assert fetched is not None and fetched.to_dict() == order.to_dict()
    assert repo.stats()["orders"] == before_orders + 1
    assert fetched.to_dict()["source_ref"] == "quote-42"


def test_create_order_idempotent_returns_existing(repo, writer, seed):
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    first = writer.create_order(
        merchant_id, "ORD-IDEM", "b_1", [{"sku": sku, "quantity": quantity}], total
    )
    orders_after_first = repo.stats()["orders"]
    item_rows_after_first = repo.stats()["order_items"]

    # 重复调用（即使 payload/total 不同）返回首次订单，不重复写
    replay = writer.create_order(
        merchant_id, "ORD-IDEM", "b_999", [{"sku": sku, "quantity": 99}], Decimal("1.00")
    )
    assert replay.order_id == first.order_id
    assert replay.buyer_id == first.buyer_id
    assert replay.total_amount == first.total_amount
    assert repo.stats()["orders"] == orders_after_first
    assert repo.stats()["order_items"] == item_rows_after_first


def test_create_order_amount_mismatch_rejected_without_write(repo, writer, seed):
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    before = repo.stats()

    with pytest.raises(MerchantInvalidError) as excinfo:
        writer.create_order(
            merchant_id, "ORD-BAD-AMOUNT", "b_1",
            [{"sku": sku, "quantity": quantity}], total + Decimal("0.01"),
        )
    assert excinfo.value.code == "MERCHANT_INVALID"
    assert repo.stats() == before
    assert repo.get_order("ORD-BAD-AMOUNT") is None


def test_create_order_tenant_isolation(repo, writer, seed):
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    other = _other_merchant(seed, merchant_id)
    writer.create_order(
        merchant_id, "ORD-TENANT", "b_1", [{"sku": sku, "quantity": quantity}], total
    )
    with pytest.raises(MerchantConflictError):
        writer.create_order(
            other, "ORD-TENANT", "b_2", [{"sku": sku, "quantity": quantity}], total
        )
    # 订单仍归属原商家，其他商家查不到
    assert repo.get_order("ORD-TENANT", merchant_id=merchant_id) is not None
    assert repo.get_order("ORD-TENANT", merchant_id=other) is None


def test_create_order_unit_price_override_and_product_resolution(repo, writer, seed):
    """促销价：items 指定 unit_price 时按它计算，仍要求总金额一致。"""
    merchant_id, sku, _, _ = _order_items(seed, repo)
    order = writer.create_order(
        merchant_id, "ORD-PROMO", "b_1",
        [{"sku": sku, "quantity": 2, "unit_price": "10.00"}], "20.00",
    )
    assert order.items[0].unit_price == Decimal("10.00")
    assert order.items[0].line_amount == Decimal("20.00")

    skus_per_product = Counter(item.product_id for item in seed.skus)
    single = next((p for p in seed.products if skus_per_product[p.product_id] == 1), None)
    if single is not None:
        sku_row = next(item for item in seed.skus if item.product_id == single.product_id)
        order2 = writer.create_order(
            single.merchant_id, "ORD-BY-PRODUCT", "b_1",
            [{"product_id": single.product_id, "quantity": 1}], sku_row.price,
        )
        assert order2.items[0].product_id == single.product_id

    multi = next(p for p in seed.products if skus_per_product[p.product_id] > 1)
    with pytest.raises(MerchantInvalidError):
        writer.create_order(
            multi.merchant_id, "ORD-MULTI", "b_1",
            [{"product_id": multi.product_id, "quantity": 1}], "1.00",
        )


def test_create_order_unknown_sku_and_invalid_payload(writer, seed, repo):
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    with pytest.raises(MerchantNotFoundError):
        writer.create_order(merchant_id, "ORD-404", "b_1", [{"sku": "SKU-NOPE", "quantity": 1}], "1.00")
    with pytest.raises(MerchantInvalidError):
        writer.create_order(merchant_id, "ORD-EMPTY", "b_1", [], total)
    with pytest.raises(MerchantInvalidError):
        writer.create_order(merchant_id, "ORD-NOBUYER", "   ", [{"sku": sku, "quantity": 1}], total)
    with pytest.raises(MerchantInvalidError):
        writer.create_order(merchant_id, "   ", "b_1", [{"sku": sku, "quantity": 1}], total)


def test_create_order_does_not_touch_inventory(repo, writer, seed):
    """create_order 只写订单记录；库存变化必须走 reserve/commit（文档契约）。"""
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    before = _stock(repo, sku)
    writer.create_order(
        merchant_id, "ORD-NOSTOCK", "b_1", [{"sku": sku, "quantity": quantity}], total
    )
    assert _stock(repo, sku) == before


# ==================== 7. 组合流程：预占 → 下单 → 提交 ====================
def test_full_reserve_create_order_commit_flow(repo, writer, seed):
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    baseline = _stock(repo, sku)

    reservation = writer.reserve_inventory(
        merchant_id, "RSV-FLOW", [{"sku": sku, "quantity": quantity}], buyer_id="b_1"
    )
    order = writer.create_order(
        merchant_id, "ORD-FLOW", "b_1",
        [{"sku": sku, "quantity": quantity}], total, source_ref="quote-flow",
    )
    committed = writer.commit_reservation(merchant_id, "RSV-FLOW", order_id=order.order_id)
    assert committed.status == "COMMITTED"
    assert committed.order_id == "ORD-FLOW"

    final = _stock(repo, sku)
    assert final.available_qty == baseline.available_qty - quantity
    assert final.reserved_qty == baseline.reserved_qty
    assert repo.get_order("ORD-FLOW", merchant_id=merchant_id).source_ref == "quote-flow"


# ==================== 8. 老库迁移（v1 无 source_ref / m_reservation） ====================
def test_old_database_is_migrated_on_init(repo, writer, seed, merchant_db):
    """模拟 v1 老库：m_order 没有 source_ref、没有 m_reservation；升级后首次初始化应自动补。"""
    connection = sqlite3.connect(str(merchant_db))
    try:
        connection.execute("ALTER TABLE m_order DROP COLUMN source_ref")
        connection.execute("DROP TABLE m_reservation")
        connection.commit()
    finally:
        connection.close()

    reset_merchant_repository_cache()  # 模拟服务重启：旧实例作废，重新初始化
    upgraded = get_merchant_write_repository()
    try:
        connection = sqlite3.connect(str(merchant_db))
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(m_order)")}
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        assert "source_ref" in columns
        assert "m_reservation" in tables

        merchant_id, sku = _pick_sku(seed, upgraded)
        sku_row = next(item for item in seed.skus if item.sku == sku)
        order = upgraded.create_order(
            merchant_id, "ORD-MIGRATED", "b_1",
            [{"sku": sku, "quantity": 1}], sku_row.price, source_ref="migrated",
        )
        assert order.source_ref == "migrated"
        reservation = upgraded.reserve_inventory(
            merchant_id, "RSV-MIGRATED", [{"sku": sku, "quantity": 1}]
        )
        assert reservation.status == "RESERVED"
    finally:
        upgraded.close()


def test_write_errors_are_structured(seed, repo):
    merchant_id, sku = _pick_sku(seed, repo)
    error = MerchantStockError("库存不足", details={"sku": sku})
    payload = error.to_dict()
    assert payload["code"] == "MERCHANT_STOCK"
    assert payload["details"]["sku"] == sku
    # 基类错误同样有 code，可被上层统一处理
    assert MerchantConflictError("冲突").to_dict()["code"] == "MERCHANT_CONFLICT"
