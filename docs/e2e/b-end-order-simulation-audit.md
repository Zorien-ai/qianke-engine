# B 端 2.0：模拟支付/完成审计

日期：2026-11-14

## 范围

```text
新增独立模拟动作接口
POST /api/b/workbench/orders/{id}/simulation-actions
GET  /api/b/workbench/orders/{id}/simulation-actions/{client_request_id}

SIMULATE_PAYMENT：CREATED → PAID
SIMULATE_COMPLETION：SHIPPED → COMPLETED
```

旧 `PATCH /orders/{id}/status` 的 PAID/COMPLETED 返回 409，必须走模拟动作接口。
SHIPPED/CANCELLED 仍保留原路径。

## 审计

```text
m_order_simulation_action
action_id / merchant_id / order_id / actor_id / client_request_id
action / before_status / after_status
transaction_mode=SIMULATED / is_simulated=1
amount / currency / reason / created_at
```

订单状态、时间字段、动作审计同一事务；按
`(merchant_id, actor_id, client_request_id)` 幂等。
同键同参数返回原动作；同键不同 order/action/amount/currency/reason 返回冲突。
唯一键并发冲突用 INSERT ... ON CONFLICT DO NOTHING 回读原动作，不返回 500。

## 真实接口验收

```text
账号：test_b_image
CREATED 订单：order_1579fdd829d7443a
模拟支付：oact_cac15f1d15294a17a7725617c2868398
before_status=CREATED / after_status=PAID / is_simulated=1
同请求重放：返回同一 action_id
GET 查回：同一 action_id
旧 PATCH COMPLETED：HTTP 409
```

## 浏览器验收

```text
订单 → 待支付订单 → 详情
模拟支付（演示）→ 确认写入模拟状态
toast：模拟支付已写入审计 · cadb99e6
抽屉状态变为：已支付
订单表格刷新为：已支付
```

![模拟支付审计](docs/design/b-end-2.0-p0-prod-simulation-audit.png)

## 测试

```text
全量 pytest：796 passed, 6 skipped
前端 build：PASS
新增：
  SHIPPED → COMPLETED 模拟动作 + 重放 + GET 查回
  旧 PATCH COMPLETED 409
  CREATED → PAID 模拟动作（种子有 CREATED 时）
  同键不同金额冲突
  PG schema 表清单更新
```

## 已知限制

```text
仍没有 order_version 列；并发保护依赖状态 + 幂等键
SHIPPED/CANCELLED 没有走同一动作审计表（后续统一）
没有订单动作审计读取 UI
没有真实支付回调；transaction_mode 固定 SIMULATED
退款/跨月口径仍按设计文档待实现
```
