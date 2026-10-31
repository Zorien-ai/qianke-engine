# 商家运营台 E2E

> 日期：2026-10-31 · 状态：通过（真实管理员会话 + 真实商家订单/售后数据）

## 1. 入口

```text
http://127.0.0.1:8000/v2/#/admin/c-end
```

页面三个视图：

```text
交易审计（只读，保留原有筛选/分页/CSV 导出）
商家订单（状态操作）
售后工单（审批）
```

## 2. 商家订单真实操作

实测订单 `order_6d1aa9f2fbf240ff`：

```text
CREATED -> 点击「标记已支付」 -> 200 / 已支付
PAID    -> 点击「发货」-> 填 ZTO1234567890 / 中通快递 -> 200 / 已发货
SHIPPED -> 点击「标记完成」 -> COMPLETED
```

操作后列表自动刷新，物流列显示：

```text
ZTO1234567890
中通快递
```

接口：

```text
GET   /api/c/admin/merchant/orders?limit=100&status=
PATCH /api/c/admin/merchant/orders/{order_id}/status
```

## 3. 售后工单真实审批

创建售后工单：

```text
order_9de1a7a765d94b2f
ticket as_631696a7f5cb4467
OPEN / 仅退款 / 运营台审批测试
```

运营台点击「通过」后：

```text
as_631696a7f5cb4467  APPROVED
退款金额 ¥199.00
处理时间 2026-10-31 07:56:52
toast：已通过工单 as_631696a7f5cb4467，退款已写入订单
```

接口：

```text
GET   /api/c/admin/after-sales?status=
PATCH /api/c/admin/after-sales/{ticket_id} {"approved":true}
```

## 4. 测试与构建

```bash
pytest tests/ -q
# 538 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 6.02s
```

新增 API 测试：

```text
tests/test_c_end_admin_merchant_orders.py
2 passed
```

## 5. 已知限制

- 商家订单状态操作没有二次确认（发货有表单确认）；取消/完成是直接操作。
- 无操作人/操作原因审计字段。
- 商家订单列表最多 100 条，无分页。
- 售后通过是本地模拟退款，无支付网关/退货物流。
- 管理员可操作所有商家，当前只有单店 `m_gear_002`。
