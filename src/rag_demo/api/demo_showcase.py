# -*- coding: utf-8 -*-
"""官网首屏「demo 用户星云」的公开只读展示数据（纯函数，便于单测）。

安全边界（红线）：
  - 只服务仓库自带的合成演示数据集 `config.DEFAULT_DATASET`（"demo"），
    **不接受**任何 dataset / tenant_id 参数；企业库、用户上传库永远不会经过这里。
  - 只 SELECT 画像的结构化字段（年龄段/性别/城市/等级/订单数/客单价/品类/最近购买），
    不返回 profile_text、embedding、联系方式。
  - 所有数字（画像总数、命中数、年龄范围、客单价均值）都由 SQL 实时统计，
    这里不写死任何业务事实；DEMO_QUERY_* 只是对 demo 数据的固定演示问题定义。
"""

DEMO_QUERY_TITLE = "最近一个月高客单的美妆女性用户"

# 演示问题：女、25-35 岁、美妆、近 30 天有购买、客单价 ≥ 1200。
# 这是「demo 数据集上的展示脚本」，不是对任何真实用户数据的规则。
DEMO_QUERY_WHERE = (
    "gender = '女' AND age BETWEEN 25 AND 35 AND top_category = '美妆' "
    "AND days_since_last_buy <= 30 AND avg_amount >= 1200"
)

DEFAULT_LIMIT = 400
MAX_LIMIT = 800

# 前端同一套兜底文案：接口不可用时首屏仍能展示，不出现空白/报错。
FALLBACK_LABELS = ["女 / 28 岁", "客单价 1200", "偏好美妆"]


def clamp_limit(limit) -> int:
    """限制采样条数，避免公开接口被拿来拉全表。"""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def serialize_user(row) -> dict:
    """把 SQL 行转成前端可用的 demo 用户对象（不包含任何自由文本）。"""
    uid, age, gender, city, member_level, order_count, avg_amount, top_category, days = row
    return {
        "uid": uid,
        "age": age,
        "gender": gender,
        "city": city,
        "member_level": member_level,
        "order_count": order_count,
        "avg_amount": round(float(avg_amount), 2) if avg_amount is not None else None,
        "top_category": top_category,
        "days_since_last_buy": days,
    }


def build_labels(matched_users: list[dict]) -> list[str]:
    """从命中的 demo 用户里抽出三条真实标签（不足时用固定文案兜底）。"""
    if not matched_users:
        return list(FALLBACK_LABELS)
    first = matched_users[0]
    second = matched_users[1] if len(matched_users) > 1 else first
    third = matched_users[2] if len(matched_users) > 2 else first

    gender = first.get("gender") or "女"
    age = first.get("age")
    label1 = f"{gender} / {age} 岁" if age is not None else FALLBACK_LABELS[0]

    amount = second.get("avg_amount")
    label2 = f"客单价 {int(round(amount)):,}" if amount is not None else FALLBACK_LABELS[1]

    category = third.get("top_category")
    label3 = f"偏好{category}" if category else FALLBACK_LABELS[2]

    return [label1, label2, label3]
