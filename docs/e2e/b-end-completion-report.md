# B 端 2.0：经营报告（完成口径）

日期：2026-11-14

## 范围

```text
GET /api/b/workbench/reports/completion?date_from&date_to
店主/管理员可用；staff 403
服务端全量聚合，不受订单列表 limit 影响
完成口径按 completed_at；退款按 refunded_at 发生期冲减
```

返回：

```text
completed_orders / completed_gmv
refund_orders / refund_amount
net_amount
cohort_refund_amount / cohort_net_amount
currencies
daily
period / simulation_mode / note
```

## 真实接口验收

```text
账号：test_b_image
范围：2026-10-01 至 2026-10-31
完成订单：1
完成 GMV：602.00
退款：0
完成订单群净额：602.00
按日：2026-10-04 / 1 单 / ¥602.00
```

## 浏览器验收

```text
侧栏：经营分析 → 经营报告
日期：2026-10-01 至 2026-10-31
5 张指标卡：完成 GMV / 完成订单 / 期间退款 / 期间净额 / 完成订单群净额
按日表格 1 行
1440 视口：scrollWidth = clientWidth = 1425
```

![经营报告](docs/design/b-end-2.0-p0-prod-completion-report.png)

## 测试

```text
全量 pytest：798 passed, 6 skipped
前端 build：PASS
新增：店主报告可读、staff 403、日期范围/日汇总
```

## 已知限制

```text
完成 GMV 为多币种简单相加；多币种时应按币种分开读
退款字段仍是单笔 refund_amount，不是多笔退款事件账本
没有导出按钮
没有 order_version
报告只读，不做实时推送
```
