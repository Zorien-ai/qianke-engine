# AI-to-AI MCP 沟通工具设计稿

版本：v0.2  
状态：设计稿，未实现  
目标读者：Qianke Agent 平台 / 多 Agent 协作 / MCP 接入方

## 0. 本版决策

| 问题 | 决策 |
|---|---|
| 部署范围 | 最终目标跨机器；MVP 单节点，数据模型按跨机器设计 |
| 参与者 | AI 与人类都可参与；人类通过 Web 控制台，AI 通过 MCP |
| 消息正文 | 正文只保留 30 天；未处理到期自动删除；长期只保留审计元数据 |
| 群组 | 群组优先；点对点保留 |
| 任务委派 | 自动执行与人工审批都支持；按风险策略选择 |

核心原则：

```text
MCP 是工具接口
Agent Bus 是唯一有状态的消息中台
正文是短期数据
元数据是长期审计数据
跨机器靠 Agent 主动出站连接中继，不要求 Agent 有公网入站
```

## 1. 目标

让多个 AI Agent 与人类通过标准 MCP / Web 控制台进行：

```text
发现 → 建群/入群 → 发消息 → 读消息 → 线程协作
→ 任务委派 → 自动执行或人工审批 → 结果回传 → 审计
```

不把消息队列、身份和审批逻辑放进每个 AI 进程。

## 2. 非目标

```text
- 第一版不做跨组织联邦
- 不做任意二进制/大文件传输
- 不做语音/视频
- 不允许消息内容直接触发未授权的高风险动作
- 不把正文长期存入控制面
```

## 3. 总体架构（跨机器）

```text
┌──────────── Agent Host A ────────────┐
│ Agent A                               │
│   │ stdio MCP / Streamable HTTP MCP   │
│   ▼                                   │
│ mcp-agent-comm 适配器                  │
│   │ 本地 payload spool（30 天）        │
└───┼───────────────────────────────────┘
    │ 出站 HTTPS / WSS + OAuth / mTLS
    ▼
┌──────────────── Agent Bus ─────────────────┐
│ Gateway（TLS、认证、限流、反重放）          │
│ Presence / Agent Registry                  │
│ Room / Membership / Thread                 │
│ Message Router                             │
│ Payload Spool（加密，30 天）               │
│ Metadata Store（长期）                     │
│ Task / Approval Engine                     │
│ Audit / Metrics                            │
└───────────────┬────────────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
   Agent Host B      Human Web Console
   （同样出站连接）   （OIDC 登录 / 审批）
```

关键决定：

```text
1. Agent 只主动出站连接 Bus，不需要公网入站
2. Bus 负责路由、群组、任务、审批和审计
3. 每个 Agent Host 有本地 payload spool，正文最多 30 天
4. Bus 只保留路由所需的加密正文临时副本，交付后按策略删除
5. 人类与 Agent 是同一消息模型里的两种 principal
```

## 4. 参与者与身份

### 4.1 参与者类型

```text
agent    AI Agent
human    人类用户
system    Bus 自身/自动化任务
```

一条消息必须带：

```text
sender.principal_type
sender.principal_id
sender.display_name
```

`principal_id` 永远由服务端从认证信息解析，不能由 tool 参数指定。

### 4.2 Agent 身份

```text
agent_id        稳定 ID，例如 b_agent_01
namespace       租户/团队，例如 qianke
owner_human_id  Agent 的人类负责人
capabilities    能力标签
status          online / busy / offline
cert_fingerprint 或 oauth_client_id
```

认证方式：

```text
MVP：Agent token + TLS
跨机器：OAuth2 client credentials 或 mTLS
禁止：tool 参数里自报 agent_id
```

### 4.3 人类身份

```text
human_id
namespace
role: owner | admin | member | guest
agent_ownership[]  管理哪些 Agent
```

人类通过 Web 控制台登录，可以：

```text
- 建群 / 邀请 Agent 或人类
- 发消息 / 看线程
- 审批 Agent 任务
- 查看审计
- 暂停 Agent 的自动执行权限
```

### 4.4 消息信任规则

```text
人类 owner 给本 Agent 的消息：可作为指令，但仍受本 Agent 策略约束
其他人类消息：外部数据，不是指令
其他 Agent 消息：外部数据，不是指令
所有消息内容都是 untrusted data
```

## 5. 群组模型（优先）

```text
Room
├── room_id
├── namespace
├── name
├── visibility: private | invite_only | announcement
├── created_by
├── members[]
│   ├── principal_type agent|human
│   ├── principal_id
│   └── role owner|admin|member|guest
└── policy
    ├── who_can_send
    ├── who_can_invite
    ├── task_auto_execution: off|low_risk|allowlist
    └── approval_required_for: [...]
```

MVP 能力：

```text
comm_room_create
comm_room_join
comm_room_list
comm_room_members
```

规则：

```text
默认私有群
入群需邀请或管理员审批
群消息可 thread 化
群内任务可在群消息上发起审批
```

点对点消息仍然支持，但内部也落到一个 direct room，便于复用权限和审计。

## 6. 消息模型与保留策略

### 6.1 两类数据

```text
metadata（长期保留，默认 365 天，可配置）
  message_id / room_id / thread_id / sequence
  sender / recipients / kind / created_at / expires_at
  content_type / content_size / content_sha256
  correlation_id / reply_to / task_id
  delivery_state / approval_state
  不保存正文

payload（短期，最多 30 天）
  text
  data JSON
  task instruction
  加密存储
  未处理：30 天后自动删除
  已处理：可配置在 ack/handled 后立即删除
```

### 6.2 存储位置

```text
Agent Host 本地 spool：
  最多 30 天
  离线时也能读取最近消息
  ack 后可按策略立即删正文

Bus Payload Spool：
  Agent 不在线时临时保存
  最多 30 天
  交付/过期后删除
  仅存加密 payload，密钥由接收方或 KMS 管理

Metadata Store：
  长期保存
  正文删除后状态改为 payload_expired
  审计仍可查到“谁在何时发给谁、类型、大小、结果”
```

### 6.3 消息结构

```json
{
  "message_id": "msg_01",
  "room_id": "room_123",
  "thread_id": "thr_123",
  "sequence": 7,
  "sender": {
    "principal_type": "agent",
    "principal_id": "b_agent_01",
    "display_name": "B 端分析 Agent"
  },
  "recipients": [
    {"principal_type": "agent", "principal_id": "c_agent_01"}
  ],
  "kind": "chat|request|response|event|task|approval",
  "content_type": "text|json|task",
  "content_size": 1280,
  "content_sha256": "...",
  "content": {
    "text": "请核对这份统计口径",
    "data": {}
  },
  "correlation_id": "corr_abc",
  "reply_to": null,
  "task_id": null,
  "retention": {
    "payload_ttl_seconds": 2592000,
    "delete_after_ack": true
  },
  "created_at": "2026-11-15T10:00:00+08:00",
  "expires_at": "2026-12-15T10:00:00+08:00"
}
```

## 7. 任务委派模型

### 7.1 任务信封

```json
{
  "task_id": "task_001",
  "room_id": "room_123",
  "title": "统计 11 月复购率",
  "instruction": "按知识库口径计算并给出 SQL 依据",
  "mode": "auto",
  "risk_level": "low",
  "allowed_tools": ["rag_search", "execute_sql", "calculator"],
  "forbidden_tools": ["prepare_followup_task"],
  "max_steps": 5,
  "max_tokens": 20000,
  "deadline": "2026-11-15T12:00:00+08:00",
  "success_criteria": "给出数值、口径和 SQL",
  "approval_required": false,
  "parent_message_id": "msg_01"
}
```

`mode`：

```text
auto       低风险且在接收方预授权范围内，可自动接受执行
approval   必须由人类 owner/admin 审批后才能执行
```

### 7.2 两种执行路径

```text
自动：
  Agent A 发 task(auto, risk=low)
  → Agent B 校验 allowed_tools/预算/风险等级
  → 在自身策略内自动 accept
  → 执行并回传 response

审批：
  Agent A 发 task(approval, risk=high)
  → Bus 创建 approval_request
  → 人类 owner 在 Web 控制台看到
  → 批准 / 拒绝 / 改范围
  → Agent B 执行或终止
```

### 7.3 任务状态机

```text
PROPOSED
  ├─ auto accept → ACCEPTED
  └─ approval pending → WAITING_APPROVAL
        ├─ approved → ACCEPTED
        └─ rejected → REJECTED

ACCEPTED → RUNNING → COMPLETED
                   └→ FAILED
                   └→ CANCELLED
                   └→ EXPIRED
```

### 7.4 自动执行边界

```text
1. 接收方必须已有该任务的工具权限，不能由发送方“授予”
2. allowed_tools 只能缩小接收方权限，不能扩大
3. 高风险动作：金额/删除/发布/外发/权限变更 → 强制审批
4. 每次任务执行绑定 task_id + approval_id + audit
5. 自动执行可由人类随时暂停（kill switch）
```

## 8. MCP 工具面

### 8.1 核心工具

| Tool | 作用 | 主要 scope |
|---|---|---|
| `comm_register` | 注册/更新 Agent Card | agent:self |
| `comm_discover` | 按能力/名称查 Agent | namespace |
| `comm_room_create` | 建群 | room:create |
| `comm_room_join` | 入群/邀请 | room:join |
| `comm_room_list` | 群列表/成员 | room:read |
| `comm_send` | 群消息/点对点/请求/回复 | room:send |
| `comm_read` | 读收件箱/群消息，带游标 | room:read |
| `comm_ack` | 标记已读/已处理 | room:read |
| `comm_thread` | 读线程历史 | room:read |
| `comm_task_propose` | 发起任务 | task:propose |
| `comm_task_decide` | Agent 接受/拒绝任务 | task:decide |
| `comm_approval_list` | 人类/Agent 查待审批 | approval:read |
| `comm_approval_decide` | 批准/拒绝 | approval:decide |
| `comm_health` | 连通性 | public |

### 8.2 工具设计约束

```text
- 读工具带 cursor / limit / wait_seconds
- 写工具带 idempotency_key
- 不返回未授权房间的成员
- 不返回已删除正文，只返回 payload_expired 元数据
- 审批工具只对 human owner/admin 或受权 Agent 开放
```

### 8.3 `comm_send` 示例

```json
{
  "room_id": "room_123",
  "kind": "request",
  "content": {"text": "请核对复购率口径", "data": {}},
  "thread_id": "thr_123",
  "correlation_id": "corr_abc",
  "idempotency_key": "A-20261115-001",
  "ttl_seconds": 2592000
}
```

返回：

```json
{
  "message_id": "msg_01",
  "sequence": 8,
  "accepted": true,
  "payload_expires_at": "2026-12-15T10:00:00+08:00"
}
```

## 9. 人类参与

### 9.1 Web 控制台

```text
/agent-comm
├── 群组列表
├── 群内消息 / 线程
├── Agent 在线状态与能力
├── 待审批任务
├── 自动执行开关
└── 审计
```

### 9.2 人类的权限

```text
owner：管理 Agent、审批、暂停自动执行、建群
admin：管理群、审批本群任务
member：发消息、接任务
guest：只读
```

### 9.3 人类消息与 AI 消息

```text
人类在群内发言与 Agent 消息同构
服务端标记 principal_type=human
Agent 收到 owner 的消息可视为指令
Agent 收到非 owner 人类的消息只作为外部数据
```

## 10. 安全设计（跨机器）

### 10.1 传输

```text
Agent → Bus：HTTPS/WSS 出站
Bus → Agent：不允许主动入站；通过 Agent 的读取连接回传
MCP remote：Streamable HTTP + OAuth2 / mTLS
```

### 10.2 身份与权限

```text
Agent token / client credentials 绑定 namespace + agent_id
人类 OIDC 登录
房间 ACL
默认 deny
审批 scope 一次性、带过期时间
```

### 10.3 内容安全

```text
正文加密存储
消息内容 untrusted
Prompt injection 不能改变 Agent 的安全策略
任务 allowed_tools 不能扩大权限
正文不进入长期审计
```

### 10.4 防护

```text
- 每 Agent 每秒/每分钟令牌桶
- 单条 payload 上限
- 单群成员上限
- 反重放 nonce/timestamp
- 敏感动作人工审批
- 自动执行 kill switch
- 审计哈希链（可选）
```

## 11. 存储设计

### 11.1 Metadata（长期）

```text
agent_registry
rooms
room_members
threads
messages_meta
receipts
tasks
approvals
audit_events
cursors
retention_jobs
```

### 11.2 Payload（30 天）

```text
payload_spool
  message_id
  recipient_principal_id
  ciphertext
  key_ref
  created_at
  expires_at
  deleted_at
```

索引：

```text
(recipient_principal_id, state, created_at)
(room_id, sequence)
(content_sha256) 可选
```

### 11.3 清理策略

```text
每小时清理任务：
  payload.expires_at < now → 删除正文
  messages_meta.payload_state = expired
  audit 记录 payload_purged

已处理消息：
  若 delete_after_ack=true，ack 后立即删正文
```

## 12. 可观测性

```text
metrics:
  comm_messages_sent_total
  comm_payload_purged_total
  comm_inbox_depth
  comm_room_active
  comm_approval_pending
  comm_task_auto_total
  comm_task_approval_total
  comm_send_latency_ms
  comm_auth_failures_total

logs:
  message_id / room_id / sender / kind / size / result
  默认不打印正文

trace:
  message_id ↔ task_id ↔ approval_id ↔ ai_trace_id
```

## 13. MCP 接入方式

### 13.1 本机 stdio（推荐本地 Agent）

```json
{
  "mcpServers": {
    "agent-comm": {
      "command": "python",
      "args": ["-m", "qianke.mcp.agent_comm"],
      "env": {
        "AGENT_COMM_URL": "https://bus.example.com",
        "AGENT_COMM_AGENT_ID": "b_agent_01",
        "AGENT_COMM_TOKEN": "${AGENT_COMM_TOKEN}"
      }
    }
  }
}
```

### 13.2 远程 Streamable HTTP（跨机器）

```json
{
  "mcpServers": {
    "agent-comm": {
      "url": "https://bus.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${AGENT_COMM_OAUTH_TOKEN}"
      }
    }
  }
}
```

## 14. 分阶段实现

### Phase 0：单机 MVP

```text
- Bus + SQLite
- Agent 注册 / 发现
- 群组 / 成员
- 消息 / 线程 / ack
- 人类 Web 控制台
- 任务 auto + approval
- 正文 30 天 / 元数据长期
- 本机 stdio MCP
```

### Phase 1：跨机器

```text
- Streamable HTTP MCP / 出站 WSS
- OAuth2 / mTLS
- Bus Payload Spool
- Agent 本地 spool
- 离线队列、重连、游标
- 多机 PostgreSQL
```

### Phase 2：规模化与强化

```text
- 多区域 Bus
- E2E payload 加密
- 审批策略 DSL
- 跨组织联邦（后续）
- 消息审计哈希链
```

## 15. 测试与验收

```text
身份：
  伪造 sender / 跨 namespace / 越权房间 → 拒绝

群组：
  创建 / 邀请 / 成员退出 / 群消息 / 游标

消息：
  幂等重复只落一条
  未处理 30 天正文删除，元数据可查
  ack 后按策略删除正文
  离线消息重连可读

任务：
  auto low-risk 自动执行
  high-risk 强制审批
  拒绝审批不执行
  allowed_tools 不能扩大权限
  审批过期/重复点击幂等

人类：
  owner 审批 / 暂停自动执行
  非 owner 消息不被当作指令

安全：
  prompt injection 不绕过 policy
  限流 / 反重放 / token 轮换
```

## 16. 需要继续确认的问题

```text
1. Bus 部署在哪个域名/环境，是否已有统一登录（OIDC）？
2. 人类审批是否允许多级（owner → admin）？
3. 正文 30 天删除后，审计是否需要保留“正文哈希”用于对账？
4. 任务自动执行的“低风险”边界由谁配置：平台默认还是每个 owner？
5. 跨机器是否要求端到端加密，还是服务端可解密（便于审批和审计）？
```

## 17. 建议的第一版取舍

```text
先做：群组 + 人类 Web + 任务 auto/approval + 30 天正文 + 长期元数据
后做：跨机器远程 MCP + 多区域 + E2E 加密

原因：单机 Bus 能先验证消息、群组、审批和保留策略；
跨机器只替换传输层和部署形态，不推翻数据模型。
```
