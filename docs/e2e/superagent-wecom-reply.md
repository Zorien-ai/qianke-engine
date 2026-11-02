# Super-agent 企业微信结果回写

> 日期：2026-11-02 · 状态：应用直发 + 群机器人兜底均已真实验证

## 1. 能力

```text
企业微信消息
→ Super-agent 调查
→ 工作项进入 WAITING_APPROVAL
→ 主动回写调查结论到发起人

人工审批/执行
→ 回写执行结果（成功/失败/驳回）
```

回写使用企业微信应用 API：

```text
GET  /cgi-bin/gettoken?corpid=&corpsecret=
POST /cgi-bin/message/send?access_token=
```

## 2. 配置

```dotenv
QIANKE_WECOM_CORP_ID=ww...
QIANKE_WECOM_CORP_SECRET=<应用 Secret>
QIANKE_WECOM_AGENT_ID=1000002
```

`QIANKE_WECOM_CORP_SECRET` 在企业微信应用详情页的 Secret 字段获取。

没有配置 Secret 时，回写会被安全跳过，不影响 Super-agent 主流程。

### 群机器人兜底

如果暂时没有应用 Secret，可复用已有企业微信群机器人：

```dotenv
QIANKE_ALERT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
QIANKE_WECOM_REPLY_FALLBACK_GROUP=1
```

兜底会把同一份结果发到群机器人，不是应用直发给发起人。

## 3. 触发时机

```text
Worker 调查完成 → INVESTIGATED
审批通过并执行 → APPROVED
审批驳回 → REJECTED
```

消息只回写给来源为 `wecom` 的 Trigger 的 `from_user`；CApp/Webhook 来源不会误发。

## 4. 真实回写 E2E

真实测试订单：

```text
order_22340294c85d4efd
work_item saw_b2e3702a53bf4086
```

人工审批：

```json
{"approved": true, "action_params": {"sale_type": "REFUND_ONLY"}}
```

执行结果：

```text
status DONE
execution_status EXECUTED
ticket as_2a0d85ace25f4051
type REFUND_ONLY
status OPEN
```

回写日志：

```text
企业微信回写走群机器人兜底 sent=True reason=None
```

说明当前没有应用 Secret 时，执行结果已真实回写到企业微信群机器人。

应用直发真实验证（配置 Secret + 可信 IP 后）：

```text
send_text -> {'sent': True, 'msgid': 'cpB2NxqCi8uaKeFH...'}
真实工作项结果回写 -> {'sent': True, 'msgid': 'cpB2NxqCi8uaKeFH...'}
```

企业微信要求把服务出口 IP 加入应用「企业可信 IP」：

```text
113.116.58.161
```

未加白名单时返回：

```text
errcode 60020: not allow to access from your ip
```

## 5. 内容示例

调查完成：

```text
【千客 Super-agent】
工作项：saw_...
状态：WAITING_APPROVAL
调查已完成，等待人工审批。
<调查结论摘要>
建议动作：CREATE_AFTER_SALE
订单：order_...
```

执行完成：

```text
【千客 Super-agent】
工作项：saw_...
状态：DONE
人工已审批并执行。
执行结果：成功
订单：order_...
```

## 6. 审批参数

`POST /approve` 支持：

```json
{
  "approved": true,
  "note": "",
  "action_params": {
    "sale_type": "REFUND_ONLY",
    "tracking_no": "",
    "carrier": ""
  }
}
```

`CREATE_AFTER_SALE` 的 `sale_type` 必须由人工明确：

```text
REFUND_ONLY    仅退款
RETURN_REFUND  退货退款
```

缺失时审批返回 400，不执行。

## 7. 已知限制

```text
真实企业微信应用直发已验证（send_text + 工作项结果回写均返回 sent=True）
群机器人兜底也已真实验证：sent=True / group_webhook
必须把 API 出口 IP 加入应用「企业可信 IP」
换网络/换出口 IP 后需要重新加白
回写失败只记日志，不影响审批结果
消息为纯文本，截断到 1200 字符
```

## 8. 测试

```bash
pytest tests/test_superagent_wecom_send.py -q
# 4 passed
```

覆盖：

```text
文本消息构造
从 wecom Trigger 提取接收人
未配置 Secret 时安全跳过
群机器人兜底
```
