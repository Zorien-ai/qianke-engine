"""B 端画像查询接口：数据范围、权限、数据空间未就绪与 SQL 可见性。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from rag_demo import config
from rag_demo.api import b_workbench
from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _bind(monkeypatch, c_store, role="owner"):
    c_store.bind_merchant_member(113, "m_gear_002", role=role)
    monkeypatch.setattr(
        b_workbench.auth,
        "current_account",
        lambda: {
            "id": 113,
            "username": "merchant",
            "display_name": "商家",
            "status": "active",
            "is_system_admin": False,
            "is_enterprise_admin": False,
        },
    )
    monkeypatch.setattr(config, "DATASETS", dict(config.DATASETS))
    monkeypatch.setitem(
        config.DATASETS,
        "mch_m_gear_002",
        {"dbname": "vec_db_mch_m_gear_002"},
    )


def _status(ready: bool = True, profiles: int = 10):
    return {
        "dataset": "mch_m_gear_002",
        "ready": ready,
        "profiles": profiles,
        "docs": 1,
        "chunks": 3,
        "error": "",
    }


def test_profile_sources_returns_both_pools(c_store, monkeypatch):
    _bind(monkeypatch, c_store)
    monkeypatch.setattr(b_workbench.b_insights, "dataset_status", lambda dataset: _status())
    monkeypatch.setattr(
        b_workbench.b_user_pool,
        "pool_summary",
        lambda merchant_id: {
            "count": 2,
            "with_orders": 1,
            "with_chat": 2,
            "updated_at": "2026-11-14T10:00:00+00:00",
            "ready": True,
        },
    )
    data = b_workbench.workbench_profile_sources()
    assert data["merchant_id"] == "m_gear_002"
    assert data["qianke"]["count"] == 2
    assert data["imported"]["ready"] is True
    assert data["can_manage"] is True
    assert {item["value"] for item in data["scopes"]} == {"qianke", "imported", "all"}


def test_staff_cannot_manage_profiles(c_store, monkeypatch):
    _bind(monkeypatch, c_store, role="staff")
    monkeypatch.setattr(b_workbench.b_insights, "dataset_status", lambda dataset: _status())
    monkeypatch.setattr(
        b_workbench.b_user_pool,
        "pool_summary",
        lambda merchant_id: {"count": 0, "with_orders": 0, "with_chat": 0, "updated_at": None},
    )
    data = b_workbench.workbench_profile_sources()
    assert data["can_manage"] is False
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_profile_pool_refresh()
    assert exc.value.status_code == 403


def test_imported_profiles_require_built_dataset(c_store, monkeypatch):
    _bind(monkeypatch, c_store)
    monkeypatch.setattr(b_workbench.b_insights, "dataset_status", lambda dataset: _status(ready=False))
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_profiles(source="imported")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PROFILE_DB_NOT_READY"


def test_all_profiles_returns_two_groups(c_store, monkeypatch):
    _bind(monkeypatch, c_store)
    monkeypatch.setattr(b_workbench.b_insights, "dataset_status", lambda dataset: _status())
    monkeypatch.setattr(
        b_workbench.b_insights,
        "imported_profile_page",
        lambda dataset, page, size: {
            "source": "imported",
            "page": page,
            "size": size,
            "total": 3,
            "total_pages": 1,
            "items": [],
            "mode": "list",
        },
    )
    monkeypatch.setattr(
        b_workbench.b_insights,
        "qianke_profile_page",
        lambda merchant_id, page, size: {
            "source": "qianke",
            "page": page,
            "size": size,
            "total": 2,
            "total_pages": 1,
            "items": [],
            "mode": "list",
        },
    )
    data = b_workbench.workbench_profiles(source="all")
    assert data["groups"]["imported"]["total"] == 3
    assert data["groups"]["qianke"]["total"] == 2


def test_invalid_source_returns_structured_error(c_store, monkeypatch):
    _bind(monkeypatch, c_store)
    monkeypatch.setattr(b_workbench.b_insights, "dataset_status", lambda dataset: _status())
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_profiles(source="nope")
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "PROFILE_SOURCE_INVALID"


def test_owner_sees_sql_and_staff_does_not(c_store, monkeypatch):
    _bind(monkeypatch, c_store)
    monkeypatch.setattr(b_workbench.b_insights, "dataset_status", lambda dataset: _status())
    monkeypatch.setattr(
        b_workbench.b_insights,
        "answer",
        lambda **kwargs: {
            "answer": "ok",
            "route": "rag",
            "sources": [],
            "cards": [],
            "coverage": {"note": "范围说明"},
            "sql": "SELECT 1",
            "trace": {"internal": True},
        },
    )
    owner = b_workbench.workbench_profile_query(
        b_workbench.ProfileQueryIn(question="问一下", source="imported")
    )
    assert owner["sql"] == "SELECT 1"
    assert "trace" not in owner

    _bind(monkeypatch, c_store, role="staff")
    staff = b_workbench.workbench_profile_query(
        b_workbench.ProfileQueryIn(question="问一下", source="imported")
    )
    assert "sql" not in staff
    assert "trace" not in staff


def test_unbound_account_cannot_query_profiles(c_store, monkeypatch):
    monkeypatch.setattr(
        b_workbench.auth,
        "current_account",
        lambda: {"id": 999, "username": "other", "status": "active", "is_system_admin": False},
    )
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_profile_sources()
    assert exc.value.status_code == 403


def test_merchant_sample_files_are_present():
    files = b_workbench._merchant_sample_files()
    names = {name for name, _ in files}
    assert names == {"merchant_users.csv", "merchant_rules.md"}
    assert all(content for _, content in files)
