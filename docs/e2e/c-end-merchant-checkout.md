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
# 448 passed, 5 skipped, 1 warning
```

新增覆盖：

```text
tests/test_merchant_write.py                     32 条（预占/释放/提交/订单幂等/并发/迁移）
tests/test_c_end_merchant_transactions.py         5 条（C 草稿预占、确认写商家订单、取消释放、重复确认、库存不足、订单列表）
tests/conftest.py                                 测试级商家库隔离
```

## 4. 已知限制

- 商家写层仍是 SQLite 本地 adapter，不是真实 OMS；生产需替换 adapter + 鉴权/支付/对账。
- C 端下单与商家写分属两个 SQLite 事务，没有分布式事务；当前用预占 + 幂等 + 补偿释放降低不一致，极端进程崩溃窗口仍需对账任务。
- 预占过期是懒清理（无后台 TTL worker）。
- 商家订单状态目前固定 CREATED，没有支付/发货状态流转。
- 浏览器 E2E 只跑了单次下单，未做并发下单/多买家竞争。
