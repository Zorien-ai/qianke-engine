# Agent 协作审批台 + 正文 TTL

日期：2026-11-15  
入口：`/v2/#/admin/agent-comm`  
权限：系统管理员

## 1. 数据链路

```text
Agent MCP
  comm_propose_task(required_capabilities, risk)
    ↓
固定能力配置匹配
    ↓
low risk + auto_accept → ASSIGNED
high risk / 超出 max_risk → WAITING_APPROVAL
    ↓
人类审批台
  approve → task=ASSIGNED，补发 task 消息给目标 Agent
  reject  → task=REJECTED，通知发起 Agent
```

## 2. 页面

审批列表：

```text
待审批 / 已同意 / 已驳回 / 全部
任务标题、说明、风险、发起方、目标、所需能力
审批备注
同意并放行 / 驳回
```

最近消息：

```text
sender → recipient / room
kind
正文预览
created_at / expires_at
清理过期正文按钮
```

## 3. 正文 TTL

```text
默认 30 天
AGENT_COMM_MESSAGE_TTL_DAYS 可覆盖
过期正文删除前写 message_audit + content_hash
长期保留元数据，不保留正文
每次 Bus 读写 / 控制台访问 / 进程启动都会顺手清理
```

## 4. 实测

```text
创建 pending approval：task_3810ace9eb
人类同一审批：approved → 已同意 1，待审批 0
消息：human:admin → b_end
再创建 pending approval：task_286836a3a0
页面显示 1 待审批
TTL 显示 30 天
清理接口返回 purged=0
```

截图：

![审批台](docs/design/agent-comm-human-approval.png)

![消息与 TTL](docs/design/agent-comm-human-messages.png)

![移动端](docs/design/agent-comm-human-approval-mobile.png)

## 5. 验证

```text
pytest tests/test_mcp_agent_comm.py
  → 10 passed
pytest tests/test_admin_agent_monitor_api.py
  → 16 passed
```

完整回归：

```text
pytest tests/ -q
  → 856 passed, 6 skipped
```
