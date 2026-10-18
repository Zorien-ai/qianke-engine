# -*- coding: utf-8 -*-
"""增量更新 / 取消等级推导的纯函数单测（M3 第五轮）

这些用例**不连数据库、不加载模型**，只验证「判断规则」本身：
  · manifest 比对：new / ingested / changed，以及 CSV 同名改内容必须跳过；
  · 旧库引导：mtime <= last_build.at 的文件视为已入库；
  · 合并规则 merge_profile_row：订单数/金额精确相加、属性新有值用新值、
    天数取 min、品类新有值用新值；
  · 取消等级推导：没有等级列时 build_profiles 输出全 None 且 level_source="none"。

为什么这些规则必须逐条测：增量更新最危险的失败不是「跑得慢」，而是
「判断/合并错了但不报错」——把已入库文件再合并一次会让用户订单数翻倍，
把等级按金额推算会给出不属于客户业务的结论。两者都不会抛异常。
"""
import os
from datetime import datetime

import pandas as pd
import pytest

from rag_demo.ingest_data import build_profiles, merge_profile_row
from rag_demo.mvp import uploads


# ==================== 1. manifest 比对 ====================
def _entry(name: str, sha: str = "sha-a", mtime: float = 0.0) -> dict:
    return {"name": name, "size": 10, "sha256": sha, "mtime": mtime}


def _manifest(csv: dict, docs: dict) -> dict:
    return {"csv": csv, "docs": docs}


def test_classify_csv_new_ingested_changed():
    """CSV：不在清单=new；sha 相同=ingested；sha 变了=changed（且进跳过名单）"""
    manifest = _manifest(
        {"a.csv": {"sha256": "sha-a"}},
        {},
    )
    entries = [
        _entry("a.csv", sha="sha-a"),      # 已入库
        _entry("b.csv", sha="sha-b"),      # 新增
        _entry("c.csv", sha="sha-c-new"),  # 同名但内容变了 → 跳过
    ]
    manifest["csv"]["c.csv"] = {"sha256": "sha-c-old"}

    out = uploads.classify_files(entries, [], manifest)

    states = {e["name"]: e["state"] for e in out["csv_files"]}
    assert states == {"a.csv": "ingested", "b.csv": "new", "c.csv": "changed"}
    assert [e["name"] for e in out["new_csv"]] == ["b.csv"]
    assert out["skipped_changed_csv"] == ["c.csv"]


def test_classify_md_changed_is_processed_not_skipped():
    """MD：同名 sha 变化 = changed，但**要处理**（删旧 chunk 重切分），不进跳过名单"""
    manifest = _manifest(
        {},
        {
            "规则.md": {"sha256": "old"},
            "旧文档.md": {"sha256": "same"},
        },
    )
    entries = [
        _entry("规则.md", sha="new-content"),
        _entry("旧文档.md", sha="same"),
        _entry("新文档.md", sha="brand-new"),
    ]

    out = uploads.classify_files([], entries, manifest)

    states = {e["name"]: e["state"] for e in out["md_files"]}
    assert states == {"规则.md": "changed", "旧文档.md": "ingested", "新文档.md": "new"}
    assert [e["name"] for e in out["new_md"]] == ["新文档.md"]
    assert [e["name"] for e in out["changed_md"]] == ["规则.md"]
    assert out["skipped_changed_csv"] == []


def test_classify_without_manifest_degrades_to_none():
    """清单不可用（旧库）时 state 必须是 None——不能谎称「新增」，否则可能重复累加"""
    out = uploads.classify_files([_entry("a.csv")], [_entry("a.md")], None)
    assert [e["state"] for e in out["csv_files"]] == [None]
    assert [e["state"] for e in out["md_files"]] == [None]
    assert out["manifest_available"] is False
    # 判断不了 → 既不进「新增」也不进「跳过」
    assert out["new_csv"] == [] and out["skipped_changed_csv"] == []


# ==================== 2. 旧库引导（mtime） ====================
def test_seed_manifest_marks_old_files_ingested():
    """mtime <= last_build.at 的文件视为已入库；更晚的是本次新增，不进清单"""
    built_at = "2026-10-17 20:00:00"
    # last_build.at 是本地时间字符串（builder 用 time.strftime 写入），
    # 与 os.path.getmtime 的 epoch 比较必须用**本地时区**换算
    cutoff = datetime.strptime(built_at, "%Y-%m-%d %H:%M:%S").timestamp()
    csv_entries = [
        _entry("old.csv", sha="sha-old", mtime=cutoff - 60),
        _entry("new.csv", sha="sha-new", mtime=cutoff + 60),
    ]
    md_entries = [_entry("old.md", sha="sha-md", mtime=cutoff - 3600)]

    seeded = uploads.seed_manifest_from_mtime(csv_entries, md_entries, built_at)

    assert set(seeded["csv"]) == {"old.csv"}
    assert seeded["csv"]["old.csv"]["sha256"] == "sha-old"
    assert seeded["csv"]["old.csv"]["rows"] is None  # 旧构建没留按文件计数，不编造
    assert set(seeded["docs"]) == {"old.md"}


def test_seed_manifest_unparsable_built_at_returns_empty():
    """last_build.at 格式坏了 → 引导失败（空清单），调用方据此禁用增量"""
    out = uploads.seed_manifest_from_mtime(
        [_entry("a.csv")], [_entry("a.md")], "not-a-timestamp"
    )
    assert out == {"csv": {}, "docs": {}}


def test_sha256_and_file_entry(tmp_path):
    """文件指纹按字节算：同内容同指纹；file_entry 带 name/size/mtime"""
    path = tmp_path / "a.csv"
    path.write_text("user_id,amount\n1,10\n", encoding="utf-8")
    entry = uploads.file_entry(str(path))
    assert entry["name"] == "a.csv"
    assert entry["size"] == os.path.getsize(path)
    assert entry["sha256"] == uploads.sha256_file(str(path))
    assert len(entry["sha256"]) == 64
    assert entry["mtime"] > 0


# ==================== 3. plan 提示文案 ====================
def test_plan_hint_counts_and_skipped():
    hint = uploads.plan_hint(1, 400, 0, 0, 99457, [])
    assert "1 个新增 CSV（400 行）" in hint
    assert "99,457 个用户不受影响" in hint

    changed = uploads.plan_hint(1, 400, 0, 0, 5, ["c.csv"])
    assert "已跳过" in changed and "c.csv" in changed


def test_plan_hint_nothing_new():
    hint = uploads.plan_hint(0, 0, 0, 0, 100)
    assert "没有新增文件" in hint and "覆盖重建" in hint


# ==================== 4. merge_profile_row 合并规则 ====================
def _old_row(**overrides) -> dict:
    row = {
        "user_id": "u1",
        "age": 30,
        "gender": "女",
        "city": "深圳",
        "member_level": "黑卡",
        "order_count": 2,
        "total_amount": 100.0,
        "avg_amount": 50.0,
        "top_category": "美妆",
        "days_since_last_buy": 30,
        "platforms": "天猫",
    }
    row.update(overrides)
    return row


def _new_row(**overrides) -> dict:
    row = {
        "user_id": "u1",
        "age": None,
        "gender": None,
        "city": None,
        "member_level": None,
        "order_count": 3,
        "total_amount": 90.0,
        "avg_amount": 30.0,
        "top_category": None,
        "days_since_last_buy": 5,
        "platforms": "京东",
    }
    row.update(overrides)
    return row


def test_merge_orders_and_amounts_add_exactly():
    """订单数/总消费精确相加，avg = total/count（不是新旧均值平均）"""
    merged = merge_profile_row(_old_row(), _new_row())
    assert merged["order_count"] == 5
    assert merged["total_amount"] == pytest.approx(190.0)
    assert merged["avg_amount"] == pytest.approx(38.0)  # 190/5，不是 (50+30)/2


def test_merge_attributes_prefer_new_then_keep_old():
    """新文件有值用新值；新文件没有的保留旧值（不猜、不推导）"""
    merged = merge_profile_row(_old_row(), _new_row(city="广州", age=31))
    assert merged["city"] == "广州"   # 新有值 → 新
    assert merged["age"] == 31        # 新有值 → 新
    assert merged["gender"] == "女"    # 新缺失 → 保留旧
    assert merged["member_level"] == "黑卡"  # 不按金额推算，旧等级保留


def test_merge_days_min_and_top_category_preference():
    """天数取 min（保守近似）；品类新文件有值用新值，否则保留旧值"""
    merged = merge_profile_row(_old_row(), _new_row())
    assert merged["days_since_last_buy"] == 5  # min(30, 5)

    kept = merge_profile_row(_old_row(), _new_row(top_category=None))
    assert kept["top_category"] == "美妆"

    replaced = merge_profile_row(_old_row(), _new_row(top_category="数码"))
    assert replaced["top_category"] == "数码"


def test_merge_platforms_union():
    """活跃平台取并集：这次没出现的老平台不消失"""
    merged = merge_profile_row(_old_row(platforms="天猫,淘宝"), _new_row(platforms="京东,天猫"))
    assert merged["platforms"] == "京东,天猫,淘宝"


def test_merge_new_user_has_no_old_values():
    """库里没有的用户：按新聚合值落库（old=None 不能崩）"""
    merged = merge_profile_row(None, _new_row(city="广州"))
    assert merged["order_count"] == 3
    assert merged["total_amount"] == pytest.approx(90.0)
    assert merged["city"] == "广州"
    assert merged["member_level"] is None
    assert merged["days_since_last_buy"] == 5


def test_merge_missing_amount_is_not_zeroed():
    """新文件没有金额列时：不能当 0 把旧总额冲掉（缺失≠0）"""
    merged = merge_profile_row(
        _old_row(total_amount=100.0, order_count=2),
        _new_row(total_amount=None),
    )
    assert merged["total_amount"] == pytest.approx(100.0)
    assert merged["avg_amount"] == pytest.approx(20.0)  # 100/(2+3)，口径一致


# ==================== 5. 取消会员等级推导 ====================
def _tx_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_build_profiles_without_level_column_does_not_derive():
    """没有映射等级列 → member_level 全 None、level_source='none'（不再按金额推导）"""
    df = _tx_frame(
        [
            {"user_id": "u1", "amount": 100.0, "city": "深圳", "platform": "天猫",
             "purchase_time": pd.Timestamp("2026-01-01")},
            {"user_id": "u1", "amount": 300.0, "city": "深圳", "platform": "天猫",
             "purchase_time": pd.Timestamp("2026-01-02")},
            {"user_id": "u2", "amount": 50.0, "city": "广州", "platform": "京东",
             "purchase_time": pd.Timestamp("2026-01-03")},
        ]
    )
    profiles = build_profiles(df)

    assert profiles["member_level"].isna().all()
    assert profiles.attrs["member_level_source"] == "none"
    # 画像文本里也不能出现「会员」片段（未提供就是未提供）
    assert not any("会员" in text for text in profiles["profile_text"])


def test_build_profiles_with_user_level_column_keeps_values():
    """映射了等级列 → 用用户自己的值，level_source='user'"""
    df = _tx_frame(
        [
            {"user_id": "u1", "amount": 100.0, "member_level": "黑卡",
             "platform": "天猫", "purchase_time": pd.Timestamp("2026-01-01")},
            {"user_id": "u2", "amount": 50.0, "member_level": "金卡",
             "platform": "京东", "purchase_time": pd.Timestamp("2026-01-02")},
        ]
    )
    profiles = build_profiles(df).set_index("user_id")

    assert profiles.loc["u1", "member_level"] == "黑卡"
    assert profiles.loc["u2", "member_level"] == "金卡"
    assert profiles.attrs["member_level_source"] == "user"
