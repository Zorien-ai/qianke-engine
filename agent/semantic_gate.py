"""Agent 业务语义守门：防止 Copywriter 把候选用户当成精确命中用户。"""
from __future__ import annotations

import re
from typing import Any

# “没有命中”的判定要精确，不能把回答里的风险提示当成无结果：
# 例如黑卡查询会写“资料里没有流失标签/无法直接给出联系方式”，
# 但明确说“只有 1 位用户”，这是命中，不是无匹配。
NO_MATCH_PATTERNS = (
    re.compile(r"没有(完全)?符合"),
    re.compile(r"(未|没有)找到[^。]{0,20}(用户|名单)"),
    re.compile(r"不存在[^。]{0,20}(用户|名单)"),
    re.compile(r"资料(里|中)没有[^。]{0,20}(符合|匹配)[^。]{0,10}(用户|名单)?"),
    re.compile(r"无法判断[^。]{0,20}(哪位|哪个|是否).{0,20}用户"),
)

# 兜底话术必须包含“未找到匹配用户”，供测试和前端稳定识别。
NO_MATCH_REPLY_TEMPLATE = (
    "⚠️ 未找到匹配用户：数据中没有完全符合「{conditions}」的用户"
    "（当前仅有{candidates}）。请确认您的筛选口径。"
)

# 用户可能说“黄金/金卡/黑卡/白银”；如果请求里的等级在候选卡中完全不存在，
# 即使 Analyst 的话术把“黄金”解释成“高价值”，也不能当作命中。
LEVEL_TERMS = (
    "黑卡", "金卡", "黄金", "黄金会员", "白银", "钻石", "铂金", "普通", "银卡", "铜卡",
)


def _requested_levels(user_query: str) -> list[str]:
    text = user_query or ""
    return [level for level in LEVEL_TERMS if level in text]


def _level_matches(requested: str, card_level: str) -> bool:
    requested, card_level = requested.strip(), card_level.strip()
    return bool(requested and card_level) and (
        requested in card_level or card_level in requested
    )


def condition_label(user_query: str) -> str:
    """从用户请求里提取一句可展示的筛选条件。"""
    text = (user_query or "").strip()
    text = re.sub(r"^帮我(给|为|针对)?", "", text).strip()
    text = re.sub(r"(写|生成|推荐|做).*(短信|文案|话术).*$", "", text).strip()
    text = text.strip("，。,.；; ")
    return text or "当前筛选条件"


def candidate_label(user_cards: list[dict[str, Any]] | None) -> str:
    """把候选卡片收敛成“上海黑卡、北京金卡”这类可读条件。"""
    parts: list[str] = []
    for card in (user_cards or [])[:3]:
        city = str(card.get("city") or "城市未知")
        level = str(card.get("member_level") or "等级未知")
        parts.append(f"{city}{level}")
    return "、".join(parts) if parts else "没有候选用户"


def should_gate(profiles_data: dict[str, Any] | None, user_query: str = "") -> bool:
    """画像工具返回“没有精确命中”时返回 True。

    注意：`user_cards` 是检索候选，不等于命中；即使 cards 非空，只要 answer
    明确说没有匹配/无法判断，或用户请求的会员等级在候选卡中不存在，也必须拦截。
    """
    data = profiles_data or {}
    if not data.get("ok"):
        return True
    answer = str(data.get("answer") or "")
    cards = data.get("user_cards") or []
    if not cards:
        return True
    if any(pattern.search(answer) for pattern in NO_MATCH_PATTERNS):
        return True

    requested_levels = _requested_levels(user_query)
    if requested_levels:
        card_levels = [str(card.get("member_level") or "") for card in cards]
        if not any(
            _level_matches(requested, card_level)
            for requested in requested_levels
            for card_level in card_levels
        ):
            return True
    return False


def build_fallback(user_query: str, user_cards: list[dict[str, Any]] | None) -> str:
    return NO_MATCH_REPLY_TEMPLATE.format(
        conditions=condition_label(user_query),
        candidates=candidate_label(user_cards),
    )
