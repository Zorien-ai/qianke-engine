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
GET /api/superagent/audit/actions?limit=50&offset=0
    &action_type=&execution_status=&q=
GET /api/superagent/audit/actions.csv
GET /api/superagent/audit/policy?limit=50
```

动作接口返回：

```text
items / total / limit / offset
```

筛选：

```text
action_type       精确动作
execution_status  NONE / EXECUTED / FAILED
q                 工作项 / 订单 / 动作 JSON 关键词
```

CSV 导出：

```text
work_item_id, order_id, action_type, work_status,
approval_status, execution_status, result, error, executed_at
```

UTF-8 BOM，Excel 可直接打开。

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
筛选：动作 / 执行状态 / 关键词
分页：上一页 / 下一页 / 总数
导出 CSV
策略变更：操作人、时间、补偿/退款/动作数量变化
```

截图：

```text
.mcp/playwright-output/action-audit-filter.png
```

Playwright 验证：

```text
切换到执行审计
共 83 条，第 1 页
筛选「发放补偿」→ 共 1 条
CSV 下载 200，text/csv
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
筛选/分页/关键词返回 total 与 items
```

完整套件：

```text
645 passed, 5 skipped, 1 warning
```

## 5. 已知限制

```text
没有按时间范围筛选
没有策略变更分页/CSV
审计日志没有防篡改/签名
CSV 最多导出 200 条
```
