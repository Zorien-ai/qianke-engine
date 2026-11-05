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
    &date_from=YYYY-MM-DDTHH:MM&date_to=YYYY-MM-DDTHH:MM
GET /api/superagent/audit/actions.csv
    （支持同样的筛选参数，最多 5000 行）
GET /api/superagent/audit/policy?limit=20&offset=0
    &date_from=YYYY-MM-DDTHH:MM&date_to=YYYY-MM-DDTHH:MM
GET /api/superagent/audit/policy.csv
    （支持日期筛选，最多 5000 行）
```

动作与策略接口均返回：

```text
items / total / limit / offset
```

筛选：

```text
action_type       精确动作
execution_status  NONE / EXECUTED / FAILED
q                 工作项 / 订单 / 动作 JSON 关键词
date_from/date_to 分钟级时间范围（含首尾；纯日期自动补全天）
```

CSV 导出：

```text
动作：work_item_id, order_id, action_type, work_status,
      approval_status, execution_status, result, error, executed_at
策略：changed_at, changed_by, 补偿/退款 before-after,
      动作 before-after, require_note before-after,
      prev_hash, entry_hash
```

策略审计哈希链：

```text
GET /api/superagent/audit/policy/verify
python scripts/verify_policy_audit_chain.py --merchant m_gear_002
```

返回：

```json
{"ok": true, "checked": 2, "head_hash": "..."}
```

链式字段：

```text
prev_hash / entry_hash
entry_hash = SHA256(prev_hash | canonical(payload))
```

UTF-8 BOM，Excel 可直接打开；CSV 会带上当前筛选参数。

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
筛选：动作 / 执行状态 / 关键词 / 开始时间 / 结束时间（分钟级）
动作分页：上一页 / 下一页 / 总数
策略变更分页：每页 10 条，上一页 / 下一页 / 总数
导出动作 CSV / 导出策略 CSV（均带当前筛选参数）
策略变更：操作人、时间、补偿/退款/动作数量变化
```

截图：

```text
.mcp/playwright-output/audit-hour-policy-csv.png
```

Playwright 验证：

```text
切换到执行审计
共 93 条动作 / 共 14 条策略（清理前）
开始时间 2099-01-01T00:00 → 动作 0 条、策略 0 条
清空时间 → 恢复
策略变更下一页 → 第 2 页
动作 CSV 200，94 行数据
策略 CSV 200，15 行数据
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

## 5. 开发库测试审计清理

脚本：

```bash
python scripts/cleanup_policy_audit.py --merchant m_gear_002 --changed-by admin
python scripts/cleanup_policy_audit.py --merchant m_gear_002 --changed-by admin --yes
```

默认 dry-run；`--yes` 前先导出：

```text
logs/policy_audit_backup_<timestamp>.json
```

本次清理：

```text
matched = 14
deleted = 14
backup = logs/policy_audit_backup_1793723450.json
清理后 policy total = 0
```

注意：生产环境审计应只追加，不应执行该脚本。

## 6. 已知限制

```text
时间筛选为分钟级，不支持秒
策略变更没有 CSV 删除/归档 UI
审计日志没有防篡改/签名
CSV 最多导出 5000 条
```
