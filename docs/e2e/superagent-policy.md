# 商家级动作策略与额度

> 日期：2026-11-03 · 状态：策略表、执行校验、API、B 工作台配置页已接入

## 1. 数据模型

```sql
c_merchant_policy (
  merchant_id,
  allowed_actions_json,
  compensation_max_amount,
  refund_max_amount,
  require_note,
  updated_by,
  updated_at
)
```

默认策略：

```text
全部 8 个动作
补偿上限 50 元/单
退款上限 1000 元/单
不强制填写原因
```

## 2. 动作

```text
CANCEL_ORDER
CREATE_AFTER_SALE
SHIP_ORDER
COMPLETE_ORDER
REFUND_AFTER_SALE
RECEIVE_RETURN
REJECT_AFTER_SALE
ISSUE_COMPENSATION
```

## 3. 执行前强制校验

```text
人工审批通过 → ACTION Job → _execute()
→ 读取 item.merchant_id 对应策略
→ 动作未开放：ACTION_NOT_ALLOWED_BY_POLICY
→ 补偿超上限：COMPENSATION_EXCEEDS_POLICY
→ 退款超上限：REFUND_EXCEEDS_POLICY
→ 要求原因但为空：NOTE_REQUIRED
```

补偿上限取：

```text
min(环境变量 QIANKE_COMPENSATION_MAX_AMOUNT, 商家策略 compensation_max_amount)
```

审批参数无法绕过策略。

## 4. API

```text
GET /api/superagent/policy
PUT /api/superagent/policy

{
  "allowed_actions": ["..."],
  "compensation_max_amount": 50,
  "refund_max_amount": 1000,
  "require_note": false
}
```

权限：

```text
查看：绑定商家的成员
修改：owner / admin / 系统管理员
```

系统管理员可带 `merchant_id` 查看/修改指定租户；商家账号只能操作自己租户。

## 5. B 工作台配置页

入口：

```text
/v2/b.html → 动作策略
```

功能：

```text
允许动作复选框
补偿上限
退款上限
动作必须填写原因
保存策略
```

截图：

```text
.mcp/playwright-output/merchant-policy.png
```

Playwright 验证：

```text
切换到动作策略
取消勾选「取消订单」
补偿上限改为 30
保存 → API 返回 updated_by=admin
恢复默认配置
console errors: 0
```

## 6. 测试

```text
tests/test_merchant_policy.py
# 4 passed

完整套件
# 643 passed, 5 skipped, 1 warning
```

覆盖：

```text
默认策略
upsert 校验
动作/补偿/退款超限
执行期 ACTION_NOT_ALLOWED_BY_POLICY
执行期 COMPENSATION_EXCEEDS_POLICY
```

## 7. 已知限制

```text
没有策略变更审计表（当前只记录 updated_by/updated_at）
没有按动作类型分别配置退款上限
没有时间窗口/每日额度
没有部门或成员级策略
B 工作台没有历史版本/回滚
```
