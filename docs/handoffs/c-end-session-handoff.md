# C 端会话 Handoff

日期：2026-11-14  
新会话职责：C 端产品、C 端页面、C 端 Agent/IM 功能与 C 端 UI 验收。  
当前主协调会话不再承接 C 端编码，只做系统/测评/验收协调。

## 基线与仓库

```text
分支：b-end-2.0-p0
最新提交：0f6c0ac
最新已合入 C 端 / UI 相关 PR：
  #24 QQ 式联系人 / 好友申请 / 群通知 / 会话偏好
  #25 C 端去渐变
  #26 Landing 去渐变
  #28 CApp/Chat IME 防误发 + Landing Canvas 纯色
  #29 Landing 去 Bloom / shader 光晕
```

重要：当前工作区有**其他 agent 未提交改动**（B/企业端、AGENTS、docs 等）。进入新会话先：

```bash
git status --short
git diff --stat
```

不要 reset、checkout 丢弃，也不要擅自提交非 C 端文件。

## C 端范围

页面：

```text
/c/login
/c/home
/c
/c/app
/c/orders
/c/social
/c/me
CShell / CApp 移动导航
```

主要文件：

```text
web/src/views/CHome.vue
web/src/views/CShop.vue
web/src/views/CApp.vue
web/src/views/COrders.vue
web/src/views/CSocial.vue
web/src/views/CMe.vue
web/src/components/CShell.vue
web/src/router.js
src/rag_demo/api/c_end.py
src/rag_demo/api/c_auth.py
src/rag_demo/c_end/*.py
tests/test_c_end_*.py
```

## 当前已关闭 / 已完成

```text
C 端 7 页面 CSS 渐变 = 0
Landing CSS/Canvas 渐变 = 0，#2 Codex 已关闭
60:30:10 口径锁定为 A（色彩角色）
QQ 式联系人：好友 / 店宠 / 群聊 / 会话置顶/免打扰/隐藏
后端：c_friend_request / c_group_notice / c_conversation_pref / c_friend_removed
CApp / Chat IME 合成事件回归通过
pytest 全量基线：823 passed, 6 skipped（当前工作区）
local /ready = 200，public /ready = 200
```

## 仍未完成 / 边界

```text
#5 原生中文输入法候选窗：需要真实设备人工验证，合成事件不能替代
好友申请 / 群通知目前没有外部 producer，UI 只有空态
C 端无真实支付；通知/隐私偏好只存本机
首页商品卡统一跳 /c，无单品深链
通用市集多商家聚合口径待确认
CSocial 群聊走 HTTP，不接 CApp 群 WebSocket
```

## 验收要求

```text
改动后必须 build：
  cd web && npm run build

C 端相关测试至少：
  pytest tests/test_c_end_contacts.py tests/test_c_end_social.py tests/test_c_end_agent.py -q

浏览器验收：
  320 / 390 / 768 / 1440
  CSS/Canvas gradient 扫描 = 0（若涉及 Landing/动效）
  Chrome DevTools console 无报错，关键接口 200

交付必须附：提交号、可访问版本、复验截图、测试命令与结果
```

## 不应做的事

```text
不要修改 B/企业端 sidebar、Billing、AgentDemo、离线评测页
不要修改 Chat.vue（共享企业端）以外的企业端布局
不要动 Pachat 定时任务与 Codex 验收协调（当前主协调会话负责）
不要在群里泄露 token、配对码、主人隐私
```

## 新会话第一步

```text
1. git status / git diff，确认未提交文件归属
2. 先跑 pytest C 端子集 + web build
3. 先接性能任务 task-67（见下），修完再做其他 C 端任务
4. #5 原生 IME 需要主人真实设备补证
5. 改完删除的代码/截图放 docs/e2e 与 docs/design
```

## 待接性能任务（task-67，P0）— 已完成 2026-11-14 20:30

共享任务板 id：`task-67`  
报告：`docs/e2e/c-end-performance-2026-11-14.md`

```text
提交：
  e40b704 perf(c): stabilize CShop CLS, split routes and enable gzip
  60c1bf4 fix(c): repair default buttons, tab hit areas, page titles and group avatar

结果：
  CShop CLS     1440 0.17→0.03；390 0.576→0.00
  首屏传输      1.59MB→约 104KB（gzip 生效）
  CApp Fast3G   LCP 8,004ms→870ms
  build 5.99s；pytest 823 passed / 6 skipped；C 端子集 30 passed
  截图：docs/design/c-end-perf/
  注意：main.py 加了 GZipMiddleware，本地 uvicorn 已重启（PID 17592）
```

边界：只改 C 端；共享后端压缩中间件先与本会话确认；不要动 B/企业端文件。

