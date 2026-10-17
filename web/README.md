# 用户画像 RAG · Vue 3 新版前端（web/）

M3 企业后台的新版界面，替换原 `src/rag_demo/api/static/` 的单页应用（旧版仍保留不动）。

- 技术栈：**Vue 3 `<script setup>` + Vite + vue-router 4（hash 模式）+ 手写 CSS**，依赖只有 `vue` / `vue-router`，没有 UI 库。
- 部署形态：`npm run build` 产出 `web/dist/`，后端 `main.py` 在 `/static` 挂载之前把 `web/dist` 挂到 **`http://127.0.0.1:8000/v2/`**（契约 F）。
- 路由用 `createWebHashHistory()`：`/v2/` 是静态挂载，没有服务端 fallback，刷新 `/v2/chat` 会 404；hash 路由下服务端只认 `/v2/index.html`。
- Vite `base: './'`：产物资源用相对路径，才能在 `/v2/` 子路径下加载。

## 快速开始

```bash
cd web
npm install        # Node 24 + npm 11（本项目不使用 pnpm）
npm run build      # 产出 web/dist（必须存在；后端按此目录挂载）
```

构建产物（示例）：

```
dist/index.html                  0.50 kB │ gzip:  0.35 kB
dist/assets/index-*.css         37.08 kB │ gzip:  7.69 kB
dist/assets/index-*.js         183.51 kB │ gzip: 66.64 kB
```

`dist/` 与 `node_modules/` 已在仓库根 `.gitignore` 里（`dist/` 规则 + `web/node_modules/`），不会提交。

本地开发（可选）：

```bash
npm run dev        # http://127.0.0.1:5173；vite.config.js 里已把
                   # /whoami /qa /stats /admin /api /auth /login 代理到 8000
```

## 目录结构

```
web/
├── index.html
├── vite.config.js          # base './'、outDir 'dist'、dev 代理
├── package.json
└── src/
    ├── main.js
    ├── App.vue             # 布局外壳：侧边栏 / 顶栏 / 路由出口 / toast
    ├── router.js           # hash 路由 + 登录守卫 + 能力守卫
    ├── api.js              # 统一 fetch：same-origin Cookie、401 → /login、错误中文 detail
    ├── store.js            # /whoami 会话与能力（唯一真源）、toast、logout
    ├── theme.js            # 深浅色（跟随系统 + localStorage）
    ├── lib/markdown.js     # 无依赖 Markdown 渲染（移植自旧版 static/markdown.js）
    ├── components/
    │   ├── ToastHost.vue
    │   └── ConfirmButton.vue   # 二次确认按钮（点两次才执行）
    ├── styles/main.css     # 设计变量 + 全部样式（深色 = data-theme="dark"）
    └── views/
        ├── Dashboard.vue   # 工作台
        ├── Chat.vue        # 对话（SSE 流式）
        ├── Kb.vue          # 知识库
        ├── Staff.vue       # 员工管理
        └── Settings.vue    # 权限配置
```

## 页面与路由

| 路由（`/v2/#...`） | 页面 | 关键接口 |
|---|---|---|
| `/` | 工作台：账号 / 企业 / 等级 / 能力清单；`/stats` 概况卡（仅 `can.stats`）；数据空间卡；快捷入口 | `GET /whoami`、`GET /stats`、`GET /api/kb/overview` |
| `/chat` | 对话：SSE 流式问答、思维链、来源列表、SQL 原文 / 查询结果、检索过程、缓存与错误态 | `POST /qa/stream` |
| `/kb` | 知识库：文档数 / 切片数 / 画像数 / 构建时间 / 索引新鲜度条 / 文档矩阵；企业管理员可重建（轮询进度）与清空；只读账号显示 `readonly_reason` | `GET /api/kb/overview`、`POST /api/wizard/build`、`GET /api/wizard/build/{task_id}`、`POST /api/kb/clear` |
| `/staff` | 员工管理：成员列表 / 状态筛选 / 搜索 / 审核通过 / 拒绝 / 改角色 / 停用启用；邀请码卡（复制、重置）；系统管理员看企业总览 | `GET /admin/users`、`POST /admin/users/{id}/approve|reject|role|status`、`POST /admin/enterprise/invite-code/reset`、`GET /admin/enterprises` |
| `/settings` | 权限配置（仅 `can.ops`）：等级 × 能力矩阵、角色 → 默认等级、一键全开、恢复默认、人员授权只读 | `GET /admin/permissions`、`PUT /admin/permissions`、`POST /admin/permissions/reset` |

侧边栏底部「数据导入」是独立向导页 `/wizard`（整页跳转，不走 SPA 路由）。

## 能力显隐全部来自 `/whoami.can`

| `can` 键 | 控制点 |
|---|---|
| `ask` | 能否提问（提问按钮 / 输入框） |
| `sources` | 来源列表；同时决定正文里的 `[来源N]` 是否渲染（无权限时删除该标记） |
| `topk` | 「返回用户数」输入（范围取 `whoami.topk_range`，服务端会再次夹取） |
| `internals` | 来源原文 / 精排分数 / 检索式 / trace 明细 |
| `trace_flow` | 「融合与精排」链路汇总 |
| `sql` | SQL 原文与执行报错（查询结果行是所有能提问的账号都能看到的业务事实） |
| `stats` | 工作台 `/stats` 概况卡与会员等级分布 |
| `ops` | 权限配置页入口 |
| `tenant` | 企业管理员身份自带（不由等级授予） |

员工管理的入口在 `store.isManager()`（`is_system_admin || is_enterprise_admin`）上判断；后端仍会再校验一次。

## 硬性约束（与 `_contract_m3.md` 一致）

1. **前端绝不传 `dataset` / `tenant_id` 选库**：重建只传 `upload_id + fields`，清空只传 `confirm`（与后端推导出的 dataset 字面值比对）。读哪个库永远由登录账号推导。
2. **不写死业务事实**：文档数、切片数、构建时间、成员数、邀请码、等级、能力全部运行时从接口取；示例问句只写"问法"，不写具体取值。
3. 不修改后端 py、既有 `src/rag_demo/api/static/`、`tests/**`；不做 git 提交。

## 构建自检

```bash
cd web
npm install     # 成功：added 36 packages
npm run build   # 成功：vite v6.4.4，37 modules transformed，无报错
```

另外用无头 Chrome + CDP 做过一次真实运行冒烟（本地临时静态代理 `/v2` 同源接口到 8000，账号 `admin`）：

- 未登录访问 → `/whoami.authenticated=false` → 跳 `/login`；登录后五个页面均正常渲染，控制台 0 报错；
- 对话页真实提问走通 `POST /qa/stream`：`meta`（route=rag、4 条 sources、trace）、`delta` 拼接、Markdown 渲染、来源卡片、检索过程均正常；缓存命中有提示；
- 深色主题、移动端（390px）抽屉侧边栏截图正常。

后端重启并挂载 `/v2` 之后，又用真实部署地址逐页验证过：

- `http://127.0.0.1:8000/v2/` 正常加载最新 dist（`/v2/assets/*` 200）；
- 知识库页拿到真实 `/api/kb/overview`：demo 数据集「已构建 / 索引新鲜」、文档 6 / 切片 36 / 画像 8110、`readonly_reason` 正确显示「演示数据集是评测基准，只读」；
- 员工管理页拿到真实 `/admin/users`（12 个账号）与 `/admin/enterprises`（11 家企业、企业总览表含邀请码 / 重置按钮）；
- 权限配置页拿到真实 `/admin/permissions`（4 等级 × 9 能力矩阵、角色默认等级）；
- 唯一控制台报错是 `/favicon.ico` 404，已改为内联 SVG favicon。

## 已知缺口 / 限制

- **依赖 M3 新后端端点**：`/api/kb/overview`、`/api/kb/clear`、`/admin/enterprises`、`/admin/enterprise/invite-code/reset` 由后端任务实现，需重启 8000 后才可用；未就绪时本页给出「暂不可用 / Not Found」的人话提示而不是白屏（知识库页、企业总览已做降级）。
- **权限页的人员授权**：只读展示 `config.user_levels`，编辑（grant / revoke）留给后续迭代；矩阵、角色默认等级、一键全开、恢复默认已实现。
- **对话历史不持久化**：刷新即丢；「新对话」会清空当前上下文（单轮问答，无多轮记忆）。
- **SSE 边界**：已处理 `replace`（后置审查整体覆盖正文）、`reasoning`、缓存命中提示；未接 mermaid 图表渲染（旧版有，新版代码块原样展示），也不做断线自动重连（可手动重试）。
- **构建进度是后端进程内状态**：后端重启后 `task_id` 失效，页面会提示回到向导重试；不传 `dataset`，因此重建目标永远是当前账号的数据空间。
- **旧版入口未改**：旧 SPA 的侧边栏没有加 `/v2` 链接（属于原生前端任务的写作用域），需要直接访问 URL。
- 未做 i18n、无障碍的完整键盘焦点陷阱；对话长列表未做虚拟滚动（当前量级不需要）。

## 与旧版的关系

- `/`、`/static/*`、`/wizard` 仍是旧版；`/v2/` 只读 `web/dist`，两套互不影响。
- 新版接口调用与旧版 `static/app.js` 的 `apiFetch`、SSE 事件处理、能力显隐口径保持一致，便于对照排查。
