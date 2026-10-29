"""商家数据层的 Repository 接口（可替换适配器的唯一契约）。

为什么用 ``Protocol`` 而不是继承某个 SQLite 基类：
- 未来接真实 OMS/PG 时，适配器**不需要**依赖本项目的 SQLite 实现或任何第三方基类，
  只要「长得像」这个协议即可被注入（结构化鸭子类型）；
- 测试可以塞一个内存 Fake 进来验证业务层不绑死 SQLite；
- ``runtime_checkable`` 只给测试做 isinstance 断言，运行期不靠它做安全判断。

调用约定（所有 adapter 必须遵守）
--------------------------------
1. **租户隔离**：``list_products`` / ``list_orders`` 的 ``merchant_id`` 必填，且
   空值必须**失败关闭**（抛 ``MerchantDataError``），禁止退化成全表查询。
   ``get_*`` 的 ``merchant_id`` / ``buyer_id`` 是可选作用域，传入时必须同时匹配。
2. **limit 钳制**：所有列表方法内部必须经过 :func:`rag_demo.merchant.limits.clamp_limit`。
3. **只读**：v1 数据层不做 reservation/写入；真实 OMS 写操作必须走独立确认流程。
4. **返回模型**：返回 :mod:`rag_demo.merchant.models` 里的 frozen dataclass（或 ``None``），
   不要返回裸 dict——模型是跨 adapter 的统一契约。
5. **金额**：模型里是 ``Decimal``，adapter 不得用 float 中转。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .limits import DEFAULT_LIST_LIMIT
from .models import Inventory, Order, Product, SKU


@runtime_checkable
class MerchantRepository(Protocol):
    """商家商品/库存/订单查询接口（只读 v1）。"""

    #: 后端标识（"sqlite" / "postgres" / "oms" …），用于日志与诊断
    backend: str

    def describe(self) -> dict[str, Any]:
        """后端自描述：backend / db 位置 / 数据规模等，供健康检查与文档排障。"""
        ...

    def list_products(
        self,
        merchant_id: str,
        keyword: str | None = None,
        limit: int | None = DEFAULT_LIST_LIMIT,
    ) -> list[Product]:
        """按商家列出商品（可按标题/类目/品牌关键词模糊过滤，limit 钳制）。"""
        ...

    def get_product_sku(self, sku: str, *, merchant_id: str | None = None) -> SKU | None:
        """按 SKU 取规格与价格；传 merchant_id 时同时校验租户归属，不匹配返回 None。"""
        ...

    def list_product_skus(
        self, product_id: str, *, merchant_id: str | None = None
    ) -> list[SKU]:
        """列出一个商品下的全部 SKU（商品页展示用）。"""
        ...

    def get_inventory(self, sku: str, *, merchant_id: str | None = None) -> Inventory | None:
        """SKU 的跨仓库存汇总；不存在（或租户不匹配）返回 None。

        注意：返回 None 表示「这个 SKU 没有库存记录」，与「有记录但可售为 0」不同——
        后者返回 ``Inventory`` 且 ``available_qty == 0`` / ``in_stock is False``。
        """
        ...

    def list_orders(
        self,
        merchant_id: str,
        buyer_id: str | None = None,
        status: str | None = None,
        limit: int | None = DEFAULT_LIST_LIMIT,
    ) -> list[Order]:
        """按商家列出订单（可再按买家/状态过滤，limit 钳制，含订单行快照）。"""
        ...

    def get_order(
        self,
        order_id: str,
        *,
        merchant_id: str | None = None,
        buyer_id: str | None = None,
    ) -> Order | None:
        """按订单号取订单；传 merchant_id / buyer_id 时同时校验作用域，不匹配返回 None。"""
        ...

    def close(self) -> None:
        """释放 adapter 持有的资源（连接/句柄）；可重复调用。"""
        ...


__all__ = ["MerchantRepository"]
