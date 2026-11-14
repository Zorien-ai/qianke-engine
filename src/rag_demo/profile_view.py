"""用户画像的只读展示层：脱敏、结构化字段映射。

从 `api/kb.py` 抽出来，供两处复用：
- 知识库画像卡牌（/api/kb/profiles，企业管理员）；
- B 端商家工作台画像查询（/api/b/workbench/profiles）。
不在这里做权限判断，也不碰数据库——调用方负责数据集与租户作用域。
"""
from __future__ import annotations

import re

_NAME_RE = re.compile(r"用户[^（(]*[（(]([^）)]{1,24})[）)]")

# 与 kb_profiles 的 SELECT 列顺序严格一致：_profile_row 按元组解包。
PROFILE_SELECT_COLUMNS = (
    "user_id, profile_text, age, gender, city, member_level, "
    "order_count, avg_amount::float8, top_category, days_since_last_buy"
)


def extract_profile_name(profile_text: str) -> str | None:
    match = _NAME_RE.search(profile_text or "")
    if not match:
        return None
    name = match.group(1).strip()
    return name or None


def mask_name(name: str | None) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    return value[:1] + "**" if len(value) > 1 else value + "**"


def mask_profile_name(profile_text: str) -> str | None:
    """从 profile_text 提取姓名并脱敏：张三 → 张**；不返回完整姓名。"""
    name = extract_profile_name(profile_text)
    return mask_name(name) if name else None


def redact_profile_text(profile_text: str) -> str:
    """把文本里出现的完整姓名替换成脱敏形式；没有姓名时原样返回。"""
    text = str(profile_text or "")
    name = extract_profile_name(text)
    if not name:
        return text
    return text.replace(name, mask_name(name))


def profile_row(row) -> dict:
    """把 kb 画像查询的一行转成结构化字典（姓名已脱敏）。"""
    (
        user_id,
        profile_text,
        age,
        gender,
        city,
        member_level,
        order_count,
        avg_amount,
        top_category,
        days_since_last_buy,
    ) = row
    return {
        "user_id": user_id,
        "name": mask_profile_name(profile_text),
        "age": age,
        "gender": gender,
        "city": city,
        "member_level": member_level,
        "order_count": int(order_count or 0),
        "avg_amount": round(float(avg_amount), 2) if avg_amount is not None else None,
        "top_category": top_category,
        "days_since_last_buy": days_since_last_buy,
    }


__all__ = [
    "PROFILE_SELECT_COLUMNS",
    "extract_profile_name",
    "mask_name",
    "mask_profile_name",
    "profile_row",
    "redact_profile_text",
]
