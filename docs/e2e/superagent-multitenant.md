# Super-agent 多租户隔离

> 日期：2026-11-02 · 状态：租户字段、API 过滤、Worker/动作作用域已完成

## 1. 数据模型

`sa_thread` 和 `sa_work_item` 新增：

```sql
merchant_id TEXT NOT NULL DEFAULT 'm_gear_002'
```

已有数据自动迁移为默认商家 `m_gear_002`。

```text
Thread     → 属于一个商家
WorkItem   → 属于一个商家
Trigger    → 通过 Thread 归属商家
```

## 2. Thread Key

默认商家保持历史 key：

```text
wecom:user:default
```

非默认商家自动加租户前缀：

```text
m_tea_001:wecom:user:default
```

避免不同商家使用相同 thread_key 时串数据。

## 3. API 作用域

```text
系统管理员  → 可跨租户查看/操作，可用 merchant_id 过滤
商家账号    → 只能看绑定商家的数据，merchant_id 被强制覆盖
```

接口：

```text
GET  /api/superagent/work-items?merchant_id=m_tea_001
GET  /api/superagent/threads?merchant_id=m_tea_001
POST /api/superagent/events  {merchant_id, ...}
```

越权访问：

```text
403 不能访问其他商家的数据
404 工作项不存在
```

`/jobs` 和全局 `/watchdog` 仅系统管理员可用。

## 4. Worker 工具作用域

每个 WorkItem 执行时设置：

```python
_CURRENT_MERCHANT.set(item["merchant_id"])
```

工具按当前商家过滤：

```text
query_order        → 校验订单属于当前商家
query_after_sales  → 过滤当前商家订单的售后
query_products     → 当前商家商品/库存
```

不会用一个商家的 Agent 查询另一个商家的订单或库存。

## 5. 动作执行作用域

```text
CANCEL_ORDER      → cancel_confirmed_order(merchant_id=...)
CREATE_AFTER_SALE → 校验订单属于当前商家
SHIP_ORDER        → 当前商家 update_order_status
COMPLETE_ORDER    → 当前商家 update_order_status
```

## 6. 企业微信

单应用单商家时配置：

```bash
QIANKE_WECOM_MERCHANT_ID=m_gear_002
```

回调、审批命令、结果回写都使用该租户范围。

多商家需要多企业微信应用/多个回调入口，后续再做映射表。

## 7. 真实 API 冒烟

创建租户事件：

```text
merchant_id: m_tea_001
thread_key:  m_tea_001:tenant-api-test
work_item:   saw_2eed5e77fd7b40d3
```

列表过滤：

```text
GET /work-items?merchant_id=m_tea_001
→ saw_2eed5e77fd7b40d3 / m_tea_001

GET /work-items?merchant_id=m_gear_002
→ saw_aee890acd66946da / m_gear_002
```

## 8. 测试

```bash
pytest tests/test_superagent.py::test_merchant_tenant_isolation -q
# 1 passed
```

完整套件：

```text
616 passed, 5 skipped, 1 warning
```

## 9. 已知限制

```text
企业微信一个应用只映射一个商家
CApp Trigger 仍默认 m_gear_002
没有租户管理页面（新增商家/绑定账号）
sa_job 没有 merchant_id，队列观测仍全局
自定义 Webhook 的 merchant_id 只做字符串校验，需要调用方自己保证可信
```
