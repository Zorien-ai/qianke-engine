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

```text
顶部：千客 / 会员等级 / 会话信息
中间：完整对话流
底部：快捷问题 / 输入区 / 固定四栏导航
概览：从底部导航打开右侧抽屉
```

移动端截图：`docs/screenshots/c-app-mobile.png`

验证：

```text
390 × 844 无横向溢出
对话 / 快捷问题 / 移动端概览抽屉可用
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

## 7. 文件

```text
web/src/views/CApp.vue
web/src/App.vue          # standalone 路由不套企业工作台外壳
web/src/router.js
```
