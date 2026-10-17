# -*- coding: utf-8 -*-
"""`rag_demo.kb_stats` 纯函数单测（M3 企业后台：知识库概况/清空/重建）

这个模块刻意不 import DB / torch / FastAPI：
知识库概况里所有「怎么算、怎么判」的逻辑都收敛在这里，才能不起服务、不连库就验证。
真实接口的隔离与写路径由 `%TEMP%\\rag_ui_test\\m3_admin_test.py`（HTTP 回归）覆盖。
"""
import json

import pytest

from rag_demo import kb_stats


# ---------- 文档矩阵 ----------
def test_docs_from_rows_shape_and_order():
    """(doc_name, chunks, chars) 元组转成前端要的 dict，且不动 SQL 给的顺序"""
    rows = [("b.md", 3, 300), ("a.md", 5, 800)]
    assert kb_stats.docs_from_rows(rows) == [
        {"doc_name": "b.md", "chunks": 3, "chars": 300},
        {"doc_name": "a.md", "chunks": 5, "chars": 800},
    ]


def test_docs_from_rows_empty():
    assert kb_stats.docs_from_rows([]) == []


def test_docs_from_rows_null_chars_tolerated():
    """SUM(length()) 正常不为 NULL，但历史脏数据/空切片不该让整页 500"""
    assert kb_stats.docs_from_rows([("x.md", 2, None)]) == [
        {"doc_name": "x.md", "chunks": 2, "chars": 0},
    ]


# ---------- 汇总 ----------
def test_totals_from_sums_docs_and_profiles():
    docs = [
        {"doc_name": "a.md", "chunks": 3, "chars": 100},
        {"doc_name": "b.md", "chunks": 5, "chars": 200},
    ]
    assert kb_stats.totals_from(docs, profiles=5) == {
        "docs": 2,
        "chunks": 8,
        "profiles": 5,
    }


def test_totals_from_empty_dataset():
    assert kb_stats.totals_from([], profiles=0) == {"docs": 0, "chunks": 0, "profiles": 0}


# ---------- last_build（重建的数据来源） ----------
def test_serialize_last_build_roundtrip_keeps_chinese_fields():
    payload = kb_stats.serialize_last_build(
        upload_id="ab12cd34ef56",
        fields={"user_id": "用户ID", "amount": "实付金额"},
        csv=1,
        md=2,
        at="2026-10-17 20:00:00",
    )
    # 落盘走 JSON 字符串（meta 表是 TEXT），中文不能被转义成一堆 \\uXXXX
    raw = json.dumps(payload, ensure_ascii=False)
    assert "用户ID" in raw
    assert kb_stats.parse_last_build(raw) == payload


@pytest.mark.parametrize("raw", [None, "", "not-json", "{", "[]"])
def test_parse_last_build_bad_input_returns_none(raw):
    """meta 缺失/损坏时返回 None，让概况页降级成「没有重建来源」而不是 500"""
    assert kb_stats.parse_last_build(raw) is None


# ---------- 清空二次确认 ----------
def test_validate_clear_confirm_exact_match_ok():
    assert kb_stats.validate_clear_confirm("ent_12", "ent_12") is None


def test_validate_clear_confirm_mismatch_rejected_with_hint():
    msg = kb_stats.validate_clear_confirm("ent_99", "ent_12")
    assert msg and "ent_12" in msg


@pytest.mark.parametrize("confirm", [None, "", "  "])
def test_validate_clear_confirm_empty_rejected(confirm):
    msg = kb_stats.validate_clear_confirm(confirm, "ent_12")
    assert msg and "ent_12" in msg


# ---------- 索引新鲜度 ----------
def test_freshness_payload_keeps_known_status():
    assert kb_stats.freshness_payload("stale", "索引已过期") == {
        "status": "stale",
        "reason": "索引已过期",
    }


@pytest.mark.parametrize("status", [None, "", "weird", "FRESH "])
def test_freshness_payload_unknown_status_normalized(status):
    """状态只认 fresh/stale/unknown；未知值归一成 unknown，前端血条才不会乱配色"""
    out = kb_stats.freshness_payload(status, "原因")
    assert out["status"] == "unknown"
    assert out["reason"] == "原因"
