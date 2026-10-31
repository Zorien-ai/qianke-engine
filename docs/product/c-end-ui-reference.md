# C 端 UI 参考：去「AI 味」的消费级界面

> 页面：`/v2/#/c/app`
> 状态：可运行的界面参考，不是最终生产设计稿。

## 1. 设计目标

C 端入口从「企业工作台里的一个页面」改成独立的消费级应用：

```text
对话优先
服务关系清楚
交易状态可追溯
纸白、哑光、低饱和
```

初始进入页是「小鱼」对话，而不是数据仪表盘。

![C 端桌面端](../screenshots/c-app-white-desktop.png)

![C 端移动端](../screenshots/c-app-white-mobile.png)

## 2. 六条改造要求的落地

| 要求 | 落地 |
|---|---|
| 背景与间距 | 背景 `#FFFFFF`，侧栏 / 上下文 `#FCFCFB`；8px 基准，主要间距 16/20/24/32 |
| 去饱和 | 无紫蓝渐变、无外发光；强调色仅用于状态与图表 |
| 品牌精简 | 左上角纯文字「千客」；无 AI/PRO 徽章 |
| 数据可视化 | 1.5px 低饱和折线；网格透明度极低；无发光 |
| 微文案 | 无感叹号、火焰、情绪符号；状态用中性描述 |
| 材质层级 | 纸白面板 + 1px 细线；阴影只用于浮层；圆角 8–12px |

## 3. 设计变量

```css
--c-bg:       #ffffff;
--c-bg-soft:  #fcfcfb;
--c-panel:    #ffffff;
--c-panel-2:  #f6f6f3;
--c-panel-3:  #efefeb;
--c-line:     #e4e4de;
--c-line-soft:#efefeb;
--c-text:     #171715;
--c-text-2:   #5c5c56;
--c-text-3:   #6b6b64;
--c-accent:   #587376;
--c-positive: #6f8f7a;
--c-warning:  #7a6340;
--c-negative: #8a4f4f;
```

## 4. 桌面端结构

```text
左侧 248px：品牌 / 搜索 / 主导航 / 会话 / 伙伴卡
中间自适应：对话标题 / 消息流 / 快捷问题 / 输入区
右侧 304px：本期概览 / 图表 / 待确认报价 / 最近订单
```

桌面端截图：`docs/screenshots/c-app-white-desktop.png`

## 5. 移动端结构

参考 WhatsApp iOS 的移动端信息架构（Mobbin）：

https://mobbin.com/apps/whats-app-ios-8738dbc9-e7a8-4fef-91e5-6afd1c9d092b

映射方式：

```text
对话页：返回箭头 / 头像 / 名称 / 在线状态 / 右侧信息按钮
消息：深色发件块 + 行式收件文本 + 气泡内时间
输入：加号 / 细边框输入 / 圆形发送
会话列表：顶部「消息」/ 搜索 / 头像 / 名称 / 预览 / 时间 / 未读
底部：对话 / 商城 / 订单 / 概览
```

保留 C 端自己的纸白和低饱和规则，不直接复制 WhatsApp 的高饱和绿色。

头像：首字兜底；支持上传 PNG / JPEG / WebP（≤1MB），点击顶部/消息/概览头像可更换，失败回退首字。

![移动端对话](../screenshots/c-app-white-mobile.png)

验证：

```text
390 × 844 无横向溢出
键盘弹起（visualViewport 高度变化）输入框仍可见
输入聚焦时隐藏底部导航，失焦恢复
长按消息复制并显示轻提示
滚动离开底部后显示「回到底部」
对话页返回按钮打开消息列表
消息列表搜索 / 选中会话可用
底部导航与气泡内时间正常
发送失败出现重试条，重试不重复插入用户消息
控制台错误 0
```

## 6. 交互边界

```text
小鱼只做解释、提醒、锐评
店宠负责商品/活动/SOP 查询
成交必须由用户逐单确认
```

初始种子对话、报价卡和图表是界面参考数据；最近订单来自 `GET /api/c/orders`；快捷问题之后的链路会调用真实 C Agent。

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
- 断线后自动重连，退避 1s / 2s / 4s / 8s，最多 5 次
- 头部状态显示「店宠在线 / 连接中 / 正在重连 / 连接已断开」
- `@店宠` 唤醒真实店宠 Agent
- WebSocket 不可用时回退 HTTP POST
- 店宠回复 + 小鱼锐评一起进入消息流
- 店宠返回的 quote_id 会显示在右侧「待确认」卡片
- 点击「查看报价」进入商城逐单确认

历史消息会做 emoji/感叹号清理后再展示，避免旧数据破坏新 UI 的克制风格。

### 最近订单（真实数据）

右侧「最近订单」不再写死演示条目，订单页同理：

```text
GET /api/c/orders?limit=3    # CApp 挂载 / 切回会话时刷新
GET /api/c/orders?limit=50   # 订单页
```

- 订单页状态优先显示 `merchant_status`（CREATED / SHIPPED / COMPLETED / CANCELLED…），无该字段时回退旧字段 `status`；
- 有 `merchant_order_id` 时在订单号下方显示「商家单号」；
- 最近订单为空显示「还没有订单」；加载失败只做轻提示，不清空已加载的列表。

状态时间线与物流（merchant 字段）：

```text
merchant_tracking_no   运单号
merchant_carrier       承运商
merchant_status_at     最近状态时间
merchant_timeline      [{status, at}] 状态历史（后端给了优先用）
```

- 订单页按标准四步（已创建 → 已支付 → 已发货 → 已完成）展示已到达节点；已取消订单额外显示取消节点；
- 时间优先取 `merchant_timeline[].at`，没有时只对当前状态使用 `merchant_status_at`，不推断/编造时间；
- 承运商与运单号在卡片内独立展示；右侧「最近订单」空间有限，只显示承运商 + 单号后 4 位，完整单号放 `title`；
- 没有 merchant 字段的旧订单不显示时间线与物流，保持原有样式。

取消订单与退款：

```text
GET  /api/c/orders                           # order 新增 can_cancel / merchant_cancelled_at / merchant_refund_amount
POST /api/c/orders/{order_id}/cancel         # 取消已确认订单，成功返回 order；失败 detail 为 {code, message}
```

- 仅 `can_cancel=true` 的订单显示「取消订单」按钮；点击后行内展开二次确认（保留订单 / 确认取消），确认才发请求；
- 成功后刷新列表：状态显示「已取消」，有 `merchant_refund_amount` 时展示退款金额、有 `merchant_cancelled_at` 时展示取消时间；已取消订单不再出现取消按钮；
- 失败时展示后端 `detail.message`（如「已发货订单不可取消」），订单状态与按钮保持不变；
- CApp「最近订单」复用既有 `loadRecentOrders`，进入/切回会话时自然拿到取消后的状态（`merchant_status=CANCELLED` → 已取消）。

申请售后与工单状态：

```text
GET  /api/c/orders                              # order 新增 can_after_sale / after_sale
POST /api/c/orders/{order_id}/after-sales        # body {type: REFUND_ONLY|RETURN_REFUND, reason} → ticket
GET  /api/c/orders/{order_id}/after-sales        # 返回该订单售后工单列表
```

`after_sale` 结构：`{ticket_id, status, type, reason, refund_amount, created_at, resolved_at}`（无工单为 null）。

- 仅 `can_after_sale=true` 的订单显示「申请售后」；点击后行内表单选择「仅退款 / 退货退款」+ 填写原因（前端必填、≤200 字），确认提交才创建工单；
- 提交成功后刷新列表：展示工单号与「售后 · 待处理」；已有工单的订单展示状态（待处理 / 已通过 / 已拒绝）、类型、原因、退款金额（有值）、申请与处理时间；
- `REFUNDED`（售后工单已退款或订单状态已退款）显示「已退款」，不再显示取消订单与申请售后入口；已拒绝且后端 `can_after_sale=true` 时允许重新申请；
- 前端只展示后端字段，不推断退款金额或工单状态；CApp「最近订单」对已退款订单显示「已退款」。

## 7. 会话持久化

小鱼会话通过以下接口持久化：

```text
GET    /api/c/app/messages?thread_id=companion&limit=30
GET    /api/c/app/messages?thread_id=companion&limit=30&before=<cursor>
POST   /api/c/app/messages
DELETE /api/c/app/messages?thread_id=companion
```

保存内容：

```text
role: user / companion
content
metadata（如 order_id）
created_at
```

页面加载时优先展示最近 30 条持久化消息；没有历史时使用演示种子。发送消息、Agent 回复、订单确认结果都会写入该表。

会话分页与清理：

- 顶部「加载更早消息」按 `created_at < before` 取上一页；
- 右侧「清空小鱼会话」二次确认后删除当前 buyer 的 companion 消息；
- 删除只影响当前买家与会话，不影响订单或报价审计。

## 8. PWA 与移动端安全区

已加入可安装 PWA：

```text
/v2/manifest.webmanifest
/v2/sw.js
/v2/icons/icon-192.png
/v2/icons/icon-512.png
```

PWA 配置：

```text
display: standalone
start_url: /v2/#/c/app
scope: /v2/
theme_color: #ffffff
background_color: #ffffff
```

Service Worker 缓存：

```text
script / style / image / font
导航 HTML 外壳（离线兜底）
manifest / icons 由浏览器缓存
```

明确不缓存：

```text
/api/*
/auth/*
/whoami
/admin/*
```

安装提示：

- 监听 `beforeinstallprompt`，支持 Chromium 安装；
- iOS Safari 显示「分享 → 添加到主屏幕」提示；
- 已 standalone 打开时不显示。

在线状态：

- 监听 online / offline；
- 离线时顶部显示「当前处于离线状态」；
- WebSocket 断线继续走重连退避；HTTP 请求失败由页面错误处理兜底。

移动端增加 iOS 安全区：

```css
padding-top: env(safe-area-inset-top);
padding-bottom: env(safe-area-inset-bottom);
height: calc(56px + env(safe-area-inset-bottom));
```

覆盖对话头部、底部导航、消息列表头部和主体底部。

验证：

```text
manifest         200
icon-192         200
icon-512         200
Service Worker   activated，scope /v2/
shell cache      存在
离线事件         顶部提示出现，恢复后消失
安装事件         安装条出现
C 端 App 控制台  0 errors / 0 warnings
```

## 9. 文件

```text
web/src/views/CApp.vue
web/src/App.vue          # standalone 路由不套企业工作台外壳
web/src/router.js
web/public/manifest.webmanifest
web/public/sw.js
web/public/icons/
```

## 10. 商家运营台（管理员）

`/v2/#/admin/c-end`（`web/src/views/CAdminAudit.vue`）顶部三个视图切换：交易审计 / 商家订单 / 售后工单；交易审计原有筛选、分页、统计与 CSV 导出全部保留，商家订单与售后工单为受控操作入口，操作成功后自动刷新。

```text
GET   /api/c/admin/merchant/orders?limit=100&status=&buyer_id=
PATCH /api/c/admin/merchant/orders/{order_id}/status   {status, tracking_no?, carrier?}
GET   /api/c/admin/after-sales?status=&limit=
PATCH /api/c/admin/after-sales/{ticket_id}             {approved}
```

- 商家订单：状态筛选（CREATED/PAID/SHIPPED/COMPLETED/CANCELLED/REFUNDED）；行内操作按状态机给出——CREATED→标记已支付/取消、PAID→发货（行内表单填物流单号，承运商可选）/取消、SHIPPED→标记完成；物流单号前端必填且至少 4 位，最终以后端校验为准；
- 售后工单：状态筛选（OPEN/APPROVED/REJECTED）；待处理工单可「通过 / 拒绝」，通过后工单变为已通过并显示退款金额；
- 所有写操作错误以 toast 展示后端 `detail.message`（兼容字符串与 `{code,message}`），列表数据不被清空；
- 白色极简：与既有管理页共用 `.card/.table/.btn` 样式，表格在移动端容器内横向滚动，页面本身不横向溢出。

## 11. 双宠谈判（CApp）

CApp 快捷问题区新增「让小鱼去砍价」入口（`web/src/views/CApp.vue`）：

```text
POST /api/c/negotiations
body {need: "跑鞋", budget: 500, quantity: 1}
→ {status: "ACCEPTED"|"REJECTED", transcript: [{actor: "c_pet"|"b_pet", name, text}], quote|null, reason?}
```

- 默认按当前 companion 会话发起：need=跑鞋、budget=500、quantity=1；若当前停在其它会话会先切回 companion；
- `transcript` 按 actor 映射为对话消息：`c_pet`→companion、`b_pet`→merchant（作者名取 transcript.name），谈判过程可见，不伪造内容；
- `ACCEPTED`：把返回的 quote 写入 `storeQuote`，复用既有「来自店宠的结构化报价」卡与「查看报价」链接，成交仍需用户在商城逐单确认；
- `REJECTED`：不生成报价卡（同时隐藏初始静态演示报价卡，待确认计数归零），只追加一条基于 `reason` 的伙伴解释消息；
- 调用中按钮禁用、`typing` 同时阻断发送与重复点击；失败在入口下方显示轻提示（兼容 `detail` 字符串与 `{code,message}`），不打断会话；
- 白色极简、移动端快捷问题行可横向滚动，消息气泡与报价卡不溢出。
