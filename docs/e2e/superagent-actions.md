# Super-agent 审批后受控执行 E2E

> 日期：2026-11-02 · 状态：真实 API + 真实 Deep Agents Worker + 真实取消订单

## 1. 闭环

```text
CApp/IM/Webhook Trigger
→ Router
→ Deep Agents Worker（只读调查）
→ propose_action 登记动作建议
→ 人工审批
→ 白名单执行器调用现有 C/商家受控接口
→ 执行结果写回 WorkItem/Approval
```

模型不能直接写库；只有人工审批后才执行。

## 2. 白名单动作

```text
CANCEL_ORDER        取消已确认订单（复用 cancel_confirmed_order，含模拟退款/库存恢复）
CREATE_AFTER_SALE   创建仅退款/退货退款售后工单
SHIP_ORDER          商家发货并写物流单号
COMPLETE_ORDER      标记商家订单完成
```

不在白名单内的动作返回 `ACTION_NOT_ALLOWED`，不执行。

真实审批参数 E2E：

```text
订单 order_0e134d83049f4d8a
Worker 建议 CREATE_AFTER_SALE / sale_type=RETURN_REFUND
人工审批时改选 REFUND_ONLY
→ 执行成功
→ 工单 as_d252217b487f4a37 / REFUND_ONLY / OPEN
```

人工参数会覆盖模型建议，但不会静默执行：仍必须显式提交 `action_params`。

审批前可补充参数：

```json
{
  "approved": true,
  "action_params": {
    "sale_type": "RETURN_REFUND",
    "tracking_no": "SF1234567890",
    "carrier": "顺丰速运"
  }
}
```

规则：

```text
CREATE_AFTER_SALE 必须明确 sale_type=REFUND_ONLY/RETURN_REFUND
SHIP_ORDER 必须明确 tracking_no
CANCEL_ORDER / COMPLETE_ORDER 无额外参数
缺失时审批 400，不执行
```

## 3. 真实 E2E

创建新订单：

```text
order_6165c9addb24431c
C 端状态 CONFIRMED
商家状态 CREATED
```

提交事件：

```text
请取消订单 order_6165c9addb24431c，买家不想要了，帮我处理
```

Deep Agents 输出并登记：

```json
{
  "action_type": "CANCEL_ORDER",
  "order_id": "order_6165c9addb24431c",
  "reason": "买家主动表示不想要了，申请取消。订单当前 CONFIRMED / CREATED，可取消=True..."
}
```

人工审批：

```text
POST /api/superagent/work-items/saw_6e75bc08c6c04472/approve
{"approved": true, "note": "E2E 同意取消"}
```

结果：

```text
HTTP 200
status: DONE
approval.execution_status: EXECUTED
execution_result.executed: true
action_type: CANCEL_ORDER
order_id: order_6165c9addb24431c
```

最终状态：

```text
C 端订单：CANCELLED
商家订单：CANCELLED
```

## 4. 安全边界

```text
只允许白名单动作
动作必须包含合法 order_id
订单必须属于当前商家 m_gear_002
取消走现有 cancel_confirmed_order（含 C/商家/库存一致性）
审批通过后才执行
驳回不执行
重复审批由工作项状态拦截
执行失败写 EXECUTION_FAILED，不伪造成功
```

## 5. 失败路径

```text
订单不存在 / 不属于商家 → ORDER_NOT_FOUND / ORDER_FORBIDDEN
动作缺少 order_id → INVALID_ACTION
发货缺少物流单号 → INVALID_ACTION
订单状态不允许取消 → CStoreError / MerchantError
执行异常 → EXECUTION_FAILED + error
```

## 6. UI

B 工作台 `Super-agent`：

```text
WAITING_APPROVAL
→ 建议动作卡
→ 通过并执行 / 驳回
→ 二次确认动作类型 + 订单号
→ 已执行 / 执行失败
```

真实浏览器已验证已执行工作项展示「已执行 取消订单（订单 order_6165c...）」；待审批项展示建议动作与确认框。

## 7. 测试

```bash
pytest tests/test_superagent.py -q
# 11 passed
```

覆盖：

```text
Worker 生成 CANCEL_ORDER 建议
审批通过执行取消
C/商家订单均变为 CANCELLED
驳回不执行
动作执行失败不误报成功
```

完整套件：

```text
598 passed, 5 skipped, 1 warning
```

## 8. 已知限制

```text
执行器同步执行，接口请求会等待动作完成
没有分布式锁，多实例审批可能有竞争
没有动作回滚/补偿；外部动作失败后靠人工处理
CREATE_AFTER_SALE 只创建工单，不等于退款；sale_type 必须由人工明确（REFUND_ONLY / RETURN_REFUND），缺失时执行器拒绝，不默认仅退款
SHIP_ORDER/COMPLETE_ORDER 只更新商家侧，C 端展示依赖现有聚合
没有二次复核/双人审批
```
