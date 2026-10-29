"""商家数据层的结构化错误。

为什么不用裸 ``ValueError`` / ``RuntimeError``：
- 调用方（Agent Tool / API 层）需要按 **错误类型** 做分支（配置错 vs 数据错 vs 后端不可用），
  而不是去匹配英文报错字符串——后者一改文案就静默失效；
- 每个错误都带稳定的 ``code``，可直接进结构化 JSON 返回，符合项目的 Tool 错误约定。
"""
from __future__ import annotations


class MerchantError(Exception):
    """商家数据层错误基类：所有可预期错误都有稳定的 code。"""

    code = "MERCHANT_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def to_dict(self) -> dict[str, str]:
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


__all__ = [
    "MerchantConfigurationError",
    "MerchantDataError",
    "MerchantError",
    "MerchantSeedError",
    "MerchantUnavailableError",
]
