# C 端浏览器验收巡检 · 2026-11-14

## 结论

C 端 6 个页面在 320 / 390 / 768 / 1440 四档宽度下**没有整页横向溢出、CSS/Canvas 渐变 = 0、console 无报错、接口全部 200**。

发现 3 个 UI 缺陷 + 1 个 320 头部折行，全部已修复并复验（工作区未提交）：P1-1 订单页默认按钮、P1-2 CApp 试听默认按钮、P2-1 移动端底栏点击区、320 头部状态折行。另有 P3-2 群头像冷色、P3-3 C 端页签标题已一并修复；P3-1 桌面 560px 手机框复核后确认为既定设计，不改。详见「问题清单」。

## 修复后复验（4 档 × 6 页）

| 宽度 | 文档宽度 | 渐变(元素+伪元素) | UA 默认控件 | console |
|---|---:|---:|---:|---|
| 320 | 320 | 0 | 0 | 无 |
| 390 | 390 | 0 | 0 | 无 |
| 768 | 768 | 0 | 0 | 无 |
| 1440 | 1440 | 0 | 0 | 无 |

修复后 `npm run build` 通过（5.89s），C 端 pytest 子集 30 passed。



## 基线与环境

```text
分支：b-end-2.0-p0
HEAD：95798b7 feat(b): unify profile query and fix enterprise UI acceptance
服务：http://127.0.0.1:8000（/ready 200；public /ready 200）
前端：web/dist 由本次 `cd web && npm run build` 构建（6.57s，✓ built）
C 端 pytest 子集：30 passed（tests/test_c_end_contacts.py / test_c_end_social.py / test_c_end_agent.py）
账号：真实 consumer 13900005678（c_13900005678，非演示账号），开发验证码 123456
```

测试工具与限制：

```text
驱动：Chrome DevTools MCP，独立隔离上下文 c-acceptance（不共享已登录的 Playwright profile）
未用 Playwright 的原因：Playwright 持久化 profile 当前是“系统管理员”会话，
  访问 /c/login 会被路由守卫送回工作台；用独立上下文可避免登出影响其他会话。
  因此本次为“纯 UI + DevTools 技术证据”模式，Playwright 侧未覆盖。
渐变扫描口径：元素 computed backgroundImage + ::before/::after 伪元素 + canvas 数量。
```

## 四档扫描结果

| 宽度 | 页面 | 文档宽度 | 整页横向溢出 | 渐变(元素/伪元素) | canvas | console |
|---|---|---:|---|---:|---:|---|
| 320 | /c/app /c/home /c /c/orders /c/social /c/me | 320 | 无 | 0 / 0 | 0 | 无 |
| 390 | 同上 6 页 | 390 | 无 | 0 / 0 | 0 | 无 |
| 768 | 同上 6 页 | 768 | 无 | 0 / 0 | 0 | 无 |
| 1440 | 同上 6 页 | 1440 | 无 | 0 / 0 | 0 | 无 |

接口证据（includePreservedRequests，252 条）：C 端 `/api/c/*` 全部 200；仅有的 404 是本次探测用的猜测路径 `/api/c/shop/products`、`/api/c/mall/products`（不存在，非页面请求）。

CSS 自定义滚动条（`*::-webkit-scrollbar` 8px，thumb = `--border-strong`）在 320/768/1440 截图中表现为右缘细线，属样式行为，不是渲染异常。

## 问题清单

### P1-1 订单页「刷新」按钮是浏览器默认样式（已修复，待提交）

- 位置：`web/src/views/COrders.vue:485`
- 实测 computed style：`background rgb(240,240,240)`、`border 1.69px outset`、`border-radius 0`、`padding 1px 6px`、`font-size 13.33px`
- 根因：按钮用 `class="ghost-btn"`，但 `COrders.vue` 只有 `.order-cancel-actions .ghost-btn` / `.after-sale-form-actions .ghost-btn` 两个 scoped 覆盖；基础 `.ghost-btn` 定义在 `CShop.vue` 的 scoped 样式里，跨组件不生效。
- 影响面：同一根因还会影响售后弹层「取消」、取消订单弹层「保留订单」两个按钮。
- 修复：在 `COrders.vue` 的 scoped 样式开头补基础 `.ghost-btn`（透明底、`--border-strong` 细边、`--radius-xs`、hover/disabled）。
- 复验：1440 `left 918 / top 111`，位于卡头右上；320 下自动换到标题下方；computed `background transparent / border 1px solid / radius 9px`。
- 证据：修复前 `docs/design/c-end-acceptance/cend-1440-orders.png`、`cend-320-orders.png`；修复后 `cend-1440-orders-fixed.png`、`cend-320-orders-fixed.png`

### P1-2 CApp 右栏「试听」按钮是浏览器默认样式（已修复，待提交）

- 位置：`web/src/views/CApp.vue:3693`（`class="c-context-link"`）
- 实测：按钮 253×18，UA 默认外观；`.c-context-link`（CApp.vue:5290）只设了 color / font-size，没有 `border:0;background:none;padding:0`
- 影响：1440 桌面上语速滑杆下方出现一条灰色默认按钮样式的横条。
- 修复：`.c-context-link` 补 `border/padding/background/font` 复位 + `:disabled`；与同文件 `.c-memory-clear` 的写法一致。
- 复验：1440 下 `background transparent / border 0 / font-size 9px`，全页 `uaButtons = 0`。
- 证据：修复前 `cend-1440-app.png`；修复后 `cend-1440-app-fixed.png`


### P2-1 移动端底部导航点击区只有 18px 宽（已修复，待提交）

- 位置：**CApp 的 `.c-mobile-nav`**（不是 CShell 的 `.c-shell-tab`，后者本来就是 `flex:1` 且实测每格 51px）
- 实测 320：6 个锚点 `width 18px / height 35px`，导航用 `justify-content: space-around` 把内容宽度的链接摊开，条目之间的空白点不到。
- 修复：`.c-mobile-nav a/button` 加 `flex: 1 1 0 / min-height: 100% / justify-content: center`。
- 复验：320 下 6 格各 `53px`（`320 / 6`），整格可点。
- 证据：`cend-320-app-nav-cells.png`

### P3-1 桌面端 5 个 C 端页面被约束成 560px 居中窄栏（确认是设计，不改）

- 位置：`c-shell-frame`；1440 实测 `width 560 / left 440 / right 440 / top 20 / height 860`
- 复核后修正判定：外层 `.c-shell-wrap` 有 `#ece8df` 底色 + 20px 内距，框本身是 `radius 26px` + `box-shadow 0 22px 60px` 的手机框，不是“内容没铺满”。
- 结论：这是 C 端「桌面展示手机框」的既定设计，与 /c/app 的满宽三栏并存属于产品选择；本次不改，只记录。

### P3-2 群聊头像用了冷色，破坏暖白气候（已修复，待提交）

- 位置：`CSocial.vue` 的 `.social-avatar.is-group`
- 原值：背景 `rgb(232,234,248)`、文字 `rgb(76,86,139)`；同页其它头像均为暖色系。
- 修复：改为暖沙 `#f2e2d2` + 暖褐 `#8a5a3b`，保留“群聊=圆角方”的形状区分。
- 证据：修复前 `cend-320-social.png`；修复后 `cend-320-social-warm.png`

### P3-3 C 端 5 个页面的浏览器标签标题是企业端名称（已修复，待提交）

- 位置：`web/src/App.vue:91-101`
- 原状：/c/home、/c、/c/orders、/c/social、/c/me 的 `document.title` 都是「千客引擎 · 新版工作台」；只有 `/c/app` 显示「千客 · C 端」。
- 修复：新增 `meta.cShell` 分支，标题为 `千客 C 端 · <页面名>`。
- 复验：`千客 C 端 · 首页 / 市集 / 订单 / 消息 / 我的`，`/c/app` 仍为 `千客 · C 端`。

### 附：320 头部状态折行（顺手修复）

- `/c/app` 头部副标题在 320 会把「在线」拆成两行（`在` / `线`）。
- 修复：说明文字包进 `.c-head-note`，`@media (max-width: 360px)` 下隐藏说明与分隔点、`white-space: nowrap`。
- 复验：320 头部状态变为单行「● 在线」，头部高度恢复。
- 证据：修复前 `cend-320-app.png`；修复后 `cend-320-app-head-fixed.png`

### 观察项（未判为缺陷）

```text
商品卡大号单字（生/运/箱）是 .product-mark 的设计占位（当前商品无 image_url），不是坏图；
  其中 .product-mark 高 36px、字号 38px，字形上下被裁掉 2-4px，保留现状待设计确认。
/c 页商品来自 store_demo（10 件），/c/home 的精选来自 /api/c/products（m_demo 5 件），
  与 handoff 里「通用市集多商家聚合口径待确认」一致，本次未改动。
```

## 未覆盖 / 边界

```text
1. 订单卡片有数据时的渲染：当前账号无已确认订单（DB 中订单只属于 buyer_1/buyer_130/buyer_112），
   订单页仅验证了空态。需要一条测试订单后再补验卡片、取消、售后弹层样式。
2. #5 原生中文输入法候选窗：本轮仍只有合成事件，未替代真实设备手测。
3. CSocial 群聊仍走 HTTP（未见群 WebSocket），与 handoff 记录一致。
4. 好友申请 / 群通知只有空态（接口 200、无数据），无外部 producer。
```

## 复验命令

```bash
cd web && npm run build
.venv/Scripts/python.exe -m pytest tests/test_c_end_contacts.py tests/test_c_end_social.py tests/test_c_end_agent.py -q
```

## 测量记录（关键数值）

```text
c-shell-frame @1440: w 560, left 440, right 440, top 20, h 860, overflow hidden
c-shell-body @768: w 559, padding 12px 14px 26px; /c/me 滚到底后最后一张卡 bottom 695 < nav top 740（内容可达）
c-prompt rail @320: overflow-x auto, scrollWidth 465 vs clientWidth 288（横向滑轨，非溢出 bug）
COrders 刷新按钮（修复前）: bg rgb(240,240,240), border 1.69px outset, radius 0
CApp 试听按钮 @1440（修复前）: 253x18 UA 默认外观
底部 Tab 锚点 @320（修复前）: width 18, height 35, left 18/71/124/178/231/285 → 修复后每格 53
群头像 .social-avatar.is-group（修复前）: bg rgb(232,234,248), color rgb(76,86,139)
document.title（修复前）: /c/app = 千客 · C 端；其余 5 页 = 千客引擎 · 新版工作台
```

## 截图

`docs/design/c-end-acceptance/` 下 25 张：320（6 页）、390（4 页）、768（3 页）、1440（6 页），另 6 张 `*-fixed.png` / `cend-320-social-warm.png` / `cend-320-app-nav-cells.png` 为修复后复验。

## 本次改动（已提交 `60c1bf4`）

```text
web/src/views/COrders.vue  补基础 .ghost-btn 样式（scoped）
web/src/views/CApp.vue     .c-context-link 按钮复位 + :disabled；
                           .c-mobile-nav 每格 flex:1 填满，扩大点击区；
                           320 头部说明文字包 .c-head-note，≤360px 隐藏
web/src/views/CSocial.vue  群头像改为暖沙 #f2e2d2 / 暖褐 #8a5a3b
web/src/App.vue            meta.cShell 路由使用「千客 C 端 · <页面名>」标题
```

未提交原因：工作区归属由主协调会话统一收口；本会话只改上述 C 端文件，未触碰 B 端、AGENTS、docs 之外的其它未提交内容。


## 附：环境坑（给后续会话）

```text
1. 必须用 .venv/Scripts/python.exe 跑 pytest；Anaconda 的 python 缺
   langgraph.checkpoint.sqlite，会让 C 端 Agent 测试假失败 12 例。
2. pytest 建议加 -p no:cacheprovider（仓库根 .pytest_cache 是旧 ACL 目录，写入报 WinError 5）。
3. Chrome DevTools MCP 截图只能写系统临时目录，需再拷贝到 docs/design。
```
