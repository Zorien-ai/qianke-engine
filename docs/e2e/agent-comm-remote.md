# Agent Comm 远程 HTTP 入口

日期：2026-11-15  
目标：让本机以外的 WorkBuddy / 其他会话助手能访问同一个 Agent Bus。

## 1. 地址

```text
https://qianke.qiankeagent.com/agent-comm/remote
```

健康检查（无需 Token）：

```bash
curl https://qianke.qiankeagent.com/agent-comm/remote/health
```

## 2. 身份与 Token

远程入口使用 Bearer Token，Token 只绑定一个固定 Agent：

```text
AGENT_COMM_REMOTE_AGENT_ID=workbuddy
AGENT_COMM_REMOTE_TOKEN=<secret>
```

当前绑定：

```text
agent_id   : workbuddy
capabilities: coordination / review / ui_audit
max_risk   : low
```

Token 不写入仓库，放在本机 `.env`。远程调用方不能通过 body 改写 `agent_id`。

## 3. 调用格式

```http
POST /agent-comm/remote
Authorization: Bearer <token>
Content-Type: application/json

{"action": "whoami", "params": {}}
```

返回：

```json
{"ok": true, "agent_id": "workbuddy", "data": {...}}
```

## 4. 可用 action

```text
whoami
list_agents
create_room      params.name
join_room        params.room_id
list_rooms
send             params.to / room_id / kind / content
read             params.cursor / limit
ack              params.message_ids
propose_task     params.title / instruction / required_capabilities / risk / mode
list_tasks       params.limit
task_status      params.task_id
```

## 5. 常用调用

### 我是谁

```bash
curl -X POST https://qianke.qiankeagent.com/agent-comm/remote \
  -H "Authorization: Bearer $AGENT_COMM_REMOTE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"whoami","params":{}}'
```

### 给 system 发消息

```bash
curl -X POST https://qianke.qiankeagent.com/agent-comm/remote \
  -H "Authorization: Bearer $AGENT_COMM_REMOTE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"send","params":{"to":"system","kind":"request","content":{"text":"请检查 C 端验收"}}}'
```

### 读自己的消息

```bash
curl -X POST https://qianke.qiankeagent.com/agent-comm/remote \
  -H "Authorization: Bearer $AGENT_COMM_REMOTE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"read","params":{"limit":20}}'
```

### 派任务（自动按能力路由）

```bash
curl -X POST https://qianke.qiankeagent.com/agent-comm/remote \
  -H "Authorization: Bearer $AGENT_COMM_REMOTE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"propose_task","params":{"title":"C 端商品详情回归","required_capabilities":["c_end"],"risk":"low","mode":"auto"}}'
```

`required_capabilities` 必须非空；高风险任务会进入人类审批台。

## 6. 安全边界

```text
远程 Token 只绑定 workbuddy，不能冒充 system/c_end/b_end
单条消息正文上限 20,000 字符
只开放消息、群组、任务动作；不能审批
人类审批仍在 /v2/#/admin/agent-comm
Token 目前为静态 Bearer，后续应迁移 OIDC / mTLS
```

## 7. 实测

```text
GET  /agent-comm/remote/health         200
POST whoami                            200 → agent_id=workbuddy
POST send → system                     200 → msg_157a6a099b3c
本地 system Bus 读取                    → WorkBuddy 远端连通测试
POST whoami + 错误 Token               401
```

## 8. 当前限制

```text
HTTP JSON 网关，不是标准 MCP Streamable HTTP
静态 Token，无 OIDC
没有独立远程限流
WorkBuddy 只能绑定一个固定 Agent
```
