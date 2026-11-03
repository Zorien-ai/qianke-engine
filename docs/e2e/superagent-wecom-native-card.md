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

## 5. 真实发送阻塞

真实尝试：

```text
errcode: 60020
error: not allow to access from your ip
from ip: 113.116.59.199
```

当前企业微信应用可信 IP 仍是旧出口 IP（113.116.58.161），出网 IP 已变化。

需要：

```text
1. 把当前出口 IP 加入企业微信应用可信 IP
2. 或使用固定出口 IP
3. 再验证原生卡片发送
4. 再验证 template_card_event 是否真的推送到应用回调
```

即使发送成功，应用消息通道是否支持按钮事件回调仍取决于企业微信账号/应用类型；
当前签名链接审批卡片已真实可用。

## 6. 已知限制

```text
默认关闭，避免影响现有文本命令/链接卡片
真实原生按钮点击未验证
应用消息通道可能不推送 template_card_event
复杂参数（金额/运单号）仍走签名审批页
可信 IP 变化会导致所有应用主动消息失败
```
