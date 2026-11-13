"""C 端问题 Router：只做意图分流和槽位抽取，不生成答案。

规则优先，保证高频请求低延迟、可测试；保留 ``requested_mode`` 让前端显式
指定模式。后续可以在低置信度分支注入 LLM 分类器，而不改变路由契约。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

ROUTE_COMPANION: Final = "companion"
ROUTE_SHOPPING: Final = "shopping"
ROUTE_ORDER: Final = "order"
ROUTE_TRANSACTION: Final = "transaction"
ROUTES: Final = (ROUTE_COMPANION, ROUTE_SHOPPING, ROUTE_ORDER, ROUTE_TRANSACTION)

MODE_COMPANION: Final = "companion"
MODE_ADVISOR: Final = "advisor"
MODE_ORDER: Final = "order"
MODE_TRANSACTION: Final = "transaction"
MODES: Final = (MODE_COMPANION, MODE_ADVISOR, MODE_ORDER, MODE_TRANSACTION)

ROUTE_TO_MODE: Final = {
    ROUTE_COMPANION: MODE_COMPANION,
    ROUTE_SHOPPING: MODE_ADVISOR,
    ROUTE_ORDER: MODE_ORDER,
    ROUTE_TRANSACTION: MODE_TRANSACTION,
}
MODE_TO_ROUTE: Final = {mode: route for route, mode in ROUTE_TO_MODE.items()}

_TRANSACTION_RE = re.compile(
    r"确认(?:订单|下单)|取消(?:订单|草稿)|直接(?:下单|出草稿)|下单|购买|"
    r"(?:我要|帮我|给我)买|买一(?:件|个|双|份|盒|罐|斤)|买两|来一(?:件|个|双|份|盒|罐|斤)|"
    r"生成订单|准备订单|订单草稿|改地址|改数量|支付|付款"
)
_ORDER_RE = re.compile(
    r"我的订单|订单(?:号|状态|详情|记录)|物流|快递|运单|发货|到哪|签收|"
    r"售后|退款|退货|换货|退款进度|取消退款"
)
_SHOPPING_RE = re.compile(
    r"推荐|挑(?:一|个|选)?|选(?:一|个|款)?|对比|预算|价格|多少钱|优惠|活动|"
    r"商品|产品|图片|看图|看看图|我要看看|看看|实拍|库存|现货|有没有|有什么|哪款|怎么选|"
    r"茶叶|绿茶|红茶|乌龙|普洱|白茶|黑茶|花茶|跑鞋|双肩包|水壶|冲锋衣|"
    r"砍价|议价|便宜点|能便宜"
)
_PREFERENCE_RE = re.compile(
    r"我(?:喜欢|不喜欢|讨厌|习惯|平时|一般|通常|叫|是|住)|"
    r"别给我|不要给我|不用给我|不需要给我|我不想要|别再给我|不要推荐|不用推荐"
)
_NEGATED_SHOPPING_RE = re.compile(r"(?:别|不要|不用|不需要|不想).{0,8}(?:推荐|买|挑|选)")

_BUDGET_RE = re.compile(
    r"(?:预算|不超过|最多|以内|上限)\s*[¥￥]?\s*(\d+(?:\.\d+)?)|"
    r"[¥￥]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:元|块钱|块|以内)"
)
_ORDER_ID_RE = re.compile(r"\b(order_[A-Za-z0-9_]+)\b")


@dataclass(frozen=True)
class RouterDecision:
    route: str
    mode: str
    confidence: float
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "mode": self.mode,
            "confidence": self.confidence,
            "slots": dict(self.slots),
            "reason": self.reason,
            "source": self.source,
        }


def _first_number(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    for value in match.groups():
        if value not in (None, ""):
            try:
                return float(value)
            except ValueError:
                return None
    return None


def extract_slots(message: str) -> dict[str, Any]:
    text = str(message or "").strip()
    slots: dict[str, Any] = {}
    budget = _first_number(_BUDGET_RE.search(text))
    if budget is not None and budget >= 0:
        slots["budget"] = budget
    order_id = _ORDER_ID_RE.search(text)
    if order_id:
        slots["order_id"] = order_id.group(1)
    if text:
        slots["query"] = text[:120]
    return slots


def _decision(
    route: str,
    *,
    confidence: float,
    reason: str,
    slots: dict[str, Any],
    source: str = "rules",
) -> RouterDecision:
    return RouterDecision(
        route=route,
        mode=ROUTE_TO_MODE[route],
        confidence=confidence,
        slots=slots,
        reason=reason,
        source=source,
    )


def route_question(message: str, *, requested_mode: str | None = None) -> RouterDecision:
    """把一条用户消息路由到四类之一；不调用模型、不产生副作用。"""
    text = str(message or "").strip()
    slots = extract_slots(text)
    if requested_mode in MODES:
        route = MODE_TO_ROUTE[requested_mode]
        return _decision(
            route,
            confidence=1.0,
            reason=f"客户端显式指定 {requested_mode} 模式",
            slots=slots,
            source="explicit",
        )
    if not text:
        return _decision(
            ROUTE_COMPANION,
            confidence=0.95,
            reason="空消息按陪伴处理",
            slots=slots,
        )
    # 交易意图优先于查询意图：避免“确认订单”被当成订单状态查询。
    if _TRANSACTION_RE.search(text):
        return _decision(
            ROUTE_TRANSACTION,
            confidence=0.93,
            reason="命中下单/确认/改单等交易动作",
            slots=slots,
        )
    if _ORDER_RE.search(text):
        return _decision(
            ROUTE_ORDER,
            confidence=0.9,
            reason="命中订单/物流/售后查询",
            slots=slots,
        )
    # 用户在陈述偏好/边界，而不是发起购物请求。
    if _PREFERENCE_RE.search(text) and (
        _NEGATED_SHOPPING_RE.search(text) or not _SHOPPING_RE.search(text)
    ):
        return _decision(
            ROUTE_COMPANION,
            confidence=0.8,
            reason="用户在陈述个人偏好/边界，不是本轮购物指令",
            slots=slots,
        )
    if _SHOPPING_RE.search(text):
        return _decision(
            ROUTE_SHOPPING,
            confidence=0.86,
            reason="命中商品/价格/图片/购物参谋意图",
            slots=slots,
        )
    return _decision(
        ROUTE_COMPANION,
        confidence=0.62,
        reason="没有命中商品/订单/交易信号，按陪伴处理",
        slots=slots,
    )
