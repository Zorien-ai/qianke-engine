# 租户管理页面

> 日期：2026-11-03 · 状态：管理 API + `/v2/tenants.html` 浏览器验证通过

## 1. 数据模型

```sql
CREATE TABLE c_merchant_tenant (
  merchant_id TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at  TEXT NOT NULL
);
```

种子租户：

```text
m_gear_002  山野户外旗舰店
m_tea_001   山雾茶业
```

成员仍使用：

```text
c_merchant_member(account_id PRIMARY KEY, merchant_id, role, created_at)
```

一个账号只能绑定一个商家；角色：`owner / admin / staff`。

## 2. 管理 API

仅系统管理员：

```text
GET    /api/admin/tenants
POST   /api/admin/tenants
GET    /api/admin/tenants/accounts?q=
POST   /api/admin/tenants/{merchant_id}/members
DELETE /api/admin/tenants/{merchant_id}/members/{account_id}
```

租户返回：

```text
merchant_id / name / status / created_at
members[]
counts { orders, products, work_items, open_work_items }
backend_error
```

## 3. 页面

```text
http://127.0.0.1:8000/v2/tenants.html
```

功能：

```text
租户总数 / 成员数 / 订单数 / 待处理工作项
租户卡片：名称、ID、订单/商品/工作项/待处理
成员列表与解绑
按账号 ID 绑定成员
新建租户
账号搜索
```

未登录访问显示管理员登录表单；非系统管理员显示 403。

## 4. 浏览器验证

Playwright：

```text
navigate /v2/tenants.html
page title 千客 · 租户管理
2 个租户
m_gear_002 山野户外旗舰店：订单 34 / 商品 10 / 工作项 165 / 待处理 147
m_tea_001 山雾茶业：订单 3 / 商品 8 / 工作项 1 / 待处理 1
账号查询 admin → #1 admin / 系统管理员 / active
console errors: 0
```

截图：

```text
.mcp/playwright-output/tenants-admin.png
```

API 冒烟：

```text
GET /health 200
POST /auth/login 200
GET /api/admin/tenants 200
GET /api/admin/tenants/accounts?q=admin 200
```

## 5. 测试

```bash
pytest tests/test_tenants_admin.py -q
# 1 passed
```

覆盖：

```text
种子租户
创建租户
绑定/解绑成员
账号唯一商家约束
```

完整套件：

```text
629 passed, 5 skipped, 1 warning
```

## 6. 已知限制

```text
没有删除租户接口（避免误删）
角色只存储，尚未接入细粒度权限
一个账号只能绑定一个商家
页面没有账号创建/禁用
租户订单数走 merchant repository 全量计数，数据量大时需要改聚合接口
```
