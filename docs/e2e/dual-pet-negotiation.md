# 双宠谈判 v1 E2E

> 日期：2026-10-31 · 状态：通过（真实 CApp + 真实谈判 API）

## 1. 入口

C App：

```text
http://127.0.0.1:8000/v2/#/c/app
```

快捷问题区点击：

```text
让小鱼去砍价
```

固定使用：

```text
need = 跑鞋
budget = 500
quantity = 1
```

## 2. 真实浏览器结果

```text
用户：让小鱼去砍价：跑鞋，预算 ¥500

小鱼：我想在 ¥500.00 内买跑鞋，数量 1，你先报个能成交的方案。

山野店宠：轻量跑鞋，1 件，单价 ¥299.00，小计 ¥299.00，
          平台满减 -¥30.00，合计 ¥269.00。

小鱼：这个方案在预算内，可以接受；我把它记成报价，
      最后仍由用户确认。

山野店宠：报价已生成，成交仍需用户在商城逐单确认。
```

页面同时显示报价卡：

```text
来自店宠的结构化报价
轻量跑鞋 ¥299.00
平台满减活动
查看报价 →
```

「查看报价」跳转：

```text
/v2/#/c?quote=quote_neg_...
```

商城中仍需：

```text
准备订单 → 用户确认 → 创建订单
```

## 3. 接口

```text
POST /api/c/negotiations
{"need":"跑鞋","budget":500,"quantity":1}
```

返回：

```text
status: ACCEPTED | REJECTED
rounds
transcript: [{actor:"c_pet"|"b_pet", name, text}]
quote: PENDING 报价 | null
total_amount / discount_amount / policy_refs
reason: BUDGET_TOO_LOW | MERCHANT_NO_MATCH
```

## 4. 边界

```text
商品/库存来自商家数据层
优惠只来自平台满减（满 299 减 30 / 满 599 减 80）
店宠不能改价、发券、承诺赔付
C 伙伴不能自动下单
谈判达成只生成 PENDING 报价
```

## 5. 测试与构建

```bash
pytest tests/ -q
# 542 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 3.95s
```

谈判专项：

```text
tests/test_c_end_negotiation.py
4 passed
```

覆盖：

```text
预算 300 → P001 平台满减后 ¥269，接受并落报价
预算 200 → P001 超预算，同品类替代 P005 ¥129 接受
预算 50 → REJECTED / BUDGET_TOO_LOW
空需求/0 预算 → NEGOTIATION_INVALID
```

## 6. 已知限制

- 谈判 transcript 只作为当前会话消息展示，**未持久化**；刷新会消失。
- 谈判是确定性规则，不是自由 LLM 博弈；这是刻意的安全边界。
- 报价只有 PENDING 状态，用户需在商城逐单确认后才创建订单。
- 当前只有一个商家 `m_gear_002`，没有多商家比价。
- REJECTED 不会清空历史已存在的真实报价。
