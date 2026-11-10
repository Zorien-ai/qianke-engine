# 库存告警外部渠道配置流程

> 状态：**待接入发送器**。当前 `c_inventory_alert` 只写入 `PENDING` 站内队列，
> 还不会自动调用企业微信/邮件。下面是渠道准备与配置流程；配置完成后需要接
> `dispatch` 才会真正发送。

## 0. 先选渠道

| 渠道 | 适合场景 | 需要准备 | 复杂度 |
|---|---|---|---|
| 企业微信群机器人 | 先跑通、群内通知 | 群机器人 Webhook URL | 最低 |
| 企业微信应用消息 | 要按人/部门定向、已有企业应用 | corpid、secret、agentid、可信 IP | 中 |
| 邮件 SMTP | 没有企业微信、需要留档 | SMTP host/port、账号、授权码、收件人 | 中 |

第一版建议 **企业微信群机器人**：不依赖公司主体、不需要 corpid/secret，群主在群里就能创建。

当前项目已有对账告警的通用 Webhook 基座（`c_end/alerts.py`，环境变量
`QIANKE_ALERT_WEBHOOK_URL` / `TOKEN` / `FORMAT` / `TIMEOUT`），库存告警会复用
同一套发送函数，但使用独立的环境变量，避免和财务对账告警混在一个群。

建议新增：

```text
QIANKE_INVENTORY_ALERT_WEBHOOK_URL
QIANKE_INVENTORY_ALERT_WEBHOOK_TOKEN       # 仅 generic 接收端需要；企业微信机器人不需要
QIANKE_INVENTORY_ALERT_WEBHOOK_FORMAT      # wecom / dingtalk / generic
QIANKE_INVENTORY_ALERT_WEBHOOK_TIMEOUT_SECONDS
```

## 1. 企业微信群机器人

### 1.1 创建机器人

1. 打开企业微信，进入目标群（建议单独建「千客库存告警」群）。
2. 群右上角 `...` → **群机器人** → **添加机器人**。
3. 名称填 `千客库存告警`，确认。
4. 复制 Webhook URL，形如：

```text
https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-xxxx
```

这个 URL 就是密钥，**不要提交到 Git、不要发到聊天、不要贴到前端**。

### 1.2 写入环境变量

在服务器/本机 `.env` 或启动脚本中新增（不要写进代码）：

```dotenv
QIANKE_INVENTORY_ALERT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
QIANKE_INVENTORY_ALERT_WEBHOOK_FORMAT=wecom
QIANKE_INVENTORY_ALERT_WEBHOOK_TIMEOUT_SECONDS=5
```

说明：

- `FORMAT=wecom` 时发送 markdown 消息，企业微信群机器人可直接渲染。
- 企业微信群机器人**不需要** `TOKEN`；`TOKEN` 只给自建 generic 接收端做 Bearer 校验。
- 不要把 Webhook URL 写进 `web/`、前端 bundle、Dockerfile 或仓库。

### 1.3 先做通道自测

不经过系统，直接测机器人是否可达：

```powershell
$url = $env:QIANKE_INVENTORY_ALERT_WEBHOOK_URL
$body = '{"msgtype":"text","text":{"content":"千客库存告警通道测试"}}'
Invoke-RestMethod -Method Post -Uri $url -ContentType 'application/json; charset=utf-8' -Body $body
```

企业微信正常返回：

```json
{"errcode":0,"errmsg":"ok"}
```

若返回 `errcode` 非 0：

```text
93000  webhook key 无效
45009  接口调用超过限制
40001  secret 不对（应用消息才会遇到）
```

### 1.4 重启 API 并验证配置被读取

```powershell
# 停掉当前 8000 进程后，用带环境变量的进程启动
$env:QIANKE_INVENTORY_ALERT_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
$env:QIANKE_INVENTORY_ALERT_WEBHOOK_FORMAT="wecom"
.\.venv\Scripts\python.exe -m uvicorn rag_demo.api.main:app --host 127.0.0.1 --port 8000
```

验证：

```powershell
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/ready).StatusCode
```

应返回 `200`。然后由系统侧触发一次库存扫描 + 推送（发送器接入后），群内应收到：

```text
### 千客库存告警
> m_gear_002 / 1 个低库存 SKU
- P-GEAR-002 / 专业版：可售 0，安全库存 5，建议补货 5 件
```

## 2. 邮件 SMTP（备选）

### 2.1 准备

- SMTP 服务器、端口、加密方式（465 SSL / 587 STARTTLS）。
- 发件账号与**授权码**（不是登录密码）。
- 收件人列表（建议单独告警邮箱组）。

### 2.2 环境变量（发送器接入时新增）

```dotenv
QIANKE_INVENTORY_ALERT_SMTP_HOST=smtp.example.com
QIANKE_INVENTORY_ALERT_SMTP_PORT=465
QIANKE_INVENTORY_ALERT_SMTP_USER=alert@example.com
QIANKE_INVENTORY_ALERT_SMTP_PASSWORD=授权码
QIANKE_INVENTORY_ALERT_SMTP_FROM=alert@example.com
QIANKE_INVENTORY_ALERT_SMTP_TO=ops@example.com,owner@example.com
QIANKE_INVENTORY_ALERT_SMTP_SSL=1
```

注意：

- 授权码同样是密钥，不要进 Git。
- 邮件发送需要额外实现 SMTP sender；当前代码还没有这部分。
- 企业邮箱通常要求发件人地址与登录账号一致，否则会被拒。

## 2.5 企业微信应用消息（当前选用）

适合已有企业微信应用、希望按人/部门发送的场景。与群机器人不同，这里用的是
应用自身的 `corpsecret` 和 `agentid`，不是群 Webhook。

### 前提

```text
QIANKE_WECOM_CORP_ID
QIANKE_WECOM_CORP_SECRET
QIANKE_WECOM_AGENT_ID
```

当前服务器已配置这三项。

### 接收人

新增：

```dotenv
QIANKE_INVENTORY_ALERT_WECOM_TOUSER=zhangsan
# 多个：zhangsan|lisi
# 全员：@all（必须显式写，系统不会默认群发）
# 可选 AgentId 覆盖：QIANKE_INVENTORY_ALERT_WECOM_AGENT_ID=1000002
```

接收人从企业微信通讯录成员详情里的 **UserID** 获取，不是手机号/姓名。

### 配置步骤

1. 编辑 `.env`，填 `QIANKE_INVENTORY_ALERT_WECOM_TOUSER`。
2. 重启 API。
3. B 工作台 → 商品 → 扫描低库存 → 推送告警。
4. 企业微信应用应收到文本消息。

### 发送接口

```text
POST /api/b/workbench/inventory/alerts/dispatch
```

返回示例：

```json
{"sent": true, "dispatched": 1, "remaining": 0, "channel": "wecom_app"}
```

未配置接收人：

```json
{"sent": false, "reason": "NO_RECIPIENT", "dispatched": 0}
```

失败不会把队列标成已发送，仍保留 PENDING。

### 常见错误

```text
NO_RECIPIENT       未配置 QIANKE_INVENTORY_ALERT_WECOM_TOUSER
NOT_CONFIGURED     CorpSecret/AgentId 缺失
WECOM_ERROR 60020  服务器 IP 不在应用可信 IP 列表
WECOM_ERROR 81013  touser 不可用，且没有配置部门兜底
```

### 安全

- 接收人显式配置，代码不默认 `@all`。
- 发送失败保留队列，不伪造成功。
- 消息内容不包含客户隐私，只包含商品/SKU/库存/建议补货数量。
- 应用 Secret/AgentId 继续只放 `.env`。

## 3. 配置完成后的系统流程

```text
定时脚本 / 页面“扫描低库存”
→ c_inventory_alert 写入 PENDING
→ dispatch 读取 PENDING
→ 调用企业微信群机器人 / SMTP
→ 成功：标记 SENT，记录发送时间
→ 失败：保持 PENDING，记录错误，下一轮重试
→ 人工可“标记已处理”，库存恢复后自动 RESOLVED
```

在发送器实现前，页面会明确显示：

```text
未配置企业微信/邮件渠道，先进入站内待发送队列。
```

不会伪装成“已发送”。

## 4. 安全清单

- [ ] Webhook URL / SMTP 授权码只放在 `.env` 或密钥管理系统。
- [ ] `.env` 已在 `.gitignore`，没有提交记录。
- [ ] 没有把 URL 注入前端接口返回值。
- [ ] 机器人只加进告警群，不加入业务群。
- [ ] 泄露后立即在群机器人设置里移除/重建，旧 URL 立即失效。
- [ ] 生产环境用独立告警群，不和财务对账告警混用。

## 5. 你需要提供什么

选择企业微信群机器人时，只需要：

1. 群机器人 Webhook URL（写入 `.env`，不要发聊天）。
2. 告警群名称（仅用于文档）。
3. 确认是否现在就接发送器。

选择邮件时，需要：

1. SMTP host / port / SSL。
2. 发件账号 + 授权码（写入 `.env`）。
3. 收件人列表。

配置完成后，下一步是实现 `dispatch` 发送器与发送记录，再做一次真实群消息验证。
