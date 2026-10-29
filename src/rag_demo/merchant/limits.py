"""列表查询的 limit 钳制（纯函数，便于单测）。

为什么要有这一层：
- 商家数据层的查询会被 Agent Tool / API 直接调用，``limit`` 可能来自 LLM 生成的参数
  （``limit=100000``）或前端手填（``limit=0`` / 负数）。若透传进 SQL：
  轻则一次拉全表拖慢服务，重则把大商家的几十万订单读进内存。
- 所以**所有 list_* 查询统一走这里**：``None`` 用默认值，非法值回退默认值，
  小于 1 按 1 处理，超过上限按上限处理——既不报错（查询类接口不该因一个数字 400），
  也绝不放任它穿透到数据库。
"""
from __future__ import annotations

# 列表查询默认返回条数：与现有 C 端 / B 端接口的 20 保持一致
DEFAULT_LIST_LIMIT = 20
# 单次查询硬上限：即使调用方传 10 万，也最多读这么多行
MAX_LIST_LIMIT = 100


def clamp_limit(
    value: object,
    *,
    default: int = DEFAULT_LIST_LIMIT,
    maximum: int = MAX_LIST_LIMIT,
) -> int:
    """把调用方给的 limit 归一成 ``[1, maximum]`` 内的整数。

    参数:
        value:  任意调用方输入（None / int / 字符串 / 浮点 / 其他）
        default: value 缺失或无法转成整数时使用的默认值
        maximum: 硬上限（必须 >= 1）

    返回:
        1 <= 结果 <= maximum 的整数

    规则:
        None / 无法解析 -> max(1, min(default, maximum))
        <= 0          -> 1（"只看 0 条"没有意义，按最小页处理）
        > maximum     -> maximum
    """
    if int(maximum) < 1:
        raise ValueError("maximum 必须 >= 1")
    upper = int(maximum)

    if value is not None and not isinstance(value, bool):
        try:
            number = int(value)  # 兼容 "20" / 20.0 这类调用方
        except (TypeError, ValueError):
            number = None
        if number is not None:
            if number < 1:
                return 1
            return min(number, upper)
    elif isinstance(value, bool):
        # bool 是 int 的子类，但 limit=True 没有业务含义，按默认值处理
        value = None

    try:
        fallback = int(default)
    except (TypeError, ValueError):
        fallback = DEFAULT_LIST_LIMIT
    fallback = max(1, min(fallback, upper))
    return fallback


__all__ = ["DEFAULT_LIST_LIMIT", "MAX_LIST_LIMIT", "clamp_limit"]
