"""商户数据空间：数据集命名、构建白名单、wizard 作用域与上传归属。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from rag_demo import auth, config
from rag_demo.mvp import app as wizard_app
from rag_demo.mvp import builder


def test_merchant_dataset_name_is_deterministic():
    assert config.merchant_dataset_name("m_gear_002") == "mch_m_gear_002"
    assert config.merchant_db_name("m_gear_002") == "vec_db_mch_m_gear_002"
    with pytest.raises(ValueError):
        config.merchant_dataset_name("Bad Merchant")
    with pytest.raises(ValueError):
        config.merchant_dataset_name("")


def test_buildable_allows_registered_merchant_dataset(monkeypatch):
    assert builder.is_buildable("user") is True
    assert builder.is_buildable("test") is True
    assert builder.is_buildable("demo") is False
    monkeypatch.setitem(
        config.DATASETS,
        "mch_m_gear_002",
        {"dbname": "vec_db_mch_m_gear_002"},
    )
    assert builder.is_buildable("mch_m_gear_002") is True
    assert builder.is_buildable("mch_not_registered") is False


def test_scope_dataset_priority_for_merchant(monkeypatch):
    monkeypatch.setattr(wizard_app, "_account", lambda: {"id": 113})
    monkeypatch.setattr(
        wizard_app,
        "_merchant_member",
        lambda acct: {"merchant_id": "m_gear_002", "role": "owner"},
    )
    assert wizard_app._scope_dataset("user") == "mch_m_gear_002"

    monkeypatch.setattr(wizard_app, "_account", lambda: {"id": 1, "is_system_admin": True})
    assert wizard_app._scope_dataset("user") == config.ADMIN_DEBUG_DATASET

    monkeypatch.setattr(
        wizard_app,
        "_account",
        lambda: {"id": 113, "dataset": "ent_32", "is_enterprise_admin": True},
    )
    assert wizard_app._scope_dataset("user") == "ent_32"


def test_scope_dataset_without_space_is_403(monkeypatch):
    monkeypatch.setattr(wizard_app, "_account", lambda: {"id": 999})
    monkeypatch.setattr(wizard_app, "_merchant_member", lambda acct: None)
    with pytest.raises(HTTPException) as exc:
        wizard_app._scope_dataset("user")
    assert exc.value.status_code == 403


def test_merchant_owner_can_write_but_staff_cannot(monkeypatch):
    monkeypatch.setattr(wizard_app, "_account", lambda: {"id": 113})
    monkeypatch.setattr(
        wizard_app,
        "_merchant_member",
        lambda acct: {"merchant_id": "m_gear_002", "role": "owner"},
    )
    assert wizard_app._require_writer()["id"] == 113

    monkeypatch.setattr(
        wizard_app,
        "_merchant_member",
        lambda acct: {"merchant_id": "m_gear_002", "role": "staff"},
    )
    with pytest.raises(HTTPException) as exc:
        wizard_app._require_writer()
    assert exc.value.status_code == 403


def test_upload_access_is_merchant_scoped(monkeypatch):
    monkeypatch.setattr(
        auth,
        "upload_owner",
        lambda upload_id: {"enterprise_id": None, "merchant_id": "m_gear_002"},
    )
    monkeypatch.setattr(auth, "_merchant_id_for_user", lambda user: "m_gear_002")
    assert auth.can_access_upload({"id": 113}, "upload_1") is True

    monkeypatch.setattr(auth, "_merchant_id_for_user", lambda user: "m_tea_001")
    assert auth.can_access_upload({"id": 135}, "upload_1") is False

    assert auth.can_access_upload({"id": 1, "is_system_admin": True}, "upload_1") is True
