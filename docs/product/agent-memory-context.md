# Agent 用户记忆与上下文 · 架构契约

> 状态：架构设计 / 吸收参考方案，**业务代码尚未改动**  
> 适用：C 端店宠、B 端经营 Agent、A 端审计  
> 关联：`docs/decisions/three_agent_platform_architecture_decisions_v0.1.md` §7

## 1. 核心结论

用户记忆不是“把历史消息塞进上下文窗口”，而是一条有明确读写边界的链路：

```text
读：身份解析 → 记忆寻址 → 多源读取 → 上下文组装 → Agent
写：会话结束 → 异步复盘 → 候选记忆 → 规则校验 → 用户确认 / 策略允许 → 写回 + 版本 + 审计
```

两条链路的默认原则：

- **能读到 ≠ 能相信**：每条上下文必须带来源、时效和置信度。
- **能写入 ≠ 能生效**：LLM 只能生成候选记忆，正式长期记忆需确认。
- **身份不唯一就不读**：宁可先补问，不把记忆挂到错误客户上。

## 2. 读路径

### 2.1 身份解析

输入可能来自：

```text
客户 ID / 买家 ID
别名称呼
订单号
收货人 / 收货地址
当前会话成员
```

输出必须是：

```text
resolved_customer_id
confidence
evidence[]（哪条信息匹配）
ambiguous?（0 / 1 / 多个候选）
```

规则：

| 情况 | 行为 |
|---|---|
| 唯一且置信度足够 | 继续记忆寻址 |
| 多个候选 | 不读取，先补问 |
| 无可靠记录 | 不读取，先补问或走冷启动 |
| 跨租户命中 | 拒绝，记录审计 |

### 2.2 记忆寻址

在读取之前先确定：

```text
tenant_id / merchant_id
customer_id
actor / role / permission_scope
memory_types[]（本次需要哪些记忆）
```

禁止跨租户检索，禁止把平台级画像暴露给商户，禁止把无权限的原始上下文注入 Prompt。

### 2.3 多源读取

| 记忆类型 | 内容 | 典型生命周期 |
|---|---|---|
| 长期画像 | 稳定身份、偏好、关系、长期目标 | 长期 / 可版本化 |
| 短期任务 | 当前目标、进度、待办 | 任务结束 / TTL |
| 会话历史 | 消息、证据、结果 | 会话 + 保留期 |
| 处理记录 | 谁在何时做了什么、审批与执行 | 审计保留期 |
| 文档与 SOP | 业务规则、口径、知识 | 文档版本 |

读取时至少带：

```text
memory_id
source
type
content
created_at / updated_at
confidence
status（ACTIVE / SUPERSEDED / DELETED）
```

### 2.4 上下文组装

组装不是简单拼接，而是：

```text
过滤（权限 / 租户 / 状态 / TTL）
→ 去重
→ 冲突检测
→ 排序（当前对话 > 最近更新 > 来源可信度）
→ 预算裁剪
→ 输出可解释上下文
```

每个进入 Prompt 的片段都应可回指到 `memory_id` / `source`。  
当前对话与历史记忆冲突时，**当前对话优先**；如果可能代表长期偏好变化，生成候选记忆等待确认。

### 2.5 Agent

Agent 只接收“已组装、可解释、已授权”的上下文：

```text
messages
context_items[]
current_task
permission_scope
trace_id
```

Agent 不应直接查询任意记忆表；记忆读取必须经过受控的 Memory Tool / Service。

## 3. 写路径

### 3.1 触发

```text
会话结束
或 30 分钟无新消息（B 端会话画像现有策略）
或 用户主动说“记住……”
```

写回异步执行，不阻塞当前回答。

### 3.2 异步复盘 Agent

复盘 Agent 负责：

- 从会话中抽取事实、偏好、关系、待办候选；
- 标注来源消息 / 时间 / 会话；
- 不直接写长期记忆；
- 失败可重试，必须有幂等键。

### 3.3 候选记忆

```json
{
  "candidate_id": "mc_...",
  "customer_id": "...",
  "tenant_id": "...",
  "type": "preference",
  "key": "preferred_delivery_time",
  "value": "工作日上午",
  "source_message_ids": ["..."],
  "confidence": 0.82,
  "status": "CANDIDATE"
}
```

### 3.4 规则校验

校验必须由确定性代码完成：

```text
Schema / 字段白名单
来源可追溯
权限 / 租户匹配
PII / 支付凭证过滤
冲突检测
置信度阈值
重复 / 幂等
```

### 3.5 用户确认 / 策略允许

- 正式长期记忆：用户确认后才写入 `ACTIVE`。
- 低风险内部摘要：可按策略自动更新，但不能跨越权限边界。
- 用户拒绝：候选标记 `REJECTED`，不得再次静默写入。
- 用户可查看、修改、删除正式记忆。

### 3.6 写回 + 版本 + 审计

```text
ACTIVE
SUPERSEDED（新版本替代）
DELETED（立即可用性移除）
```

必须记录：

```text
谁写的
何时写的
基于哪条会话 / 哪条证据
旧值 / 新值
确认人 / 确认方式
trace_id / request_id
```

删除后立即从 Agent 可用记忆中移除；回收站中的记忆不得被 Agent 使用。

## 4. 状态机

```text
CANDIDATE
  ├─ 校验失败 → REJECTED
  ├─ 需要确认 → PENDING_CONFIRMATION
  └─ 策略允许 → ACTIVE
PENDING_CONFIRMATION
  ├─ 用户拒绝 → REJECTED
  └─ 用户确认 → ACTIVE
ACTIVE
  ├─ 新版本 → SUPERSEDED
  └─ 用户删除 → DELETED
```

## 5. 护栏

| 风险 | 处理 |
|---|---|
| 身份不唯一 | 先补问，不读取 |
| 无可靠记录 | 冷启动 / 先补问 |
| 记忆过期 | 降低权重或标注“可能过期” |
| 记忆冲突 | 标注来源，当前对话优先 |
| 跨租户 | 拒绝，审计 |
| PII / 支付凭证 | 不写入长期记忆 |
| 候选记忆被重复写入 | 幂等键 + 唯一约束 |
| 删除后仍被召回 | 读取层强制过滤 `DELETED` |

## 6. 与当前实现的关系

当前代码已有可复用的基础：

```text
src/rag_demo/chat_memory.py          会话记忆
src/rag_demo/c_end/memory_daily.py   C 端每日记忆摘要
src/rag_demo/c_end/chat_profile.py   C 端会话画像
src/rag_demo/b_end/insights.py       B 端画像 / 洞察
src/rag_demo/agent/tools/chat_profile.py  画像 Tool
docs/e2e/profile-three-layers.md     三层画像
```

但“身份解析 → 上下文组装元数据 → 候选记忆确认 → 版本化写回”目前还没有形成一条统一的 Memory Service 契约。  
本文件是目标契约，**不代表所有能力已经实现**。

## 7. 落地顺序

### Phase 1 · 读路径加固

- 增加身份解析结果 `{customer_id, confidence, evidence, ambiguous}`；
- 读取层强制租户 / 权限 / `DELETED` 过滤；
- 上下文条目带 `source / updated_at / confidence`；
- 增加“身份不唯一 / 记录不足”补问分支。

### Phase 2 · 写路径闭环

- 复盘 Agent 只输出候选记忆；
- 增加候选表、幂等键、规则校验；
- 增加用户确认 / 拒绝；
- 写回版本与审计。

### Phase 3 · 记忆 Eval

```text
identity_alias_collision
identity_not_found
identity_multiple_matches
stale_profile
conflicting_preference
cross_tenant_memory
pii_not_persisted
deleted_memory_not_recalled
duplicate_candidate_idempotent
user_rejected_not_written
```

## 8. 验收标准

```text
- 任何记忆进入 Prompt 都可回指 source / memory_id
- 身份不唯一时不读取记忆，先补问
- LLM 不能直接写正式长期记忆
- 用户拒绝的候选不会再次静默写入
- 删除后下一轮请求立即不可召回
- 跨租户读取被拒绝并记录审计
- 写回具备版本与审计字段
```

## 9. 与架构图

- 读 / 写链路图：`docs/assets/architecture-agent-memory.png`
- 源文件：`docs/design/architecture-agent-memory.html`
- Runtime 主图：`docs/assets/architecture-agent-runtime.png`
