# 动作执行审计页

> 日期：2026-11-03 · 状态：策略变更留痕 + 动作执行审计 + B 工作台页面

## 1. 数据

### 策略变更审计

```sql
c_merchant_policy_audit (
  policy_audit_id,
  merchant_id,
  changed_by,
  before_json,
  after_json,
  changed_at
)
```

只有实际变化才记录；相同配置重复保存不产生审计。

### 动作执行审计

来自：

```text
sa_approval + sa_work_item
```

字段：

```text
work_item_id / action_type / order_id
work_status / approval_status / execution_status
execution_result / error
created_at / decided_at / executed_at
```

## 2. API

```text
GET /api/superagent/audit/actions?limit=100
GET /api/superagent/audit/policy?limit=50
```

权限：

```text
绑定商家成员可读
商家账号只能看自己租户
系统管理员可带 merchant_id
```

## 3. B 工作台

```text
/v2/b.html → 执行审计
```

内容：

```text
动作执行表：工作项、动作、订单、状态、执行结果、时间
策略变更：操作人、时间、补偿/退款/动作数量变化
刷新
```

截图：

```text
.mcp/playwright-output/action-audit.png
```

Playwright 验证：

```text
切换到执行审计
读取 100 条动作审计
执行结果包含工单 as_1e398d95e5ec4bb6
策略变更出现 50→45 / 45→50 两条
console errors: 0
```

## 4. 测试

```bash
pytest tests/test_merchant_policy.py -q
# 5 passed
```

覆盖：

```text
策略变更写入审计
相同配置不重复审计
动作执行后 list_action_audit 返回 EXECUTED
```

完整套件：

```text
644 passed, 5 skipped, 1 warning
```

## 5. 已知限制

```text
动作审计最多返回 100 条，没有分页
没有按动作/状态/时间筛选
没有 CSV 导出
策略审计只记录变更，不记录查看
没有审计日志防篡改/签名
```
