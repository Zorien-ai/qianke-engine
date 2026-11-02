# 企业微信卡片审批

> 日期：2026-11-02 · 状态：真实卡片发送 + 固定域名审批页 + 执行 E2E 通过

## 1. 方案

企业微信应用消息的模板卡片按钮回调在应用回调中不可靠，因此采用：

```text
模板卡片（text_notice）
→ 点击卡片
→ 固定域名签名审批页
→ 选择仅退款/退货退款/同意/驳回
→ ACTION Job
→ 企业微信结果回写
```

文本命令仍保留为回退：

```text
同意 6946da 仅退款
驳回 6946da
```

## 2. 配置

```bash
QIANKE_APPROVAL_CARD_SECRET=<随机长字符串>
QIANKE_PUBLIC_BASE_URL=https://qianke.qiankeagent.com
```

`QIANKE_APPROVAL_CARD_SECRET` 只用于审批链接 HMAC 签名，不进入 Git。

## 3. 签名链接

```text
GET /api/superagent/approval-card/{work_item_id}?token=...
```

Token：

```text
base64(payload).HMAC-SHA256
payload: {"w": work_item_id, "e": expires}
有效期：24h
```

校验：

```text
work_item 匹配
未过期
HMAC 恒定时间比较
```

页面无需登录，权限来自签名链接；WorkItem 状态变化后重复提交会被拒绝。

## 4. 卡片内容

```text
main_title: 待审批：创建售后
sub_title_text: 调查摘要 + 文本命令回退
horizontal_content_list: 短码 / 动作 / 订单
card_action: 审批页 URL
```

真实发送：

```text
wecom_send.notify_work_item(item, stage="INVESTIGATED")
→ msgtype=template_card
→ msgid=D2PfORmTcZSAQn8H7KP_zGpIi1T4...
→ card=true
```

卡片发送失败自动回退文本消息，不影响审批流程。

## 5. 审批页

```text
仅退款
退货退款
同意执行
确认发货 + 运单号
驳回
```

提交：

```text
POST /api/superagent/approval-card/{work_item_id}
form: token, decision, tracking_no, carrier
```

成功后：

```text
工作项 EXECUTING
→ ACTION Job
→ 企业微信结果回写
```

## 6. 真实 E2E

```text
work_item: saw_d474b58b2b4d46e6
order:     order_8618e8338fa9457a
card:      sent=true / card=true
page:      HTTP 200
submit:    HTTP 200
final:     DONE / EXECUTED
ticket:    as_5210824d13a2435e / REFUND_ONLY / OPEN
```

## 7. 测试

```bash
pytest tests/test_superagent_approval_card.py -q
# 2 passed
```

覆盖：

```text
token 校验/篡改
审批页渲染
卡片 payload
卡片通过后进入 EXECUTING 与动作参数
```

完整套件：

```text
619 passed, 5 skipped, 1 warning
```

## 8. 已知限制

```text
卡片按钮是整卡跳转，不是原生按钮回调
审批页无登录，依赖签名 token，链接转发风险由 24h 有效期和状态机控制
没有卡片点击后的「已处理」卡片更新
链接域名必须与 QIANKE_PUBLIC_BASE_URL 一致
文本命令仍是主回退路径
```
