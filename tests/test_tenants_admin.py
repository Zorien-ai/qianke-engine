"""租户注册表与成员绑定测试。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def test_tenant_registry_and_members(c_store):
    tenants = c_store.list_tenants()
    assert {tenant["merchant_id"] for tenant in tenants} >= {"m_gear_002", "m_tea_001"}
    created = c_store.create_tenant("m_test_001", "测试租户")
    assert created["name"] == "测试租户"
    assert c_store.get_tenant("m_test_001")["status"] == "ACTIVE"

    c_store.bind_merchant_member(999, "m_test_001", role="admin")
    members = c_store.list_merchant_members("m_test_001")
    assert members[0]["account_id"] == 999
    assert members[0]["role"] == "admin"
    assert c_store.get_merchant_member(999)["merchant_id"] == "m_test_001"

    assert c_store.unbind_merchant_member(999) is True
    assert c_store.get_merchant_member(999) is None


def test_provision_tenant_owner_and_policy(c_store):
    result = c_store.provision_tenant(
        "m_new_001",
        "新租户",
        1001,
        compensation_max_amount=30,
        refund_max_amount=200,
        created_by="admin",
    )
    assert result["tenant"]["merchant_id"] == "m_new_001"
    assert result["member"]["role"] == "owner"
    assert result["policy"]["compensation_max_amount"] == 30
    assert c_store.get_merchant_member(1001)["merchant_id"] == "m_new_001"
    provisions = c_store.list_tenant_provisions("m_new_001")
    assert len(provisions) == 1
    assert provisions[0]["owner_account_id"] == 1001

    with pytest.raises(c_store.CStoreError) as exc:
        c_store.provision_tenant("m_new_002", "另一个", 1001)
    assert exc.value.code == "ACCOUNT_ALREADY_BOUND"
