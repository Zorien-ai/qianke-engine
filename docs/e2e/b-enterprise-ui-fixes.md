# B / 企业端 UI 验收整改记录

日期：2026-11-14  
分支：`b-end-2.0-p0`  
基线：`0f6c0ac`（handoff 时的提交）；工作区包含未提交的 B 端画像查询改动，本次在其上继续整改，未 reset / checkout 丢弃。  
范围：Codex UI 验收 #1 / #3 / #4；未改 C 端功能、Pachat 定时任务与 Codex 协调逻辑。

## #1 CSS 渐变与占位

**改动**

- 删除 B/企业端所有 CSS 渐变（`web/src/styles/main.css`、`web/src/b-workbench.css`、`AgentDemo.vue`、`Billing.vue`、`Eval.vue`、`ChatHistoryPanel.vue`、`ProfileWall.vue`、`DocumentReader.vue`）。
- `--grad` 改为纯色；企业外壳背景改 `var(--bg)`；骨架屏、商品缺图占位、报告加载骨架改纯色。
- 保留阴影（含侧栏柔和阴影），但不再使用任何 `linear-gradient` / `radial-gradient` / `conic-gradient`。

**验证**

```text
web/src 源码 page 扫描：linear/radial/conic gradient = 0
web/dist 产物 CSS 扫描：linear/radial/conic gradient = 0
```

## #3 桌面侧栏浮动规范

**B 端（/v2/b.html）**

- 实测 1440：`x=16, y=84, width=72, height=800, radius=20px`；hover → `240px`，文字 opacity 1。
- 组间距 32px、组标题 11px 大写灰字、底部用户区固定。

**企业端（/v2/）**

- 从“贴左 248px / 圆角 0 / 无展开”改为浮动面板：
  - `x=16, y=16, width=72, height=968, radius=20px`；
  - hover / focus-within → `240px`，文字延迟 80ms 淡入；
  - 导航按「工作台 / 管理 / 平台」分组，组间距 32px，组标题 11px 大写灰字；
  - 底部固定用户区（头像 + 账号 + 企业）；
  - 桌面端隐藏 topbar 重复账号 chip，移动端保留。
- 移动端抽屉：宽 280px；导航区独立滚动，底部用户区固定；Esc 关闭并回焦菜单按钮。

**验证**

```text
1440 collapsed: {x:16, y:16, w:72, radius:20px}
1440 hover:     {w:240, labels opacity:1}
390 drawer:     {w:280, user bottom:830 < 844}
390 Esc:        drawerOpen=false, activeElement=menu-btn
```

## #4 窄屏溢出

| 页面 | 320 | 390 | 768 | 1440 |
|---|---:|---:|---:|---:|
| 工作台 `/` | 310/310 | 380/380 | 758/758 | 1430/1430 |
| 智能助理 `/agent` | 320/320 | 390/390 | 768/768 | 1430/1430 |
| Token 账单 `/billing` | 320/320 | 390/390 | 768/768 | 1430/1430 |
| 离线评测 `/eval` | 310/310 | 390/390 | 768/768 | 1430/1430 |

（`scrollWidth / clientWidth`，均无横向溢出；滚动条占宽时两者相等。）

- 顶栏 ≤640：收紧间距，只显示当前主题/语言选项；≤420 隐藏主题/语言切换；退出按钮 390 下 `right=378 < 390`。
- 离线评测：`eval-template` 改为 `width:100%; max-width:100%; box-sizing:border-box; overflow:auto`；390 下容器 287px，内部 JSON 435px 横向滚动，页面不撑开。
- B 端 `/v2/b.html`：320/390/768 移动导航无溢出；1440 侧栏 72→240 浮动。

## 构建与测试

```text
cd web && npm run build
✓ built in 5.85s

pytest tests/test_b_workbench_api.py tests/test_b_chat_profile.py \
  tests/test_b_profile_query_api.py tests/test_b_user_pool.py \
  tests/test_mvp_merchant_scope.py tests/test_tenant_isolation_pg.py
50 passed, 1 skipped
```

全量 pytest 此前基线：`823 passed, 6 skipped`；本次仅前端 UI/交互改动，未触碰后端逻辑。

## 截图

- `docs/design/b-end-fix-sidebar-collapsed.png`
- `docs/design/b-end-fix-sidebar-hover.png`
- `docs/design/b-end-fix-enterprise-1440.png`
- `docs/design/b-end-fix-enterprise-390.png`
- `docs/design/b-end-fix-agent-390.png`
- `docs/design/b-end-fix-agent-320.png`
- `docs/design/b-end-fix-billing-390.png`
- `docs/design/b-end-fix-eval-390.png`
- `docs/design/b-end-fix-drawer-390.png`
- `docs/design/b-end-fix-b-1440.png`
- `docs/design/b-end-fix-b-390.png`
- `docs/design/b-end-fix-b-sidebar-hover.png`

## 已知说明

- 企业端导航按「工作台 / 管理 / 平台」分组；管理员看到的“平台”组会随权限出现。
- 桌面端账号信息移入侧栏底部，topbar 账号 chip 在 ≥901 隐藏；移动端仍在 topbar 显示。
- 未改 C 端页面与 CApp/CShop/CSocial/CMe。
- 交付提交号见本次 commit；本地可访问版本 `http://127.0.0.1:8000/v2/` 与 `/v2/b.html`。
