# C 端「我的」个人中心

日期：2026-11-14

## 功能

```text
路由：/c/me（CShell）
底部导航：首页 / 聊 / 逛 / 订单 / 消息 / 我的
CApp 桌面侧栏与手机底部同步增加「我的」
```

### 个人资料

```text
头像（有 user_avatar_url 才请求，否则首字占位）
昵称：companion.user_nickname > account.display_name > username
登录账号 @username
账号类型 / 账号状态
「查看名片主页」弹层：大头像、昵称、账号类型、账号状态、登录账号
```

### 账号资料

```text
昵称编辑：PATCH /api/c/companion {user_nickname}
保存成功 toast「昵称已更新」
登录账号只读
修改密码入口 /password
```

### 通知偏好

```text
新消息提醒 / 伙伴主动关心 / 活动与优惠
本机 localStorage：qianke:c:preferences
操作后 toast 反馈
说明：当前为本机偏好，推送服务接入后同步账号
```

### 隐私与通用

```text
展示在线状态 / 已读回执（本机偏好）
恢复本机默认偏好
产品说明
退出登录（/auth/logout，确认后回 /home）
```

## 状态

```text
加载中：骨架屏
加载失败：错误卡片 + 重新加载
账号为空：空状态 + 刷新 / 重新登录
有数据：卡片分区
```

## 验证

```text
Playwright 1440 / 390 / 320 / 768：scrollWidth = clientWidth，无横向溢出
C 账号：小满 / @c_13900005678 / 消费者 / 正常
昵称保存 toast：昵称已更新
通知开关：状态切换 + localStorage 写入
查看名片主页：弹层打开，账号状态/登录账号正确
错误态：拦截第二次 /whoami → 个人资料暂时不可用；解除拦截后点击重新加载恢复
CApp 底部导航：6 个 Tab
Chrome DevTools：console 无报错；/whoami、/api/c/companion 均 200；无头像 404
```

## 已知限制

```text
通知偏好和隐私开关暂存本机，未接推送/服务端偏好表
个人中心不提供头像上传，沿用 C 端已有的头像接口/入口
退出登录有 window.confirm 确认
```

截图：

```text
docs/design/c-end-me-personal-center.png
docs/design/c-end-me-personal-center-mobile.png
docs/design/c-end-me-personal-card.png
```
