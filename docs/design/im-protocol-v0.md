# Qianke IM Protocol v0

**版本：** v0.1（协议版本号 `1`）
**状态：** P0 草案，已实现 `src/rag_demo/im/protocol.py` 与单测；服务端/客户端尚未接入
**关联：** `docs/product/im-social-commerce-blueprint.md`、`docs/agent.md`

---

## 1. 目标与非目标

目标：给"千客 IM"定义一套**与业务解耦**的消息协议，让 Web 客户端、伙伴 Agent、店宠 Agent、以后的外部通道（OneBot / 官方机器人）都用同一种语言说话。

非目标（v0 不做）：

- 语音/视频通话、红包、朋友圈、端到端加密；
- 多机集群、跨机房同步；
- 业务语义（价格、库存、订单状态）——这些留在服务层，协议只传"消息"。

设计来源：

- **协议形状**参考 OneBot 11（事件 / 动作 / 消息段），便于以后写外部通道 adapter；
- **可靠性策略**参考 dsh-bili-whale：失败可见、结构化错误、发送 at-most-once、状态可审计。

## 2. 分层边界

```text
客户端/Agent ──(本协议)──> IM 服务端 ──(函数调用)──> 业务服务
```

- 协议层**不 import** `rag_demo.store` / `rag_demo.agent` / `rag_demo.auth`；
- 业务层不直接操作 WebSocket、不拼 JSON；
- 未知字段忽略、未知消息段降级为文本，保证前向兼容。

## 3. 传输

- Web 端：WebSocket `/im/ws`，文本帧，UTF-8 JSON。
- 单帧上限 **64 KiB**；超过直接拒收（`FRAME_TOO_LARGE`）。
- 连接鉴权：复用现有登录 Cookie（`auth.SESSION_COOKIE`）；握手帧里带 `protocol_version` 与 `device_id`。
- v0 不提供 HTTP 长轮询；离线同步用 `conversation.sync` 动作。

## 4. 帧类型

所有帧都是一个 JSON 对象，`type` 字段区分：

| type | 方向 | 说明 |
|---|---|---|
| `hello` | C→S | 握手：协议版本、设备、可选 token |
| `hello_ack` | S→C | 握手结果：session_id、user_id、服务器时间 |
| `event` | S→C | 服务端推送（消息、已读、在线状态…） |
| `action` | C→S | 客户端请求（发消息、同步、已读…） |
| `response` | S→C | 动作响应，`echo` 对应请求 |
| `ping` / `pong` | 双向 | 保活 |

动作/响应示例：

```json
{"type":"action","action":"message.send","echo":"e_1",
 "params":{"conversation_id":"c_1","client_msg_id":"cm_1",
           "segments":[{"type":"text","data":{"text":"在吗"}}]}}
```

```json
{"type":"response","echo":"e_1","status":"ok",
 "data":{"message_id":"m_1","seq":42}}
```

```json
{"type":"response","echo":"e_1","status":"error",
 "error":{"code":"BAD_PARAMS","message":"segments 不能为空"}}
```

## 5. 事件

| event | data | 说明 |
|---|---|---|
| `session.ready` | `{user_id, session_id}` | 握手完成后确认 |
| `message.created` | `{message}` | 新消息，含 `seq` |
| `message.read` | `{conversation_id, user_id, seq}` | 已读游标 |
| `presence.changed` | `{user_id, state}` | 在线状态变化 |
| `conversation.updated` | `{conversation_id, last_seq, last_message_id?}` | 会话摘要变化 |
| `system.notice` | `{level, text}` | 系统提示（断线、限流、风控） |

`message` 结构：

```json
{"message_id":"m_1","conversation_id":"c_1","seq":42,
 "sender":{"kind":"user","id":"u_1"},
 "segments":[{"type":"text","data":{"text":"你好"}}],
 "client_msg_id":"cm_1","created_at":"2026-10-29T12:00:00Z"}
```

`conversation_id` 与会话类型（单聊/群聊/人机）由服务端生成，协议不区分；参与者信息由服务端通过 `conversation.updated` / HTTP 查询补全。

## 6. 动作

| action | params | 说明 |
|---|---|---|
| `conversation.list` | `{}` | 拉会话列表 |
| `conversation.sync` | `{conversation_id, after_seq}` | 增量拉消息（断线重连） |
| `message.history` | `{conversation_id, before_seq?, limit?}` | 历史消息，默认 50，最大 100 |
| `message.send` | `{conversation_id, client_msg_id, segments, meta?}` | 发消息；`client_msg_id` 幂等 |
| `message.read` | `{conversation_id, seq}` | 上报已读游标 |
| `presence.update` | `{state}` | 在线状态：`online/away/quiet/sleeping` |

响应数据：

- `message.send` → `{message_id, seq}`
- `conversation.sync` → `{messages:[...], latest_seq}`
- `message.history` → `{messages:[...]}`
- 其余 → `{}` 或业务字段

## 7. 消息段

| type | data | 说明 |
|---|---|---|
| `text` | `{text}` | 纯文本，≤ 4000 字 |
| `at` | `{user_id, name?}` | @ 某人/某 Agent |
| `reply` | `{message_id}` | 引用回复 |
| `image` | `{url}` 或 `{file_id}` | 只允许 http/https，禁止本地路径 |
| `business_card` | `{card_type, ref_id, title, subtitle?, amount?, fallback_text?}` | 商品/报价/订单草稿，**只带 id，不带任何密钥** |
| `system_notice` | `{text}` | 系统提示 |

规则：

1. 一条消息最多 32 段，至少 1 段。
2. `business_card` 的 `card_type` 只能是 `product` / `quote` / `order_draft`，且 `fallback_text` 缺失时由协议层补 `【商品】标题`。
3. 卡片里**禁止**出现 `token` / `confirmation_token` / `csrf` / `cookie` / `sessdata` / `password` / `secret` / `credential` 等键；订单确认 token 永远不出现在消息里。
4. 未知段类型不报错，保留 `fallback_text`，旧客户端显示降级文本。

## 8. 可靠性与幂等

- **seq**：每个会话单调递增，从 1 开始；`conversation.sync` 用 `after_seq` 增量拉取。
- **client_msg_id**：客户端生成，同一发送者在同一会话内幂等；重复发送返回同一 `message_id`。
- **发送 at-most-once**：客户端超时不得自动重发；先 `sync` 回读，确认未落库再重试。
- **错误结构化**：所有失败返回 `{code, message}`，调用方按 `code` 判断，禁止字符串匹配。

## 9. 错误码

| code | 场景 |
|---|---|
| `BAD_FRAME` | 不是 JSON 对象、缺 `type` |
| `BAD_ENCODING` | 非 UTF-8 |
| `FRAME_TOO_LARGE` | 超过 64 KiB |
| `UNKNOWN_FRAME_TYPE` | 未知 `type` |
| `PROTOCOL_VERSION_UNSUPPORTED` | 握手版本不支持 |
| `BAD_PARAMS` | 参数类型/长度不合法 |
| `BAD_ID` | id 格式不合法 |
| `UNKNOWN_ACTION` / `UNKNOWN_EVENT` | 未知动作/事件 |
| `BAD_SEGMENT` | 消息段结构非法 |
| `EMPTY_MESSAGE` / `TEXT_TOO_LONG` / `TOO_MANY_SEGMENTS` | 消息内容超限 |
| `BAD_CARD` / `CARD_SECRET_LEAK` | 卡片非法或含密钥 |
| `BAD_MESSAGE` / `BAD_RESPONSE` | 消息/响应结构非法 |

## 10. 与现有 C 端接口的关系

| 现有 | 迁移到 |
|---|---|
| `WS /api/c/ws/chat/{friend_id}` | `/im/ws` + `message.send`（旧端点保留兼容） |
| `GET /api/c/friends` | `conversation.list`（HTTP 查询保留） |
| `GET /api/c/friends/{id}/messages` | `message.history` / `conversation.sync` |
| `POST /api/c/friends/{id}/messages` | `message.send` |
| `c_message.content` | `segments` 的 `text` 段（`from_legacy_content` / `to_legacy_content` 桥接） |

## 11. 与 OneBot 11 的映射（以后写外部通道 adapter 时用）

| 本协议 | OneBot 11 |
|---|---|
| `message.created` | `post_type=message` |
| `text` / `at` / `reply` / `image` 段 | 同名 segment |
| `message.send` | `send_private_msg` / `send_group_msg` |
| `message_id` | `message_id` |
| `client_msg_id` | 无对应，由 adapter 生成并去重 |

## 12. 兼容策略

- 新增字段：直接加，旧端忽略；
- 新增消息段：旧端降级为 `fallback_text`；
- 删除/改语义：必须升 `PROTOCOL_VERSION`，服务端在 `hello` 阶段拒绝旧版本并返回支持的版本列表。
