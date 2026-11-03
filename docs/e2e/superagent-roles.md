# 角色细粒度权限

> 日期：2026-11-03 · 状态：B 工作台与 Super-agent 写操作按角色收口

## 1. 角色矩阵

| 权限 | owner | admin | staff |
|---|---|---|---|
| 查看订单/商品/售后 | ✅ | ✅ | ✅ |
| 查看 Super-agent | ✅ | ✅ | ✅ |
| 订单状态操作 | ✅ | ✅ | ❌ |
| 售后通过/驳回 | ✅ | ✅ | ❌ |
| 退货验收入库 | ✅ | ✅ | ❌ |
| Super-agent 启动/停止/审批 | ✅ | ✅ | ❌ |
| 管理租户成员 | ✅ | ❌ | ❌ |

## 2. 后端收口

B 工作台 API：

```text
PATCH /api/b/workbench/orders/{id}/status   → operate_orders
PATCH /api/b/workbench/after-sales/{id}     → resolve_after_sale
POST  /api/b/workbench/after-sales/{id}/receive → receive_return
```

Super-agent：

```text
POST /api/superagent/work-items/{id}/run     → owner/admin
POST /api/superagent/work-items/{id}/stop    → owner/admin
POST /api/superagent/work-items/{id}/approve → owner/admin
```

租户成员管理：

```text
系统管理员 或 该租户 owner
```

staff 越权返回：

```text
403 当前角色 staff 没有 xxx 权限
```

## 3. 前端收口

B 工作台 `/api/b/workbench/me` 返回：

```json
{
  "merchant": {"merchant_id": "...", "role": "staff"},
  "permissions": ["view_orders", "view_products", "view_after_sales", "view_superagent"]
}
```

页面按权限禁用：

```text
订单操作按钮
售后通过/拒绝/验收按钮
Super-agent 停止/审批按钮
```

后端仍是最终校验点，前端禁用只是体验优化。

## 4. 测试

```bash
pytest tests/test_b_workbench_api.py -q
# 7 passed
```

新增覆盖：

```text
staff 能查看订单，不能改订单状态
staff 不能审批售后
owner/admin/staff 权限集合
```

完整套件：

```text
633 passed, 5 skipped, 1 warning
```

## 5. 已知限制

```text
企业微信审批人仍按 from_user，不映射到账号角色
租户管理页面仍只给系统管理员
没有角色变更审计
没有权限继承/自定义角色
```
