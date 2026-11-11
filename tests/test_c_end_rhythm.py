"""C 端关系节奏：默认关闭、免打扰、频率限制与购后回访。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end_rhythm.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


@pytest.fixture(autouse=True)
def completed_merchant(monkeypatch):
    monkeypatch.setattr(
        store,
        "_merchant_order_state",
        lambda owner_id, order_id, merchant_id=None: (
            "COMPLETED",
            (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        ),
    )


def _confirmed_order() -> dict:
    draft = store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 1}])
    return store.confirm_order("buyer_1", draft["order_id"], draft["confirmation_token"])


def _set_due_past(owner_id: str, order_id: str) -> None:
    conn = store._connect()
    try:
        conn.execute(
            "UPDATE c_companion_checkin SET due_at = ? WHERE owner_id = ? AND ref_id = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), owner_id, order_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_rhythm_defaults_off_and_validates_quiet_hours(c_store):
    rhythm = store.get_rhythm("buyer_1")
    assert rhythm["enabled"] is False
    assert rhythm["quiet_start"] == "22:00"
    assert rhythm["quiet_end"] == "09:00"
    with pytest.raises(store.CStoreError):
        store.update_rhythm("buyer_1", quiet_start="25:00")


def test_disabled_rhythm_does_not_deliver_order_followup(c_store):
    order = _confirmed_order()
    _set_due_past("buyer_1", order["order_id"])
    assert store.claim_due_checkin("buyer_1", now=datetime.now(timezone.utc) + timedelta(days=3)) is None


def test_enabled_rhythm_delivers_order_followup_once(c_store):
    order = _confirmed_order()
    _set_due_past("buyer_1", order["order_id"])
    store.update_rhythm("buyer_1", enabled=True)
    # 固定在白天，避免测试运行时刚好落在 22:00–09:00 免打扰时段。
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    first = store.claim_due_checkin("buyer_1", now=now)
    assert first is not None
    assert first["kind"] == "order_followup"
    assert "到手" in first["content"]
    assert "优惠" not in first["content"]
    assert "买" not in first["content"]
    assert store.claim_due_checkin("buyer_1", now=now) is None


def test_quiet_hours_block_delivery(c_store):
    order = _confirmed_order()
    _set_due_past("buyer_1", order["order_id"])
    store.update_rhythm("buyer_1", enabled=True)
    # 15:00 UTC = 23:00 Asia/Shanghai，落在 22:00-09:00 免打扰
    now = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
    assert store.claim_due_checkin("buyer_1", now=now) is None


def test_pause_blocks_delivery(c_store):
    order = _confirmed_order()
    _set_due_past("buyer_1", order["order_id"])
    store.update_rhythm("buyer_1", enabled=True, pause_hours=2)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    assert store.claim_due_checkin("buyer_1", now=now) is None


def test_not_delivered_order_does_not_trigger_followup(c_store, monkeypatch):
    order = _confirmed_order()
    _set_due_past("buyer_1", order["order_id"])
    store.update_rhythm("buyer_1", enabled=True)
    monkeypatch.setattr(store, "_merchant_order_state", lambda owner_id, order_id, merchant_id=None: ("SHIPPED", None))
    assert store.claim_due_checkin("buyer_1", now=datetime.now(timezone.utc) + timedelta(days=3)) is None


def test_followup_waits_24h_after_signed(c_store, monkeypatch):
    order = _confirmed_order()
    _set_due_past("buyer_1", order["order_id"])
    store.update_rhythm("buyer_1", enabled=True)
    signed = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(
        store,
        "_merchant_order_state",
        lambda owner_id, order_id, merchant_id=None: ("COMPLETED", signed.isoformat()),
    )
    assert store.claim_due_checkin("buyer_1", now=datetime.now(timezone.utc)) is None
