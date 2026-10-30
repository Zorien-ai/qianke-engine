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


# ==================== 8. 老库迁移（v1.1 source_ref / v1.2 物流 / v1.3 取消退款） ====================
def test_old_database_is_migrated_on_init(repo, writer, seed, merchant_db):
    """模拟老库：缺 source_ref / 物流字段 / 取消退款字段 / m_reservation；初始化应自动补齐。"""
    connection = sqlite3.connect(str(merchant_db))
    try:
        connection.execute("DROP INDEX IF EXISTS idx_m_order_cancel_request")
        for column in (
            "source_ref",
            "tracking_no",
            "carrier",
            "shipped_at",
            "completed_at",
            "cancelled_at",
            "refund_amount",
            "refunded_at",
            "cancel_request_id",
        ):
            connection.execute(f"ALTER TABLE m_order DROP COLUMN {column}")
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
        assert {
            "source_ref", "tracking_no", "carrier", "shipped_at", "completed_at",
            "cancelled_at", "refund_amount", "refunded_at", "cancel_request_id",
        } <= columns
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
        # 迁移后的老库也能走完整状态机与物流字段
        paid = upgraded.update_order_status(merchant_id, "ORD-MIGRATED", "PAID")
        assert paid.paid_at
        shipped = upgraded.update_order_status(
            merchant_id, "ORD-MIGRATED", "SHIPPED",
            tracking_no="SF1234567890", carrier="顺丰速运",
        )
        assert shipped.tracking_no == "SF1234567890" and shipped.shipped_at
        completed = upgraded.update_order_status(merchant_id, "ORD-MIGRATED", "COMPLETED")
        assert completed.completed_at

        # 迁移后的老库也能取消：PAID → 模拟退款（全额）+ cancelled_at
        upgraded.create_order(
            merchant_id, "ORD-MIGRATED-CANCEL", "b_1",
            [{"sku": sku, "quantity": 1}], sku_row.price,
        )
        upgraded.update_order_status(merchant_id, "ORD-MIGRATED-CANCEL", "PAID")
        cancelled = upgraded.cancel_order(
            merchant_id, "ORD-MIGRATED-CANCEL", request_id="req-migrated-cancel"
        )
        assert cancelled.status == "CANCELLED"
        assert cancelled.cancelled_at
        assert cancelled.refund_amount == sku_row.price
        assert cancelled.refunded_at
    finally:
        upgraded.close()


# ==================== 9. 订单状态机 / 物流字段（task-45） ====================
def _seed_order(seed, status: str):
    for order in seed.orders:
        if order.status == status:
            return order
    raise AssertionError(f"种子里没有 {status} 订单")


def test_update_status_created_to_paid_sets_paid_at(repo, writer, seed):
    order = _seed_order(seed, "CREATED")
    before = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    assert before.paid_at is None

    updated = writer.update_order_status(order.merchant_id, order.order_id, "PAID")

    assert updated.status == "PAID"
    assert updated.paid_at
    assert updated.tracking_no is None and updated.carrier is None
    assert updated.shipped_at is None and updated.completed_at is None
    persisted = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    assert persisted.paid_at == updated.paid_at
    payload = persisted.to_dict()
    assert payload["status"] == "PAID"
    assert payload["paid_at"] == updated.paid_at
    assert payload["tracking_no"] is None and payload["completed_at"] is None


def test_update_status_paid_to_shipped_requires_tracking(repo, writer, seed):
    order = _seed_order(seed, "PAID")

    # 缺少物流单号 → 失败关闭，状态不变
    with pytest.raises(MerchantInvalidError) as excinfo:
        writer.update_order_status(order.merchant_id, order.order_id, "SHIPPED")
    assert "tracking_no" in excinfo.value.message
    assert repo.get_order(order.order_id).status == "PAID"

    updated = writer.update_order_status(
        order.merchant_id, order.order_id, "SHIPPED",
        tracking_no="SF1234567890", carrier="顺丰速运",
    )
    assert updated.status == "SHIPPED"
    assert updated.tracking_no == "SF1234567890"
    assert updated.carrier == "顺丰速运"
    assert updated.shipped_at
    assert updated.completed_at is None
    payload = updated.to_dict()
    assert payload["tracking_no"] == "SF1234567890"
    assert payload["carrier"] == "顺丰速运"
    assert payload["shipped_at"] == updated.shipped_at


def test_update_status_shipped_to_completed_sets_completed_at(repo, writer, seed):
    order = _seed_order(seed, "SHIPPED")
    assert order.tracking_no and order.shipped_at

    updated = writer.update_order_status(order.merchant_id, order.order_id, "COMPLETED")

    assert updated.status == "COMPLETED"
    assert updated.completed_at
    assert updated.tracking_no == order.tracking_no
    assert updated.carrier == order.carrier
    assert updated.shipped_at == order.shipped_at
    assert updated.completed_at >= updated.shipped_at


def test_full_order_lifecycle_created_paid_shipped_completed(repo, writer, seed):
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    created = writer.create_order(
        merchant_id, "ORD-LIFECYCLE", "b_1",
        [{"sku": sku, "quantity": quantity}], total,
    )
    assert created.status == "CREATED" and created.paid_at is None

    paid = writer.update_order_status(merchant_id, "ORD-LIFECYCLE", "PAID")
    assert paid.status == "PAID" and paid.paid_at
    shipped = writer.update_order_status(
        merchant_id, "ORD-LIFECYCLE", "SHIPPED",
        tracking_no="YT1234567890", carrier="圆通速递",
    )
    assert shipped.status == "SHIPPED" and shipped.shipped_at
    completed = writer.update_order_status(merchant_id, "ORD-LIFECYCLE", "COMPLETED")
    assert completed.status == "COMPLETED" and completed.completed_at

    assert completed.paid_at == paid.paid_at
    assert completed.shipped_at == shipped.shipped_at
    assert completed.tracking_no == "YT1234567890"
    assert completed.total_amount == total
    assert completed.item_count == quantity
    from datetime import datetime as _datetime

    assert (
        _datetime.fromisoformat(completed.paid_at)
        <= _datetime.fromisoformat(completed.shipped_at)
        <= _datetime.fromisoformat(completed.completed_at)
    )


def test_same_status_replay_idempotent_does_not_rewrite_timestamps(repo, writer, seed):
    order = _seed_order(seed, "PAID")
    first = writer.update_order_status(order.merchant_id, order.order_id, "PAID")
    paid_at = first.paid_at
    second = writer.update_order_status(order.merchant_id, order.order_id, "PAID")
    assert second.paid_at == paid_at  # 同状态幂等：不重写支付时间

    shipped = writer.update_order_status(
        order.merchant_id, order.order_id, "SHIPPED",
        tracking_no="JD1234567890", carrier="京东物流",
    )
    replay = writer.update_order_status(
        order.merchant_id, order.order_id, "SHIPPED",
        tracking_no="JD1234567890", carrier="京东物流",
    )
    assert replay.shipped_at == shipped.shipped_at
    assert replay.tracking_no == "JD1234567890"


def test_shipped_replay_with_different_logistics_conflicts(repo, writer, seed):
    order = _seed_order(seed, "SHIPPED")
    with pytest.raises(MerchantConflictError):
        writer.update_order_status(
            order.merchant_id, order.order_id, "SHIPPED", tracking_no="OTHER1234567890"
        )
    with pytest.raises(MerchantConflictError):
        writer.update_order_status(
            order.merchant_id, order.order_id, "SHIPPED",
            tracking_no=order.tracking_no, carrier="另一家快递",
        )
    replay = writer.update_order_status(
        order.merchant_id, order.order_id, "SHIPPED",
        tracking_no=order.tracking_no, carrier=order.carrier,
    )
    assert replay.shipped_at == order.shipped_at


@pytest.mark.parametrize(
    "current_status,target",
    [
        ("CREATED", "SHIPPED"),
        ("CREATED", "COMPLETED"),
        ("PAID", "COMPLETED"),
        ("SHIPPED", "CANCELLED"),
        ("SHIPPED", "PAID"),
        ("COMPLETED", "PAID"),
        ("COMPLETED", "CANCELLED"),
        ("CANCELLED", "PAID"),
        ("CANCELLED", "CREATED"),
    ],
)
def test_invalid_transitions_conflict(repo, writer, seed, current_status, target):
    order = _seed_order(seed, current_status)
    kwargs = {"tracking_no": "SF1234567890"} if target == "SHIPPED" else {}
    with pytest.raises(MerchantConflictError) as excinfo:
        writer.update_order_status(order.merchant_id, order.order_id, target, **kwargs)
    assert excinfo.value.code == "MERCHANT_CONFLICT"
    assert repo.get_order(order.order_id).status == current_status


def test_cancel_allowed_from_created_and_paid(repo, writer, seed):
    created = _seed_order(seed, "CREATED")
    cancelled = writer.update_order_status(created.merchant_id, created.order_id, "CANCELLED")
    assert cancelled.status == "CANCELLED"
    assert cancelled.paid_at is None

    paid = _seed_order(seed, "PAID")
    paid_at = paid.paid_at
    cancelled_paid = writer.update_order_status(paid.merchant_id, paid.order_id, "CANCELLED")
    assert cancelled_paid.status == "CANCELLED"
    assert cancelled_paid.paid_at == paid_at  # 保留支付时间供对账


def test_update_status_unknown_or_cross_tenant_not_found(repo, writer, seed):
    order = _seed_order(seed, "CREATED")
    other = _other_merchant(seed, order.merchant_id)
    with pytest.raises(MerchantNotFoundError):
        writer.update_order_status(other, order.order_id, "PAID")
    with pytest.raises(MerchantNotFoundError):
        writer.update_order_status(order.merchant_id, "ORD-MISSING", "PAID")
    assert repo.get_order(order.order_id).status == "CREATED"


def test_update_status_missing_merchant_and_invalid_status(writer, seed):
    order = _seed_order(seed, "CREATED")
    for merchant_id in ("", "   ", None):
        with pytest.raises(MerchantDataError) as excinfo:
            writer.update_order_status(merchant_id, order.order_id, "PAID")
        assert excinfo.value.code == "MERCHANT_DATA"
    for bad_status in ("", "   ", "REFUNDED", "PAIDX", None):
        with pytest.raises(MerchantInvalidError):
            writer.update_order_status(order.merchant_id, order.order_id, bad_status)


@pytest.mark.parametrize(
    "tracking",
    ["abc", "SF 123456", "中文单号1234", "!@#$%^&*", "A" * 65],
)
def test_shipped_tracking_number_format_rules(repo, writer, seed, tracking):
    order = _seed_order(seed, "PAID")
    with pytest.raises(MerchantInvalidError) as excinfo:
        writer.update_order_status(
            order.merchant_id, order.order_id, "SHIPPED", tracking_no=tracking
        )
    assert "tracking_no" in excinfo.value.message
    assert repo.get_order(order.order_id).status == "PAID"

    # 合法格式仍可正常发货
    if tracking == "A" * 65:
        updated = writer.update_order_status(
            order.merchant_id, order.order_id, "SHIPPED",
            tracking_no="A" * 64, carrier="测试承运商",
        )
        assert updated.tracking_no == "A" * 64


def test_valid_tracking_number_formats_accepted(writer, seed):
    order = _seed_order(seed, "PAID")
    updated = writer.update_order_status(
        order.merchant_id, order.order_id, "SHIPPED",
        tracking_no="JD-VA.001_2", carrier="京东物流",
    )
    assert updated.tracking_no == "JD-VA.001_2"


def test_logistics_fields_rejected_for_non_shipped_targets(repo, writer, seed):
    created = _seed_order(seed, "CREATED")
    paid = _seed_order(seed, "PAID")
    with pytest.raises(MerchantInvalidError):
        writer.update_order_status(
            created.merchant_id, created.order_id, "PAID",
            tracking_no="SF1234567890",
        )
    with pytest.raises(MerchantInvalidError):
        writer.update_order_status(
            paid.merchant_id, paid.order_id, "CANCELLED", carrier="顺丰速运"
        )
    assert repo.get_order(created.order_id).status == "CREATED"
    assert repo.get_order(paid.order_id).status == "PAID"


def test_concurrent_same_transition_is_idempotent(repo, seed, merchant_db):
    order = _seed_order(seed, "CREATED")
    repositories = [_thread_repo(merchant_db) for _ in range(3)]

    def attempt(instance):
        return instance.update_order_status(order.merchant_id, order.order_id, "PAID")

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(attempt, repositories))
    finally:
        for instance in repositories:
            instance.close()

    assert all(result.status == "PAID" for result in results)
    assert len({result.paid_at for result in results}) == 1  # 只写一次支付时间
    persisted = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    assert persisted.status == "PAID"
    assert persisted.paid_at == results[0].paid_at


def test_update_status_does_not_touch_order_lines_or_amount(repo, writer, seed):
    order = _seed_order(seed, "PAID")
    before = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    writer.update_order_status(
        order.merchant_id, order.order_id, "SHIPPED",
        tracking_no="SF1234567890", carrier="顺丰速运",
    )
    after = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    assert after.total_amount == before.total_amount
    assert after.item_count == before.item_count
    assert [item.sku for item in after.items] == [item.sku for item in before.items]


# ==================== 10. 订单取消 / 模拟退款 / 库存恢复（task-47） ====================
def _reservation_status(merchant_db, reservation_id: str) -> str | None:
    connection = sqlite3.connect(str(merchant_db))
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT status FROM m_reservation WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else str(row["status"])


def _inventory_snapshot(repo, seed) -> dict:
    return {record.sku: _stock(repo, record.sku) for record in seed.inventory_records}


def _setup_committed_order(repo, writer, seed, *, tag: str = "CANCEL"):
    """预占 → 下单 → 提交，返回订单 + 库存基线（用于验证取消补偿）。"""
    merchant_id, sku, quantity, total = _order_items(seed, repo)
    inventory = repo.get_inventory(sku)
    baseline_available = sum(item.available_qty for item in inventory.warehouses)
    baseline_reserved = sum(item.reserved_qty for item in inventory.warehouses)
    reservation_id = f"RSV-{tag}"
    order_id = f"ORD-{tag}"
    writer.reserve_inventory(
        merchant_id, reservation_id,
        [{"sku": sku, "quantity": quantity}], buyer_id="b_1",
    )
    writer.create_order(
        merchant_id, order_id, "b_1",
        [{"sku": sku, "quantity": quantity}], total,
    )
    writer.commit_reservation(merchant_id, reservation_id, order_id=order_id)
    return {
        "merchant_id": merchant_id,
        "sku": sku,
        "quantity": quantity,
        "total": total,
        "reservation_id": reservation_id,
        "order_id": order_id,
        "baseline_available": baseline_available,
        "baseline_reserved": baseline_reserved,
    }


def test_cancel_created_order_writes_zero_refund(repo, writer, seed):
    order = _seed_order(seed, "CREATED")

    cancelled = writer.cancel_order(order.merchant_id, order.order_id)

    assert cancelled.status == "CANCELLED"
    assert cancelled.cancelled_at
    assert cancelled.refund_amount == Decimal("0")
    assert cancelled.refunded_at is None
    payload = cancelled.to_dict()
    assert payload["cancelled_at"] == cancelled.cancelled_at
    assert payload["refund_amount"] == "0.00"
    assert payload["refunded_at"] is None
    assert repo.get_order(order.order_id, merchant_id=order.merchant_id).status == "CANCELLED"


def test_cancel_paid_order_writes_simulated_refund(repo, writer, seed):
    order = _seed_order(seed, "PAID")
    paid_at = order.paid_at

    cancelled = writer.cancel_order(order.merchant_id, order.order_id)

    assert cancelled.status == "CANCELLED"
    assert cancelled.paid_at == paid_at  # 保留支付时间供对账
    assert cancelled.refund_amount == order.total_amount  # 全额模拟退款
    assert cancelled.refunded_at
    assert cancelled.cancelled_at
    assert Decimal(cancelled.to_dict()["refund_amount"]) == order.total_amount


def test_cancel_restores_stock_from_committed_reservation(repo, writer, seed, merchant_db):
    setup = _setup_committed_order(repo, writer, seed, tag="CREATED-RESTORE")
    sku = setup["sku"]
    _assert_stock(
        repo, sku,
        available=setup["baseline_available"] - setup["quantity"],
        reserved=setup["baseline_reserved"],
    )

    cancelled = writer.cancel_order(setup["merchant_id"], setup["order_id"])

    assert cancelled.status == "CANCELLED"
    assert cancelled.refund_amount == Decimal("0")  # CREATED 取消无退款
    # 库存按已提交预占的 allocations 精确回到原仓库；reserved 不再变化
    _assert_stock(
        repo, sku,
        available=setup["baseline_available"],
        reserved=setup["baseline_reserved"],
    )
    assert _reservation_status(merchant_db, setup["reservation_id"]) == "REVERSED"
    # 冲销后的预占不能再提交；重复释放是幂等返回，不会二次恢复
    with pytest.raises(MerchantConflictError):
        writer.commit_reservation(
            setup["merchant_id"], setup["reservation_id"], order_id=setup["order_id"]
        )
    released = writer.release_reservation(setup["merchant_id"], setup["reservation_id"])
    assert released.status == "REVERSED"
    _assert_stock(
        repo, sku,
        available=setup["baseline_available"],
        reserved=setup["baseline_reserved"],
    )


def test_cancel_paid_order_with_reservation_refunds_and_restores(repo, writer, seed, merchant_db):
    setup = _setup_committed_order(repo, writer, seed, tag="PAID-RESTORE")
    paid = writer.update_order_status(setup["merchant_id"], setup["order_id"], "PAID")
    assert paid.paid_at

    cancelled = writer.cancel_order(setup["merchant_id"], setup["order_id"])

    assert cancelled.status == "CANCELLED"
    assert cancelled.refund_amount == setup["total"]
    assert cancelled.refunded_at
    assert cancelled.paid_at == paid.paid_at
    _assert_stock(
        repo, setup["sku"],
        available=setup["baseline_available"],
        reserved=setup["baseline_reserved"],
    )
    assert _reservation_status(merchant_db, setup["reservation_id"]) == "REVERSED"


def test_repeated_cancel_does_not_double_restore_or_refund(repo, writer, seed, merchant_db):
    setup = _setup_committed_order(repo, writer, seed, tag="REPEAT")
    first = writer.cancel_order(
        setup["merchant_id"], setup["order_id"], request_id="req-repeat-cancel"
    )
    stock_after_first = _stock(repo, setup["sku"])

    second = writer.cancel_order(
        setup["merchant_id"], setup["order_id"], request_id="req-repeat-cancel"
    )
    third = writer.cancel_order(setup["merchant_id"], setup["order_id"])

    for result in (second, third):
        assert result.status == "CANCELLED"
        assert result.cancelled_at == first.cancelled_at
        assert result.refund_amount == first.refund_amount
        assert result.refunded_at == first.refunded_at
    assert _stock(repo, setup["sku"]) == stock_after_first  # 绝不二次恢复库存
    assert _reservation_status(merchant_db, setup["reservation_id"]) == "REVERSED"


def test_cancel_request_id_idempotency_and_cross_order_conflict(repo, writer, seed):
    merchant_id, sku = _pick_sku(seed, repo)
    sku_row = next(item for item in seed.skus if item.sku == sku)
    for order_id in ("ORD-REQ-1", "ORD-REQ-2"):
        writer.create_order(
            merchant_id, order_id, "b_1",
            [{"sku": sku, "quantity": 1}], sku_row.price,
        )

    first = writer.cancel_order(merchant_id, "ORD-REQ-1", request_id="req-idem-1")
    replay = writer.cancel_order(merchant_id, "ORD-REQ-1", request_id="req-idem-1")
    assert replay.cancelled_at == first.cancelled_at
    assert replay.refund_amount == first.refund_amount

    with pytest.raises(MerchantConflictError):
        writer.cancel_order(merchant_id, "ORD-REQ-2", request_id="req-idem-1")
    # 其他订单仍可用新的 request_id 取消
    second = writer.cancel_order(merchant_id, "ORD-REQ-2", request_id="req-idem-2")
    assert second.status == "CANCELLED"

    writer.create_order(
        merchant_id, "ORD-REQ-3", "b_1",
        [{"sku": sku, "quantity": 1}], sku_row.price,
    )
    for bad_request_id in ("", "   ", "x" * 129):
        with pytest.raises(MerchantInvalidError):
            writer.cancel_order(merchant_id, "ORD-REQ-3", request_id=bad_request_id)


def test_cancel_rejects_shipped_and_completed(repo, writer, seed):
    before = _inventory_snapshot(repo, seed)
    for status in ("SHIPPED", "COMPLETED"):
        order = _seed_order(seed, status)
        with pytest.raises(MerchantConflictError) as excinfo:
            writer.cancel_order(order.merchant_id, order.order_id)
        assert excinfo.value.code == "MERCHANT_CONFLICT"
        persisted = repo.get_order(order.order_id, merchant_id=order.merchant_id)
        assert persisted.status == status
        assert persisted.cancelled_at is None
        assert persisted.refund_amount is None
        assert persisted.refunded_at is None
    assert _inventory_snapshot(repo, seed) == before


def test_cancel_unknown_cross_tenant_and_missing_merchant(repo, writer, seed):
    order = _seed_order(seed, "CREATED")
    other = _other_merchant(seed, order.merchant_id)
    with pytest.raises(MerchantNotFoundError):
        writer.cancel_order(other, order.order_id)
    with pytest.raises(MerchantNotFoundError):
        writer.cancel_order(order.merchant_id, "ORD-MISSING")
    for merchant_id in ("", "   ", None):
        with pytest.raises(MerchantDataError) as excinfo:
            writer.cancel_order(merchant_id, order.order_id)
        assert excinfo.value.code == "MERCHANT_DATA"
    assert repo.get_order(order.order_id).status == "CREATED"


def test_cancel_legacy_cancelled_seed_order_is_idempotent(repo, writer, seed):
    """旧种子里的 CANCELLED 订单没有退款字段（历史数据）；重复取消不能凭空补退款。"""
    order = _seed_order(seed, "CANCELLED")
    before = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    assert before.cancelled_at is None and before.refund_amount is None

    result = writer.cancel_order(order.merchant_id, order.order_id)

    assert result.status == "CANCELLED"
    assert result.cancelled_at is None
    assert result.refund_amount is None
    assert repo.get_order(order.order_id).to_dict() == before.to_dict()


def test_update_order_status_cancelled_uses_cancellation_semantics(repo, writer, seed, merchant_db):
    """update_order_status(..., CANCELLED) 不能绕过退款/库存补偿（与 cancel_order 同语义）。"""
    setup = _setup_committed_order(repo, writer, seed, tag="STATUS-CANCEL")
    writer.update_order_status(setup["merchant_id"], setup["order_id"], "PAID")

    cancelled = writer.update_order_status(
        setup["merchant_id"], setup["order_id"], "CANCELLED"
    )

    assert cancelled.status == "CANCELLED"
    assert cancelled.cancelled_at
    assert cancelled.refund_amount == setup["total"]  # PAID 取消
    assert cancelled.refunded_at
    _assert_stock(
        repo, setup["sku"],
        available=setup["baseline_available"],
        reserved=setup["baseline_reserved"],
    )
    assert _reservation_status(merchant_db, setup["reservation_id"]) == "REVERSED"


def test_cancel_without_reservation_does_not_change_inventory(repo, writer, seed):
    """种子订单/直接 create_order 没有预占扣减，取消不能凭空补库存（文档策略）。"""
    before = _inventory_snapshot(repo, seed)
    order = _seed_order(seed, "PAID")

    cancelled = writer.cancel_order(order.merchant_id, order.order_id)

    assert cancelled.status == "CANCELLED"
    assert cancelled.refund_amount == order.total_amount
    assert _inventory_snapshot(repo, seed) == before


def test_cancel_does_not_touch_order_lines_or_amount(repo, writer, seed):
    order = _seed_order(seed, "PAID")
    before = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    writer.cancel_order(order.merchant_id, order.order_id)
    after = repo.get_order(order.order_id, merchant_id=order.merchant_id)
    assert after.total_amount == before.total_amount
    assert after.item_count == before.item_count
    assert [item.sku for item in after.items] == [item.sku for item in before.items]


def test_concurrent_cancel_same_request_id_restores_once(repo, writer, seed, merchant_db):
    setup = _setup_committed_order(repo, writer, seed, tag="CONCURRENT-CANCEL")
    instances = [_thread_repo(merchant_db) for _ in range(3)]

    def attempt(instance):
        return instance.cancel_order(
            setup["merchant_id"], setup["order_id"], request_id="req-concurrent-cancel"
        )

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(attempt, instances))
    finally:
        for instance in instances:
            instance.close()

    assert all(result.status == "CANCELLED" for result in results)
    assert len({result.cancelled_at for result in results}) == 1
    assert len({result.refund_amount for result in results}) == 1
    _assert_stock(
        repo, setup["sku"],
        available=setup["baseline_available"],
        reserved=setup["baseline_reserved"],
    )
    assert _reservation_status(merchant_db, setup["reservation_id"]) == "REVERSED"


def test_write_errors_are_structured(seed, repo):
    merchant_id, sku = _pick_sku(seed, repo)
    error = MerchantStockError("库存不足", details={"sku": sku})
    payload = error.to_dict()
    assert payload["code"] == "MERCHANT_STOCK"
    assert payload["details"]["sku"] == sku
    # 基类错误同样有 code，可被上层统一处理
    assert MerchantConflictError("冲突").to_dict()["code"] == "MERCHANT_CONFLICT"
