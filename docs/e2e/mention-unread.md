# Mention 元数据 / 未读 / 点击定位 E2E

> 日期：2026-10-31 · 状态：通过（真实 API + 真实 CApp）

## 1. mention 元数据

消息内容中的已知成员会被解析并落库：

```text
@小鱼 → companion / 小鱼
@店宠 → store_demo / 山野店宠
@小满 → friend_demo / 小满
@我   → me / 我
```

消息 metadata：

```json
{"mentions":[{"token":"@店宠","target_id":"store_demo","name":"山野店宠","kind":"merchant","thread_id":"store_demo"}]}
```

新增 `c_mention` 表：

```text
mention_id / owner_id / thread_id / message_id
token / target_id / target_name / created_at / read_at
```

## 2. 未读

新增 `c_thread_read`：

```text
owner_id / thread_id / last_read_at
```

接口：

```text
GET  /api/c/threads/unread
POST /api/c/threads/{thread_id}/read
GET  /api/c/mentions?unread_only=true
POST /api/c/mentions/read
```

首次访问线程时建立已读基线，历史消息不产生未读；之后只统计**对方发来的新消息**。

真实 API：

```text
baseline:
threads {companion:0, store_demo:0, friend_demo:0}, mentions 0

发送 @店宠 并收到店宠回复后:
store_demo 2

插入一条 companion 消息「@我 已收到你的退货申请」后:
companion 1, mentions 1

mark store_demo read 后:
store_demo 0
```

## 3. CApp 真实交互

打开 CApp：

```text
顶部出现 @1 未读通知
点击 @1
→ 调用 mentions/read
→ 打开最近未读提及所在会话
→ @1 消失
```

点击消息里的 `@店宠`：

```text
当前在 companion 会话
→ 点击 @店宠
→ 切换到「山野户外旗舰店」会话
```

点击 `@小鱼` / `@小满` 同理；`@我` 不跳转。

## 4. 轮询与暂停

```text
挂载时拉取一次未读
每 20s 轮询
document.hidden 时暂停
回到前台立即刷新
发送/收到消息后节流刷新
```

## 5. 测试与构建

```bash
pytest tests/ -q
# 566 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 4.82s
```

新增：

```text
tests/test_c_end_mentions_unread.py
5 passed
```

## 6. 已知限制

```text
@通知目前只统计「别人 @我」；自己 @店宠 不会给自己产生通知
没有群聊/多成员 @
没有 WebSocket 推送通知，依赖 20s 轮询与请求后刷新
@N 点击只打开最近一条未读提及所在会话，无提及列表弹层
消息只保留已知成员的 mention 元数据，未知 @ 文本不解析
```
