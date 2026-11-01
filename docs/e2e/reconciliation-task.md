# 对账任务 E2E

> 日期：2026-10-31 · 状态：通过（手动对账 + 定时 worker + 运营台）

## 1. 数据留痕

新增 `c_reconciliation_run`：

```text
run_id / trigger / started_at / finished_at
ok / checked / legacy / issue_count / issues_json
```

对账只检测、不自动修改订单。

## 2. 接口

```text
GET  /api/c/admin/reconciliation?limit=200
POST /api/c/admin/reconciliation/run?limit=200
GET  /api/c/admin/reconciliation/runs?limit=20
```

实测：

```text
run rec_e1baeccb4e414f93 / MANUAL
ok=True / checked=9 / legacy=6 / issue_count=0
POST 后 runs 从 1 条变为 2 条
```

## 3. 运营台

入口：

```text
http://127.0.0.1:8000/v2/#/admin/c-end
→ 对账
```

页面展示：

```text
已核对 9
旧平台订单 6
问题数 0
状态 正常
当前问题：未发现问题
对账历史：MANUAL / SCHEDULED
```

点击「立即对账」：

```text
最近一次运行：2026-10-31 14:17:02 · MANUAL
对账完成：检查 9 单，未发现问题
历史新增一条 MANUAL
```

## 4. 定时 worker

```bash
python scripts/reconciliation_scheduler.py --interval 1800
# 或 Windows 任务计划程序调用：
python scripts/reconciliation_scheduler.py --once
```

实测 15 秒间隔运行约 50 秒：

```text
rec_8d7e15251c484e18 SCHEDULED 14:17:58 ok=True
rec_02cf987829834a44 SCHEDULED 14:17:43 ok=True
rec_d602518545bd4ca0 SCHEDULED 14:17:28 ok=True
rec_aba175304153478a SCHEDULED 14:17:13 ok=True
共 7 条 run（4 条 SCHEDULED + 手动）
```

日志：

```text
logs/reconciliation_scheduler.log
```

## 5. 问题检测

```text
MERCHANT_ORDER_MISSING  商家订单缺失
STATUS_DIVERGENCE       C 端/商家状态不一致
AMOUNT_DIVERGENCE       C 端/商家金额不一致
legacy                  无 merchant_order_id 的旧平台订单，单独计数
```

单测构造「只取消商家侧」后，对账返回 `ok=False`，`STATUS_DIVERGENCE` 正确落库。

## 6. 对账告警

新增 `c_reconciliation_alert`，按 `(order_id, issue)` 去重：

```text
alert_id / run_id / order_id / issue / severity
message / suggestion / created_at / last_seen_at
read_at / resolved_at
```

接口：

```text
GET  /api/c/admin/reconciliation/alerts?unread_only=&limit=50
POST /api/c/admin/reconciliation/alerts/read
```

真实流程：

```text
C 订单 CONFIRMED，商家订单被取消为 CANCELLED
→ 对账 run：issue_count=1，alert_count=1
→ 未读告警：STATUS_DIVERGENCE / WARNING
→ 建议：人工确认以哪一侧为准；取消/退款必须走受控接口
→ 点击「全部标记已读」
→ 未读 0、按钮置灰
```

告警不会自动修改订单；下一次对账发现该问题消失后，自动标记 `resolved_at`。

## 7. 外部 Webhook

配置：

```bash
QIANKE_ALERT_WEBHOOK_URL=https://example.com/hook
QIANKE_ALERT_WEBHOOK_TOKEN=optional-bearer-token
QIANKE_ALERT_WEBHOOK_TIMEOUT_SECONDS=3
QIANKE_ALERT_WEBHOOK_FORMAT=generic   # generic | wecom | dingtalk
```

行为：

```text
对账产生未解决告警 → POST JSON 到 URL
Authorization: Bearer <token>（配置 token 时）
推送失败只写日志，不影响对账/告警落库
URL 未配置时不发请求
只允许 http/https；URL/Token/格式只从环境变量读取
```

格式：

```text
generic    原始 JSON（默认，适合自建/n8n/webhook.site）
wecom      企业微信群机器人 markdown
dingtalk   钉钉群机器人 markdown
```

企业微信 payload：

```json
{"msgtype":"markdown","markdown":{"content":"### 千客对账告警\n> run ..."}}
```

钉钉 payload：

```json
{"msgtype":"markdown","markdown":{"title":"千客对账告警","text":"### 千客对账告警..."}}
```

payload：

```json
{
  "event": "reconciliation.alert",
  "run_id": "rec_...",
  "trigger": "SCHEDULED",
  "issue_count": 1,
  "alerts": [{
    "order_id": "order_...",
    "issue": "STATUS_DIVERGENCE",
    "severity": "WARNING",
    "message": "状态不一致...",
    "suggestion": "人工确认以哪一侧为准..."
  }]
}
```

真实接收端实测：

```text
webhook {'sent': True, 'status': 200, 'alert_count': 1}
auth Bearer test-token
event reconciliation.alert
alerts 1
```

## 8. 测试与构建

```bash
pytest tests/ -q
# 582 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 5.14s
```

新增：

```text
tests/test_c_end_reconciliation_runs.py   5 passed
tests/test_c_end_alerts_webhook.py        7 passed
```

## 9. 已知限制

```text
只检测 + 告警 + 修复建议，不自动修复订单
一次最多 200 单，无全量分页扫描
旧平台订单只计 legacy，无法核对
单商家 m_gear_002；多商家需扩展
worker 是独立脚本，不在 API 进程内常驻
Webhook 只支持单 URL，不做重试队列/签名校验
企业微信/钉钉使用 markdown 消息，不支持交互卡片
```
