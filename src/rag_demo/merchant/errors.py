"""商家数据层的结构化错误。

为什么不用裸 ``ValueError`` / ``RuntimeError``：
- 调用方（Agent Tool / API 层）需要按 **错误类型** 做分支（配置错 vs 数据错 vs 后端不可用），
  而不是去匹配英文报错字符串——后者一改文案就静默失效；
- 每个错误都带稳定的 ``code``，可直接进结构化 JSON 返回，符合项目的 Tool 错误约定。
"""
from __future__ import annotations

from typing import Any


class MerchantError(Exception):
    """商家数据层错误基类：所有可预期错误都有稳定的 code。"""

    code = "MERCHANT_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class MerchantConfigurationError(MerchantError):
    """配置/后端选择错误：未知 backend、缺依赖、参数非法到无法初始化。"""

    code = "MERCHANT_CONFIG"


class MerchantSeedError(MerchantError):
    """种子数据错误：文件缺失、列缺失、引用不一致、订单金额对不上、低于最小规模。"""

    code = "MERCHANT_SEED"


class MerchantDataError(MerchantError):
    """查询参数错误（例如多租户查询缺少 merchant_id），属于调用方问题。"""

    code = "MERCHANT_DATA"


class MerchantUnavailableError(MerchantError):
    """数据层不可用：已关闭、文件不可读写等运行期问题。"""

    code = "MERCHANT_UNAVAILABLE"


# ==================== 写操作错误（task-43） ====================
# 写路径的失败必须**结构化成不同 code**，调用方才能决定下一步：
#   库存不足 → 提示换规格/等补货；幂等冲突 → 不要重试；过期 → 重新预占；
#   参数/金额错 → 修业务参数。全部严禁「字符串匹配错误文案」。
class MerchantInvalidError(MerchantError):
    """写请求参数非法：缺字段、数量非正、SKU 重复、金额与订单行不一致等。"""

    code = "MERCHANT_INVALID"


class MerchantNotFoundError(MerchantError):
    """写操作引用的对象不存在（或不属于当前租户，租户隔离时统一按不存在处理）。"""

    code = "MERCHANT_NOT_FOUND"


class MerchantConflictError(MerchantError):
    """状态/幂等冲突：reservation 已被不同请求占用、已释放/已提交、order_id 被其他租户占用等。"""

    code = "MERCHANT_CONFLICT"


class MerchantExpiredError(MerchantError):
    """预占已过期（提交时发现）；库存已释放，需要重新预占。"""

    code = "MERCHANT_EXPIRED"


class MerchantStockError(MerchantError):
    """库存不足：失败关闭，调用方应换规格/等补货，而不是重试同一请求。"""

    code = "MERCHANT_STOCK"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        if self.details:
            data["details"] = self.details
        return data


class MerchantInternalError(MerchantError):
    """内部数据一致性问题（例如库存账实不符、预占记录损坏）；需要人工排查。"""

    code = "MERCHANT_INTERNAL"


__all__ = [
    "MerchantConfigurationError",
    "MerchantConflictError",
    "MerchantDataError",
    "MerchantError",
    "MerchantExpiredError",
    "MerchantInternalError",
    "MerchantInvalidError",
    "MerchantNotFoundError",
    "MerchantSeedError",
    "MerchantStockError",
    "MerchantUnavailableError",
]
