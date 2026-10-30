"""商家数据层的 Repository 接口（可替换适配器的契约）。

本模块定义两个协议：
- ``MerchantRepository``：**只读**查询（商品 / SKU / 库存 / 订单）；
- ``MerchantWriteRepository``：**受控写入**（库存预占 + 订单写入，task-43）。

为什么用 ``Protocol`` 而不是继承某个 SQLite 基类：
- 未来接真实 OMS/PG 时，适配器**不需要**依赖本项目的 SQLite 实现或任何第三方基类，
  只要「长得像」对应协议即可被注入（结构化鸭子类型）；
- 测试可以塞一个内存 Fake 进来验证业务层不绑死 SQLite；
- ``runtime_checkable`` 只给测试做 isinstance 断言，运行期不靠它做安全判断。

调用约定（所有 adapter 必须遵守）
--------------------------------
1. **租户隔离**：``list_products`` / ``list_orders`` 的 ``merchant_id`` 必填，且
   空值必须**失败关闭**（抛 ``MerchantDataError``），禁止退化成全表查询。
   ``get_*`` 的 ``merchant_id`` / ``buyer_id`` 是可选作用域，传入时必须同时匹配。
2. **limit 钳制**：所有列表方法内部必须经过 :func:`rag_demo.merchant.limits.clamp_limit`。
3. **读写能力分离**：只读 adapter 只实现 ``MerchantRepository``；需要预占/订单写入的
   adapter 额外实现 ``MerchantWriteRepository``。真实 OMS 写操作必须走独立确认流程，
   不能把写权限给只读查询路径。
4. **返回模型**：返回 :mod:`rag_demo.merchant.models` 里的 frozen dataclass（或 ``None``），
   不要返回裸 dict——模型是跨 adapter 的统一契约。
5. **金额**：模型里是 ``Decimal``，adapter 不得用 float 中转。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .limits import DEFAULT_LIST_LIMIT
from .models import Inventory, Order, Product, Reservation, SKU


@runtime_checkable
class MerchantRepository(Protocol):
    """商家商品/库存/订单查询接口（只读）。"""

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


@runtime_checkable
class MerchantWriteRepository(Protocol):
    """商家数据层**写接口**（库存预占 + 订单写入，task-43）。

    为什么与只读 ``MerchantRepository`` 分成两个协议：
    - 只读消费者（C 端商品/订单查询）不需要、也不应该拿到写能力；
    - 只读 adapter（或未来某些 OMS 的只读账号）可以不实现本协议，
      :func:`rag_demo.merchant.factory.get_merchant_write_repository` 会明确拒绝；
    - 调用方用 ``get_merchant_write_repository()`` 拿写能力，边界一眼可见。

    写操作的硬约束（adapter 必须遵守）：
    1. **事务化**：库存扣减/恢复与预占、订单记录必须在同一事务内，要么全成功要么全回滚；
    2. **幂等**：同一 ``reservation_id`` / ``order_id`` 重复调用不能重复扣库存/重复写订单；
    3. **失败关闭**：库存不足、参数非法、未知/过期预占必须抛结构化错误（见 errors.py），
       不允许「部分成功」或静默降级；
    4. **租户必填**：所有写的 ``merchant_id`` 必填；未知/其他租户的对象一律按不存在处理，
       不泄露跨租户信息。``merchant_id`` 必须由上层从**已认证的会话**推导，不能来自用户输入；
    5. **不是真实 OMS 写通道**：SQLite adapter 只是本地演示/测试实现，
       真实交易写必须走 OMS 的受控接口 + 人工确认（见 docs/merchant-integration-v1.md）。
    """

    backend: str

    def reserve_inventory(
        self,
        merchant_id: str,
        reservation_id: str,
        items: list[dict[str, Any]],
        ttl_seconds: int = 900,
        *,
        buyer_id: str | None = None,
    ) -> Reservation:
        """按当前库存预占（available 扣减、reserved 增加）；库存不足抛 MERCHANT_STOCK。

        items 每项至少包含 ``sku`` 或 ``product_id`` 与正整数 ``quantity``；
        同一 SKU 不得重复出现。``buyer_id`` 可选（HITL 场景用于把预占绑定到买家）。
        """
        ...

    def commit_reservation(
        self,
        merchant_id: str,
        reservation_id: str,
        order_id: str | None = None,
    ) -> Reservation:
        """把预占提交为订单占用：available 保持扣减、reserved 转出；幂等。"""
        ...

    def release_reservation(self, merchant_id: str, reservation_id: str) -> Reservation:
        """释放预占并恢复库存；重复释放幂等，已提交的预占拒绝释放。"""
        ...

    def create_order(
        self,
        merchant_id: str,
        order_id: str,
        buyer_id: str,
        items: list[dict[str, Any]],
        total_amount: Any,
        source_ref: str | None = None,
    ) -> Order:
        """幂等写入订单（同 order_id 返回已有订单）；校验订单行小计与总金额一致。

        注意：create_order **只写订单记录，不改库存**。需要库存控制时先
        ``reserve_inventory``，再 ``commit_reservation(..., order_id=...)``。
        """
        ...

    def update_order_status(
        self,
        merchant_id: str,
        order_id: str,
        status: str,
        tracking_no: str | None = None,
        carrier: str | None = None,
    ) -> Order:
        """订单状态机流转（幂等；只允许合法迁移）。

        合法迁移：``CREATED->PAID->SHIPPED->COMPLETED``；``CREATED/PAID->CANCELLED``；
        ``SHIPPED/COMPLETED->REFUNDED`` **只能**通过 :meth:`refund_order`（需要退款金额），
        本方法传 ``status=REFUNDED`` 会抛 ``MERCHANT_INVALID``，避免无金额退款绕过审计。
        - 同状态重复调用返回已有订单（幂等，不重复写时间戳）；
        - 非法迁移抛 ``MERCHANT_CONFLICT``，未知状态/参数非法抛 ``MERCHANT_INVALID``；
        - 流转到 ``SHIPPED`` 必须提供合法 ``tracking_no``（v1 规则：4~64 位字母/数字/``-_.``），
          ``carrier`` 可选；其它状态不允许携带物流字段；
        - 自动写状态时间：PAID→``paid_at``、SHIPPED→``shipped_at``、COMPLETED→``completed_at``；
        - 流转到 ``CANCELLED`` 与 :meth:`cancel_order` 语义一致（模拟退款 + 库存恢复），
          区别只是没有 ``request_id`` 幂等键；业务代码应优先用 ``cancel_order``；
        - 未知订单/跨租户一律 ``MERCHANT_NOT_FOUND``；``merchant_id`` 必填。
        """
        ...

    def refund_order(
        self,
        merchant_id: str,
        order_id: str,
        amount: Any = None,
        request_id: str | None = None,
    ) -> Order:
        """售后退款（SHIPPED/COMPLETED → REFUNDED；部分/全额；默认不恢复库存；幂等）。

        业务规则（task-49）：
        - 只允许 ``SHIPPED`` / ``COMPLETED`` → ``REFUNDED``；``CREATED`` / ``PAID`` 未发货，
          应走 :meth:`cancel_order`（``MERCHANT_CONFLICT``）；``CANCELLED`` 拒绝；
        - ``amount``：None → 默认订单全额 ``total_amount``；必须是有限正数、最多 2 位小数、
          且 ``<= total_amount``；非法金额 ``MERCHANT_INVALID``；
        - 写 ``refund_amount = amount``、``refunded_at = now``；保留已有时序字段
          （``paid_at/shipped_at/completed_at``、物流字段）与 ``cancelled_at=None``；
        - **默认不恢复库存**：售后退货验收入库是独立流程，本方法不改库存/预占
          （即使订单有 COMMITTED 预占也不动，避免把未验收商品凭空加回可售库存）；
        - 重复退款幂等：已 ``REFUNDED`` 时，同 ``request_id``（或未传 request_id 且金额相同）
          返回已有订单，不重复写时间/金额；金额或 request_id 不匹配 → ``MERCHANT_CONFLICT``；
        - ``request_id`` 幂等键：同 key 跨订单 → ``MERCHANT_CONFLICT``；空白/超长 →
          ``MERCHANT_INVALID``；
        - 事务化（`BEGIN IMMEDIATE`）、租户隔离（未知/跨租户 ``MERCHANT_NOT_FOUND``）、
          ``merchant_id`` 必填。
        """
        ...

    def cancel_order(
        self,
        merchant_id: str,
        order_id: str,
        request_id: str | None = None,
    ) -> Order:
        """取消订单（模拟退款 + 按已提交预占的 allocations 恢复库存；幂等）。

        业务规则：
        - 只允许 ``CREATED`` / ``PAID`` → ``CANCELLED``；``SHIPPED`` / ``COMPLETED`` 拒绝
          （``MERCHANT_CONFLICT``）；重复取消返回已有订单（幂等，不重复退款/恢复库存）；
        - PAID 取消写入模拟退款：``refund_amount = total_amount``、``refunded_at = now``；
          CREATED 取消：``refund_amount = 0``、``refunded_at = None``；
        - 库存恢复：只按**已提交预占**（``m_reservation.order_id`` 指向本订单且状态 COMMITTED）
          的仓库 allocations 逐仓 `available_qty += q`，随后预占标记 ``REVERSED``；
          没有预占的订单（如种子订单/直接 create_order）**不凭空补库存**（允许取消，库存不变）；
        - 事务化（`BEGIN IMMEDIATE`）；``request_id`` 作为幂等键：同 request_id 重放返回同一结果，
          同 request_id 用于取消其他订单 → ``MERCHANT_CONFLICT``；
        - ``merchant_id`` 必填、租户隔离（未知/跨租户 `MERCHANT_NOT_FOUND`）。
        """
        ...


__all__ = ["MerchantRepository", "MerchantWriteRepository"]
