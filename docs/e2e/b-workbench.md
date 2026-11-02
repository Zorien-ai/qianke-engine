# B 端商家工作台 E2E

> 日期：2026-11-02 · 状态：通过（真实商家租户 API + 真实 `/v2/b.html`）

## 1. 入口

```text
http://127.0.0.1:8000/v2/b.html
```

独立页面，不依赖 SPA router；未登录时显示「请先登录」和 `/v2/` 登录链接。

## 2. 商家租户

新增：

```text
c_merchant_member(account_id, merchant_id, role, created_at)
```

解析顺序：

```text
账号已绑定商家 → 使用绑定商家
系统管理员首次访问 → 自动绑定默认演示商家 m_gear_002
普通账号未绑定 → 403
```

真实 API：

```text
GET /api/b/workbench/me
→ account: admin / id=1
→ merchant: m_gear_002 / 山野户外旗舰店 / owner
→ counts: products=10 / orders=8
→ backend: postgres
```

所有 B 接口只访问该 merchant_id 的订单/商品/售后，不能跨租户。

## 3. B API

```text
GET   /api/b/workbench/me
GET   /api/b/workbench/products
GET   /api/b/workbench/orders
PATCH /api/b/workbench/orders/{order_id}/status
GET   /api/b/workbench/after-sales
PATCH /api/b/workbench/after-sales/{ticket_id}
POST  /api/b/workbench/after-sales/{ticket_id}/receive
```

## 4. 真实浏览器操作

打开 `/v2/b.html`：

```text
顶部：山野户外旗舰店 / m_gear_002
视图：订单 / 售后 / 商品
```

订单列表真实数据：

```text
order_5695476eb1c8441e 待支付 ¥89.00
→ 点击「标记已支付」
→ 已支付

→ 点击「发货」
→ 填写 SF-B-0001 / 顺丰速运
→ 确认发货
→ 已发货，物流：顺丰速运 · SF-B-0001
```

页面同步显示所有订单的买家、金额、商品、物流与状态操作。

## 5. 售后与商品

售后按当前商家订单过滤：

```text
OPEN + REFUND_ONLY       通过 / 拒绝
OPEN + RETURN_REFUND     同意退货 / 拒绝
RETURN_PENDING           等待买家寄回
RETURN_SHIPPED           验收通过 / 拒收
```

商品只读，展示标题/ID/SKU 价格/库存/分类。

## 6. 测试与构建

```bash
pytest tests/ -q
# 587 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 4.70s
# dist/b.html 已生成
```

新增：

```text
tests/test_b_workbench_api.py   5 passed
```

覆盖：

```text
系统管理员自动绑定默认商家
普通账号未绑定 → 403
订单按商家作用域过滤
订单状态更新租户校验
售后列表租户过滤
```

## 7. 已知限制

```text
演示环境自动把系统管理员绑定到 m_gear_002
还没有商家注册/绑定管理 UI
商家账号体系仍复用登录账号；未独立登录页
C 端订单/售后库仍是 SQLite，商家商品/订单在 PostgreSQL
售后操作复用管理员售后逻辑，没有商家级审核人记录
B 页面是独立入口，不在 SPA 导航内
```
