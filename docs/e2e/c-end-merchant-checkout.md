# C 端下单 → 商家库存/订单闭环 E2E

> 日期：2026-10-30 · 状态：通过（真实 API + 浏览器 UI）

## 1. 验收链路

```text
小鱼：看 500 元以内的跑鞋，买 1 双，直接生成待确认订单
→ C Agent prepare_order
→ 商家库存预占（P001：20 → 19）
→ 用户点击「确认并创建订单」
→ 商家订单写入（order_...，CREATED，source_ref=draft_...）
→ C 端库存扣减（20 → 19）
→ CApp 右侧最近订单显示 M + 已创建
```

## 2. 真实执行结果

浏览器：Chrome DevTools MCP，真实页面 `http://127.0.0.1:8000/v2/#/c/app`。

```text
点击快捷问题「看 500 元以内的跑鞋」
→ 返回「已处理，请查看当前待确认信息。」
→ 右侧待确认卡：轻量跑鞋 ¥299.00
→ 点击「确认并创建订单」
→ 消息：订单 order_6bf23b016e5e41fe 已创建 · ¥299.00
→ 最近订单：M 标记、轻量跑鞋、10 月 30 日 · 已创建、¥299
```

接口核对：

```text
GET /api/c/orders?limit=3
order_6bf23b016e5e41fe
merchant_order_id = order_6bf23b016e5e41fe
merchant_status = CREATED
merchant_source = merchant_v1

merchant inventory SKU-GEAR-P001-STD = 19
merchant order = CREATED / 299.00 / buyer b_2001
```

## 3. 自动化测试

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
# 511 passed, 5 skipped, 1 warning
```

新增覆盖：

```text
tests/test_merchant_store.py                     46 条（种子/查询/物流/取消字段）
tests/test_merchant_write.py                     72 条（预占/订单/状态机/取消退款/库存补偿/并发/迁移）
tests/test_c_end_merchant_transactions.py         9 条（C 草稿预占、确认、取消、退款、物流时间线、对账）
tests/conftest.py                                 测试级商家库隔离
```

## 4. 订单状态与物流（P1）

管理员模拟商家状态流转：

```text
PATCH /api/c/admin/merchant/orders/{order_id}/status
{"status":"PAID"}
{"status":"SHIPPED","tracking_no":"SF1234567890","carrier":"顺丰速运"}
{"status":"COMPLETED"}
```

真实执行结果：

```text
PAID       200  status=PAID
SHIPPED    200  status=SHIPPED tracking_no=SF1234567890
COMPLETED  200  status=COMPLETED

GET /api/c/orders?limit=3
order_6bf23b016e5e41fe
merchant_status=COMPLETED
merchant_tracking_no=SF1234567890
merchant_carrier=顺丰速运
merchant_timeline 4 条
```

C 订单页实测：

```text
已完成
状态时间线 最近更新 10-30 09:25
已创建 10-30 08:09
已支付 10-30 09:25
已发货 10-30 09:25
已完成 10-30 09:25
承运商 顺丰速运
运单号 SF1234567890
```

CApp 最近订单实测：

```text
M 轻量跑鞋 10 月 30 日 · 已完成 顺丰速运 · …7890 ¥299
```

小鱼实测：

```text
查到你 5 笔订单，只有一笔有运单号：
顺丰速运 SF1234567890，对应 order_6bf23b016e5e41fe
（轻量跑鞋，299 元，已完成）。
```

C 端订单返回：

```text
merchant_status
merchant_tracking_no
merchant_carrier
merchant_status_at
merchant_timeline = [{status, at}, ...]
```

C 订单页展示四步时间线（已创建 → 已支付 → 已发货 → 已完成）和物流单号；CApp 最近订单显示承运商/单号后四位。旧平台订单（无商家字段）保持原样式。

状态机：

```text
CREATED -> PAID -> SHIPPED -> COMPLETED
CREATED/PAID -> CANCELLED
```

约束：

```text
SHIPPED 必须提供合法 tracking_no
同状态重复调用幂等
已发货后不能悄悄改物流单号/承运商
跨租户按不存在处理
```

## 5. 取消 / 退款 / 对账（P1-B）

C 端取消已确认订单：

```text
POST /api/c/orders/{order_id}/cancel
{"request_id":"req_c_cancel_001"}
```

行为：

```text
商家侧：CREATED/PAID -> CANCELLED
  PAID 取消 refund_amount=total_amount / refunded_at=now
  CREATED 取消 refund_amount=0 / refunded_at=null
  按已提交预占 allocations 恢复商家库存
C 端：恢复 C 库存，C 订单标记 CANCELLED，列表仍展示
```

实测：

```text
PAID 订单 order_4c0875ac0225421d 取消
→ 页面「已取消」，退款 ¥129.00，取消时间 10-30 13:12
→ 时间线出现红色「已取消」
→ 商家/ C 库存恢复
```

对账：

```text
GET /api/c/admin/reconciliation
```

实测：

```text
{"checked":3,"legacy":6,"issues":[],"ok":true}
```

对账检查：

```text
C 已确认 / 商家已取消 → STATUS_DIVERGENCE
C 已取消 / 商家未取消 → STATUS_DIVERGENCE
原始金额与商家金额不一致 → AMOUNT_DIVERGENCE
旧平台订单单独计数 legacy
```

## 6. 已知限制

- 商家写层仍是 SQLite 本地 adapter，不是真实 OMS；生产需替换 adapter + 鉴权/支付/对账。
- C 端下单与商家写分属两个 SQLite 事务，没有分布式事务；当前用预占 + 幂等 + 补偿释放降低不一致，极端进程崩溃窗口仍需对账任务。
- 预占过期是懒清理（无后台 TTL worker）。
- 订单状态流转目前由平台管理员模拟，不是真实商家后台/OMS 回调。
- 退款为本地模拟，没有支付网关/退款单号/部分退款/售后审核。
- 浏览器 E2E 只跑了单次下单与取消，未做并发下单/多买家竞争。
