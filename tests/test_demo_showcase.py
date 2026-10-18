# -*- coding: utf-8 -*-
"""公开 demo 展示接口的纯函数测试（不连库、不依赖 FastAPI）。"""
from rag_demo.api.demo_showcase import (
    DEFAULT_LIMIT,
    FALLBACK_LABELS,
    MAX_LIMIT,
    build_labels,
    clamp_limit,
    serialize_user,
)


def test_clamp_limit_bounds_and_default():
    assert clamp_limit(None) == DEFAULT_LIMIT
    assert clamp_limit(0) == 1
    assert clamp_limit(10) == 10
    assert clamp_limit(MAX_LIMIT + 100) == MAX_LIMIT
    assert clamp_limit("120") == 120
    assert clamp_limit("abc") == DEFAULT_LIMIT


def test_serialize_user_converts_decimal_amount():
    row = ("U1000", 37, "男", "南京", "普通", 5, 2486.3, "家居", 10)
    user = serialize_user(row)
    assert user == {
        "uid": "U1000",
        "age": 37,
        "gender": "男",
        "city": "南京",
        "member_level": "普通",
        "order_count": 5,
        "avg_amount": 2486.3,
        "top_category": "家居",
        "days_since_last_buy": 10,
    }


def test_serialize_user_handles_missing_amount():
    row = ("U1", None, None, None, None, 0, None, None, None)
    user = serialize_user(row)
    assert user["avg_amount"] is None
    assert user["uid"] == "U1"


def test_build_labels_uses_real_demo_users():
    matched = [
        {"gender": "女", "age": 25, "avg_amount": 3105.37, "top_category": "美妆"},
        {"gender": "女", "age": 30, "avg_amount": 2453.93, "top_category": "美妆"},
        {"gender": "女", "age": 35, "avg_amount": 2244.60, "top_category": "美妆"},
    ]
    assert build_labels(matched) == ["女 / 25 岁", "客单价 2,454", "偏好美妆"]


def test_build_labels_falls_back_without_matches():
    assert build_labels([]) == FALLBACK_LABELS


def test_build_labels_reuses_single_user_when_short():
    one = [{"gender": "女", "age": 28, "avg_amount": 1200.0, "top_category": "美妆"}]
    assert build_labels(one) == ["女 / 28 岁", "客单价 1,200", "偏好美妆"]
