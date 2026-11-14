# B 端 2.0 P0：批量改库存

日期：2026-11-14

## 范围

```text
商品视图新增「批量改库存」
仅调整 SET_AVAILABLE（可售量），不动 reserved/safety
必须选择仓库；不允许默认第一仓
预检 → 逐 SKU 展示 before/after/状态
提交 → 逐 SKU 结果、审计 event_id
最多 50 SKU，单仓单 SKU 原子更新
```

## API

```text
GET  /api/b/workbench/inventory/capabilities
POST /api/b/workbench/inventory/preview
POST /api/b/workbench/inventory/batch
```

提交使用 `client_request_id` 幂等键，按
`(merchant_id, actor_id, client_request_id, item_id)` 持久化结果。
库存调整是真实写入，不标 SIMULATED；响应使用 `transaction_mode=INVENTORY_WRITE`。
库存更新 + 审计事件同事务；失败行返回 `error_code`，其他行可成功。

## 真实接口验收

账号：`test_b_image`

```text
SKU：SKU-TEA-001-250G
仓库：WH-HZ-01（SKU 有 2 个仓：WH-HZ-01 / WH-SH-01）
缺少 warehouse_id 的预览：HTTP 422
预览：UNCHANGED / expected_available=35
未变化提交：SUCCEEDED，1 个 UNCHANGED
+1 提交：SUCCEEDED，after=36
还原：SUCCEEDED，after=35
```

## 浏览器验收

```text
商品 → 批量改库存
弹层 16 个 SKU，仓库下拉 2 个仓
选择首个 SKU，目标填 35（空目标不会被暗写成 0）
预检状态 UNCHANGED，提交按钮可用
提交结果：SUCCEEDED · 成功 0 / 失败 0 / 未变 1
```

![批量改库存](docs/design/b-end-2.0-p0-prod-inventory-batch.png)

## 测试

```text
全量 pytest：795 passed, 5 skipped
前端 build：PASS
新增：
  预览 + 提交 + 幂等重放
  重复 SKU 422
  部分成功 PARTIAL_SUCCESS
  PG schema 表清单更新
```

## 已知限制

```text
没有 inventory_version 列；并发保护使用 available/reserved 条件更新
没有批次级 GET/恢复接口和跨 worker 租约
批次不是单事务；已成功行不会因后续失败自动回滚
前端目标默认为空，必须手填；单次最多 50 个已选 SKU
没有 PHYSICAL_COUNT（实物盘点）
没有多仓调拨；预览/提交必须由用户显式选择仓库
前端一次最多提交当前筛选商品的 SKU，未做跨页选择全部
旧订单状态 PATCH 仍是模拟交易入口，支付/完成审计契约尚未落地
```
