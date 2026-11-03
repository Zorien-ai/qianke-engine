# 企业微信原生按钮卡片

> 日期：2026-11-03 · 状态：代码/回调解析/单测完成；真实发送被企业微信可信 IP 拦截

## 1. 开关

默认关闭：

```bash
QIANKE_WECOM_NATIVE_CARD=0
```

开启后优先发送 `template_card` 的 `button_interaction` 卡片，失败回退现有签名链接卡片。

## 2. 按钮

```text
CREATE_AFTER_SALE:
  仅退款 / 退货退款 / 驳回
其他动作:
  同意执行 / 驳回
ISSUE_COMPENSATION:
  去填写补偿 / 驳回（金额必须人工填写）
```

按钮 key：

```json
{"a":"approve","w":"saw_...","s":"REFUND_ONLY"}
```

## 3. 回调

企业微信事件：

```text
MsgType=event
Event=template_card_event
EventKey=<button key>
```

处理：

```text
EventKey → 校验 work_item + action
→ 转换为既有审批命令
→ wecom_approval.handle_message
→ 权限/参数/ACTION Job 逻辑完全复用
```

映射：

```text
approve + REFUND_ONLY   → 同意 <短码> 仅退款
approve + RETURN_REFUND → 同意 <短码> 退货退款
approve 无参数           → 同意 <短码>
reject                  → 驳回 <短码>
page                    → 消费事件（复杂参数走签名审批页）
```

## 4. 测试

```bash
pytest tests/test_superagent_wecom_native_card.py -q
# 2 passed
```

覆盖：

```text
button_interaction payload
task_id / 三个按钮
EventKey JSON 解析
命令映射
复用 wecom_approval.handle_message
```

完整套件：

```text
635 passed, 5 skipped, 1 warning
```

## 5. 真实发送与回调

企业微信 `touser` 返回：

```text
81013 user & party & tag all invalid
```

`user/list` / `agent/get` 显示用户 `zzzzzzzq` 与部门 `1` 均存在，但直接 touser 不可用。
启用部门兜底：

```bash
QIANKE_WECOM_FALLBACK_PARTY_ID=1
```

结果：

```text
text:  sent=true / channel=party / msgid=...
card:  sent=true / channel=party / msgid=cpB2NxqCi8uaKeFH...
```

原生按钮卡片已真实发送到企业微信。

回调模拟（签名 + 加密 + 固定域名）：

```text
POST /api/superagent/wecom/callback
EventKey={"a":"approve","w":"saw_71b0b513f35b410a","s":"REFUND_ONLY"}
→ 200 success
→ item 进入 EXECUTION_FAILED
```

失败是因为测试订单 `order_native_button_test` 不存在，属于预期业务失败；
说明事件解析、命令映射、审批、ACTION Job、回调验签链路都已打通。

## 5.1 真实点击事件已到达

企业微信真实回调日志出现多次按钮事件：

```text
10:35:04  113.108.92.100   POST /api/superagent/wecom/callback 200
10:35:00  14.116.241.251   POST /api/superagent/wecom/callback 200
10:47:52  183.47.98.227    POST /api/superagent/wecom/callback 200
```

说明应用消息通道确实会推送 `template_card_event`。

当时的卡片对应已处理工作项，重复点击返回：

```text
没有找到待审批的工作项
```

已优化：点击已处理工作项现在直接回复：

```text
工作项 <短码> 当前状态为 <STATUS>，无需重复审批。
```

## 5.2 成功点击验证

新卡片：

```text
work_item: saw_54fecb19e50a43ca
order:     order_70fd445a945940f3
buttons:   仅退款 / 退货退款 / 驳回
```

卡片已真实发送，等待人工点击「仅退款」后确认成功执行。

`toparty=1` 兜底注意：会发给部门可见成员；当前部门只有 zzzzzzq。

## 5.3 真实点击遇到身份不一致

新卡片点击返回：

```text
你没有权限审批这个工作项。
```

说明按钮事件已到达，但事件里的 `FromUserName` 与该 WorkItem 发起人
`zzzzzzzq` 不一致。已加入事件日志：

```text
原生卡片事件 from=<真实 userid> work_item=... action=...
```

待再次点击后读取真实 userid，再决定：

```text
1. 修正 WorkItem 发起人映射
2. 或配置 QIANKE_WECOM_APPROVERS 授权名单
```

在身份确认前，不会放宽审批人校验。

## 6. 已知限制

```text
默认关闭，避免影响现有文本命令/链接卡片
真实原生按钮点击未验证
应用消息通道可能不推送 template_card_event
复杂参数（金额/运单号）仍走签名审批页
touser 81013 需要 toparty 兜底；部门范围必须可控
```
