# 租户开通流程

> 日期：2026-11-04 · 状态：租户 + owner + 默认动作策略一步开通，浏览器验证通过

## 1. 流程

```text
管理员填写 merchant_id / 租户名称 / owner 账号
→ 校验 owner 存在且 active
→ 校验 owner 没有绑定其他商家
→ 创建/更新租户
→ 绑定 owner
→ 初始化动作策略（允许动作、补偿/退款上限）
→ 写入 c_tenant_provision 开通记录
→ 返回 tenant / owner / policy
```

## 2. API

```text
POST /api/admin/tenants/provision
```

请求：

```json
{
  "merchant_id": "m_pilot_001",
  "name": "试点商家",
  "owner_account_id": 60,
  "compensation_max_amount": 40,
  "refund_max_amount": 300
}
```

也支持 `owner_username`，但优先 `owner_account_id`。

成功：

```json
{
  "provisioned": true,
  "tenant": {...},
  "owner": {"username": "myc6666", "role": "owner"},
  "policy": {"compensation_max_amount": 40, "refund_max_amount": 300}
}
```

错误：

```text
404 owner 账号不存在
409 owner 账号不可用
409 ACCOUNT_ALREADY_BOUND：账号已绑定其他商家
400 策略参数不合法
```

## 3. 数据

新增：

```sql
c_tenant_provision (
  provision_id,
  merchant_id,
  owner_account_id,
  created_by,
  created_at
)
```

租户列表接口返回：

```text
policy
provisions（最近 5 条）
```

## 4. 管理页面

```text
/v2/tenants.html → 开通租户
```

字段：

```text
merchant_id
租户名称
owner 账号 ID
补偿上限
退款上限
```

开通后卡片展示：

```text
租户名称 / merchant_id / ACTIVE
订单 / 商品 / 工作项 / 待处理
动作策略：补偿上限 / 退款上限 / 允许动作数
owner 成员
```

截图：

```text
.mcp/playwright-output/tenant-provision.png
```

## 5. 浏览器验证

Playwright：

```text
开通 m_pilot_001 / 试点商家 / owner 60 / 补偿 40 / 退款 300
页面出现试点商家
owner = aaa / myc6666 / owner
策略 = 补偿 40 / 退款 300 / 8 个动作
重复开通其他租户使用 owner 60 → 409 ACCOUNT_ALREADY_BOUND
console errors: 0（409 请求除外）
```

## 6. 测试

```bash
pytest tests/test_tenants_admin.py -q
# 2 passed
```

完整套件：

```text
650 passed, 5 skipped, 1 warning
```

## 7. 已知限制

```text
没有租户删除/停用流程
没有邀请邮件/短信
没有账号创建（owner 必须是已有账号）
没有租户级企业微信配置表单
没有套餐/配额/计费
开通记录没有独立审计页面
```
