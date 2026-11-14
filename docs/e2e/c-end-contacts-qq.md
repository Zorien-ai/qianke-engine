# C 端 QQ 式联系人 / 会话管理

日期：2026-11-14

## 功能

```text
/c/social 重构为双入口：
  消息：最近会话、未读、最后一条消息、置顶/免打扰/隐藏/标读
  联系人：可能想认识的人、新朋友、群通知、全部/好友/店宠/群聊筛选
进入好友/群聊后可发送消息；小鱼会话直接进入 /c/app
频道 / 机器人 / 设备：按产品确认不做，未渲染
```

## 后端新增

```text
c_friend_request    好友申请：请求人、说明、PENDING/ACCEPTED/REJECTED
c_group_notice      群通知：标题/内容/UNREAD/READ
c_conversation_pref 会话偏好：置顶/免打扰/隐藏/更新时间
c_friend_removed    好友删除墓碑，避免默认好友被重新播种
```

API：

```text
GET    /api/c/friend-requests
POST   /api/c/friend-requests/{id}/accept
POST   /api/c/friend-requests/{id}/reject
GET    /api/c/group-notices
POST   /api/c/group-notices/{id}/read
GET    /api/c/conversation-prefs
PATCH  /api/c/conversation-prefs/{thread_id}
DELETE /api/c/friends/{friend_id}
```

好友申请/群通知当前没有外部 producer，页面单独展示空态；后续 B/IM 接入时可直接复用内部写入函数，不伪造数据。

## 设计方法落地

### 视觉设计

```text
色彩语义：
  店宠绿 / 好友中性 / 群聊淡紫 / 未读橙 / 危险操作红
文字层级：
  页标题 23px，联系人行 14px，说明/时间 11-12px
尺寸：
  头像 42px、操作按钮 28-34px、底部导航图标 20px
```

### 交互设计

```text
防误操作：
  删除好友二次确认；隐藏会话可恢复
操作路径：
  列表 → 聊天一步；会话操作在“⋯”动作面板
反馈：
  添加/接受/拒绝/置顶/免打扰/隐藏均 toast 反馈
```

### 体验优化

```text
最近会话按置顶 + 最后消息排序，展示未读与摘要
搜索覆盖好友/店宠/群聊
加载态、错误态、空态分开处理
移动端 390 / 桌面 1440 无横向溢出
```

## 验证

```text
pytest：805 passed, 6 skipped
前端 build PASS
Playwright：390 消息/联系人/好友申请/群通知/聊天/操作面板
  打开聊天后消息区 510px，composer 在底部
  320/390/768/1440：scrollWidth = clientWidth
Chrome DevTools：console 无消息；friends/groups/unread/prefs/notices 均 200
```

## 已知限制

```text
好友申请 / 群通知需要外部 producer（真实用户或 B 端），当前只有空态
群聊在 CSocial 内走 HTTP，不使用 CApp 的群 WebSocket
未做频道/机器人/设备
```

截图：

```text
docs/design/c-end-contacts-messages.png
docs/design/c-end-contacts-contacts.png
docs/design/c-end-contacts-chat.png
docs/design/c-end-contacts-friend-request.png
```
