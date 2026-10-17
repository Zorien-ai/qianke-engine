# -*- coding: utf-8 -*-
"""画像结构化文本列的限长与清洗（真实数据 "Female" 打挂构建的回归）

2026-10-18 真实测试者上传 99,457 行电商数据（gender = Female / Male），
构建在写入画像时炸 `value too long for type character varying(4)`：
`user_profile_vectors.gender` 曾是 VARCHAR(4)，而 "Female" 6 个字。
超长值是在 **TRUNCATE 之后** 才炸的（表已清空），代价最大，所以两层防护：
  1. 聚合阶段 `_clip_text` 按 TEXT_LIMITS 截断并留 warning；
  2. 建表/旧库迁移把列宽扩到 TEXT_LIMITS（`ensure_schema` 里按 information_schema 判断）。
"""
import pytest

from rag_demo.db.schema import USER_PROFILE_DDL
from rag_demo.ingest_data import TEXT_LIMITS, _clean_level, _clip_text


def test_text_limits_are_not_narrower_than_before():
    """列宽常量就是迁移目标；改小会让旧库的迁移语法反向缩窄，必须显式改测试"""
    assert TEXT_LIMITS == {
        "gender": 16,
        "city": 64,
        "member_level": 32,
        "top_category": 64,
    }


def test_schema_ddl_matches_text_limits():
    """建表语句必须与 TEXT_LIMITS 一致，否则新库仍会按旧宽度建列"""
    for name, limit in TEXT_LIMITS.items():
        assert f"{name} " in USER_PROFILE_DDL
        assert f"VARCHAR({limit})" in USER_PROFILE_DDL


def test_clip_text_keeps_real_gender_values():
    """真实数据里的 Female / Male / 未知 都不能被截"""
    for value in ("Female", "Male", "女", "未知/保密"):
        assert _clip_text(value, field="用户性别", limit=TEXT_LIMITS["gender"]) == value


def test_clip_text_truncates_overlong_value(caplog):
    value = "Female-" + "x" * 60
    with caplog.at_level("WARNING", logger="rag_demo.ingest_data"):
        out = _clip_text(value, field="用户性别", limit=TEXT_LIMITS["gender"])
    assert out == value[: TEXT_LIMITS["gender"]]
    assert len(out) == 16
    assert "用户性别" in caplog.text  # 截断必须留痕，能对上具体字段


def test_clip_text_strips_and_handles_missing():
    assert _clip_text(" 深圳 ", field="用户城市", limit=64) == "深圳"
    for empty in (None, "", "   "):
        assert _clip_text(empty, field="用户城市", limit=64) is None


def test_clip_text_accepts_non_string_values():
    """CSV 读进来的性别可能是数字（0/1 编码），str() 后仍在限长内"""
    assert _clip_text(1, field="用户性别", limit=16) == "1"


def test_clean_level_uses_widened_limit():
    """会员等级上限已从 20 放宽到 32；超长仍要截断（不能交给 INSERT 去炸）"""
    ok = "黑卡"
    assert _clean_level(ok) == ok
    long_level = "超级尊享" * 10  # 40 字
    assert len(_clean_level(long_level)) == TEXT_LIMITS["member_level"]


@pytest.mark.parametrize("value", [None, "", "  "])
def test_clean_level_empty_values(value):
    assert _clean_level(value) is None
