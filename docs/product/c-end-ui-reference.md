# C 端 UI 参考：去「AI 味」的消费级界面

> 页面：`/v2/#/c/app`
> 状态：可运行的界面参考，不是最终生产设计稿。

## 1. 设计目标

C 端入口从「企业工作台里的一个页面」改成独立的消费级应用：

```text
对话优先
服务关系清楚
交易状态可追溯
中性、哑光、低饱和
```

初始进入页是「小伴」对话，而不是数据仪表盘。

![C 端桌面端](../screenshots/c-app-desktop.png)

![C 端移动端](../screenshots/c-app-mobile.png)

## 2. 六条改造要求的落地

| 要求 | 落地 |
|---|---|
| 背景与间距 | 背景 `#0F0F11`，卡片 `#161618`；8px 基准，主要间距 16/20/24/32 |
| 去饱和 | 无紫蓝渐变、无外发光；强调色仅用于状态与图表 |
| 品牌精简 | 左上角纯文字「千客」；无 AI/PRO 徽章 |
| 数据可视化 | 1.5px 低饱和折线；网格透明度极低；无发光 |
| 微文案 | 无感叹号、火焰、情绪符号；状态用中性描述 |
| 材质层级 | 卡片与背景明度差极小；阴影模糊 ≤8px、透明度 ≤8%；圆角 8–12px |

## 3. 设计变量

```css
--c-bg:       #0f0f11;
--c-bg-soft:  #131315;
--c-panel:    #161618;
--c-panel-2:  #1b1b1e;
--c-panel-3:  #202023;
--c-line:     #29292d;
--c-text:     #e7e7e9;
--c-text-2:   #a3a3aa;
--c-text-3:   #707078;
--c-accent:   #8d96a3;
--c-positive: #7e9888;
--c-warning:  #a89a7c;
```

## 4. 桌面端结构

```text
左侧 248px：品牌 / 搜索 / 主导航 / 会话 / 伙伴卡
中间自适应：对话标题 / 消息流 / 快捷问题 / 输入区
右侧 304px：本期概览 / 图表 / 待确认报价 / 最近订单
```

桌面端截图：`docs/screenshots/c-app-desktop.png`

## 5. 移动端结构

参考 WhatsApp iOS 的移动端信息架构（Mobbin）：

https://mobbin.com/apps/whats-app-ios-8738dbc9-e7a8-4fef-91e5-6afd1c9d092b

映射方式：

```text
对话页：返回箭头 / 头像 / 名称 / 在线状态 / 右侧信息按钮
消息：低饱和绿色发件气泡 + 深色收件气泡 + 气泡内时间
输入：加号 / 胶囊输入框 / 圆形发送
会话列表：顶部「消息」/ 搜索 / 头像 / 名称 / 预览 / 时间 / 未读
底部：对话 / 商城 / 订单 / 概览
```

保留 C 端自己的中性深色和低饱和规则，不直接复制 WhatsApp 的高饱和绿色。

![移动端对话](F:/workspace/python/rag-demo/docs/screenshots/c-app-mobile-whatsapp.png)

![移动端消息列表](F:/workspace/python/rag-demo/docs/screenshots/c-app-mobile-threads.png)

验证：

```text
390 × 844 无横向溢出
对话页返回按钮打开消息列表
消息列表搜索 / 选中会话可用
底部导航与气泡内时间正常
控制台错误 0
```

## 6. 交互边界

```text
小伴只做解释、提醒、锐评
店宠负责商品/活动/SOP 查询
成交必须由用户逐单确认
```

初始种子对话、报价卡和图表是界面参考数据；快捷问题之后的链路会调用真实 C Agent。

![C 端真实 Agent 草稿与确认](F:/workspace/python/rag-demo/docs/screenshots/c-app-live.png)

### 真实链路

点击「看 500 元以内的跑鞋」会调用真实 C 端 Agent：

```text
C Agent 查商品
→ 生成待确认订单草稿
→ 右侧面板出现「确认并创建订单」
→ 用户确认
→ 调用 C Agent resume 创建订单
```

Agent 不能自行确认订单；确认动作始终由用户触发。

实测：

```text
POST /api/c/agent/run      200
POST /api/c/agent/resume   200
订单 order_... 已创建
```

### 店宠会话

「山野户外旗舰店」会话已接入 IM 店宠接口：

```text
GET  /api/c/friends/store_demo/messages?limit=20
POST /api/c/friends/store_demo/messages
WS   /api/c/ws/chat/store_demo
```

- 加载最近 20 条持久化消息
- 进入店宠会话时建立 WebSocket
- `@店宠` 唤醒真实店宠 Agent
- WebSocket 不可用时回退 HTTP POST
- 店宠回复 + 小伴锐评一起进入消息流
- 店宠返回的 quote_id 会显示在右侧「待确认」卡片
- 点击「查看报价」进入商城逐单确认

历史消息会做 emoji/感叹号清理后再展示，避免旧数据破坏新 UI 的克制风格。

## 7. 会话持久化

小伴会话通过以下接口持久化：

```text
GET  /api/c/app/messages?thread_id=companion&limit=50
POST /api/c/app/messages
```

保存内容：

```text
role: user / companion
content
metadata（如 order_id）
created_at
```

页面加载时优先展示持久化消息；没有历史时使用演示种子。发送消息、Agent 回复、订单确认结果都会写入该表。

## 8. 文件

```text
web/src/views/CApp.vue
web/src/App.vue          # standalone 路由不套企业工作台外壳
web/src/router.js
```
