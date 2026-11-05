# -*- coding: utf-8 -*-
"""B 端账号级人设存储（SQLite，离线）。"""
from __future__ import annotations

import pytest

from rag_demo.b_end import store


@pytest.fixture()
def b_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_B_PERSONA_DB", str(tmp_path / "b_persona.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    monkeypatch.setattr(store, "_INIT_DONE", False)
    store.init()
    return store


def test_get_missing_returns_none(b_store):
    assert b_store.get_persona(7) is None
    assert b_store.get_persona(None) is None


def test_upsert_and_read(b_store):
    row = b_store.upsert_persona(7, name="阿千", user_address="张伟", tone_profile="concise")
    assert row["account_id"] == 7
    assert row["name"] == "阿千"
    assert row["user_address"] == "张伟"
    assert row["tone_profile"] == "concise"

    again = b_store.get_persona(7)
    assert again["name"] == "阿千"


def test_partial_update_keeps_other_fields(b_store):
    b_store.upsert_persona(7, name="阿千", user_address="张伟", tone_profile="concise")
    row = b_store.upsert_persona(7, tone_profile="standard")
    assert row["name"] == "阿千"
    assert row["user_address"] == "张伟"
    assert row["tone_profile"] == "standard"


def test_empty_string_clears_field(b_store):
    b_store.upsert_persona(7, name="阿千", user_address="张伟")
    row = b_store.upsert_persona(7, user_address="")
    assert row["user_address"] == ""


def test_reset_removes_row(b_store):
    b_store.upsert_persona(7, name="阿千")
    b_store.reset_persona(7)
    assert b_store.get_persona(7) is None
