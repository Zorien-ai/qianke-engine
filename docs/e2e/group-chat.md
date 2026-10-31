# 群聊 / 多成员 @ E2E

> 日期：2026-10-31 · 状态：通过（真实群 API + 真实 CApp）

## 1. 默认群

```text
group_demo
周末徒步群
成员：小鱼（伙伴）、山野店宠（商家）、小满（好友）
```

接口：

```text
GET  /api/c/groups
POST /api/c/groups
GET  /api/c/groups/{group_id}/messages
POST /api/c/groups/{group_id}/messages
```

## 2. 多成员 @

真实 API：

```text
POST /api/c/groups/group_demo/messages
{"content":"@小鱼 @店宠 这款包有优惠吗"}
```

返回：

```text
replies:
小鱼：我看到了。价格、优惠和售后以商家/结算页为准，需要确认的我来帮你记。
山野店宠：峰行 通勤双肩包 199 元，库存 14 件；平台满 299 减 30，
           单买 199 凑到 299 可用满减，具体以结算页为准。
```

一条消息按 mention 顺序触发多个成员回复。

## 3. CApp 真实浏览器

```text
打开 CApp
→ 默认进入「周末徒步群」
→ 会话显示「群」+「3 人 · 群聊」
→ 点击 @ 按钮弹出 3 名成员
→ 连续插入 @小鱼、@店宠
→ 输入「这款包有优惠吗」并发送
→ 用户消息上屏
→ 小鱼回复
→ 山野店宠回复
```

群消息 @ 高亮；群内点击 @：

```text
显示轻提示「群聊内 @小鱼 只作提醒，不切换会话」
仍停留在周末徒步群
```

单聊里点击 @ 仍切到对应单聊。

## 4. 测试与构建

```bash
pytest tests/ -q
# 571 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 5.93s
```

新增：

```text
tests/test_c_end_group.py
5 passed
```

覆盖：

```text
默认群与 3 名成员
@店宠 + @小鱼 双回复
@小满 单回复
无 @ 不触发回复
群归属隔离
创建自定义群
```

## 5. 群未读 / @ 通知

群线程复用 `c_thread_read` 和 `c_mention`：

```text
GET  /api/c/threads/unread
POST /api/c/threads/{group_id}/read
GET  /api/c/mentions
```

真实 API：

```text
baseline: group_demo 0

发送「@我 @小满 明天几点集合」并收到小满回复后：
group_demo 1
mentions 1

POST /api/c/threads/group_demo/read 后：
group_demo 0
```

真实 CApp：

```text
群会话显示未读角标 1
顶部显示 @1
点击 @1 → 打开群会话、@1 消失、群角标清零
```

## 6. 已知限制

```text
只有一个默认群，群创建 API 可用但 UI 暂未提供创建入口
群消息只走 HTTP，没有群 WebSocket 推送
群 replies 的结构化 metadata（如报价卡）暂未在群聊渲染
群内 @ 只做提醒，不切换会话
没有 @全体、撤回、群管理
```
