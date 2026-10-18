# 用户画像 RAG · Vue 3 新版前端（web/）

M3 企业后台的新版界面，也是**当前默认主入口**：`GET /` 直接 302 到 `/v2/`
（登录页之后的跳转全部落在 Vue 路由内；`web/dist` 缺失时后端才兜底回旧单页）。
旧版 `src/rag_demo/api/static/` 单页应用仍作为代码保留，但已不再可达：
「知识库管理」`#/kb` 冻结并跳转本项目的 `/v2/#/kb`；四步导入向导从老的 `/wizard` 页面
重写为本项目的 `/v2/#/setup`（后端 `/wizard` 现在 302 到这里）。后续全量迁移完成后旧 SPA 再整体删除。

- 技术栈：**Vue 3 `<script setup>` + Vite + vue-router 4（hash 模式）+ 手写 CSS**，依赖只有 `vue` / `vue-router`，没有 UI 库。
- 部署形态：`npm run build` 产出 `web/dist/`，后端 `main.py` 在 `/static` 挂载之前把 `web/dist` 挂到 **`http://127.0.0.1:8000/v2/`**。
- 路由用 `createWebHashHistory()`：`/v2/` 是静态挂载，没有服务端 fallback，刷新 `/v2/chat` 会 404；hash 路由下服务端只认 `/v2/index.html`。
- Vite `base: './'`：产物资源用相对路径，才能在 `/v2/` 子路径下加载。

## 构建（改完前端必须执行）

`web/dist/` **不入库**（仓库根 `.gitignore` 里的 `web/dist/`），换机器/重新拉代码后必须本地构建一次，
后端才会挂载 `/v2`（`dist` 不存在时后端会跳过挂载，`/v2/` 404 是预期现象）。

```bash
cd web
npm install
npm run build
```

一条命令自检（构建通过 = 前端可交付的最小验证）：

```bash
cd web && npm install && npm run build
```

构建完成后**不需要重启后端**：`/v2` 是静态目录挂载，实时读盘；浏览器强刷即可（静态文件有缓存时按 Ctrl+F5）。

## 本地开发（可选）

```bash
cd web
npm run dev        # http://127.0.0.1:5173；vite.config.js 已把
                   # /whoami /qa /stats /admin /api /auth /login 代理到 8000
```

## 构建产物（示例）

```
dist/index.html                  1.13 kB │ gzip:  0.74 kB
dist/assets/index-*.css         65.39 kB │ gzip: 12.14 kB
dist/assets/index-*.js         240.45 kB │ gzip: 85.54 kB
```

`web/dist/` 与 `web/node_modules/` 都在仓库根 `.gitignore` 里，不会提交。

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
    ├── lib/docTemplate.js  # 规则文档模板文本 + Blob 下载（搬自旧版 wizard.js）
    ├── lib/wizardCache.js  # 向导 localStorage key + 数据状态/技术词降维文案
    ├── components/
    │   ├── ToastHost.vue
    │   ├── ConfirmButton.vue   # 二次确认按钮（点两次才执行）
    │   └── setup/              # 四步向导拆件
    │       ├── SetupStepper.vue  # 滑动 pill + 连线进度
    │       ├── StepUpload.vue    # 双拖拽区 / 文件列表 / 示例数据
    │       ├── StepFields.vue    # 字段映射 / 文档结构 / 提示
    │       ├── StepBuild.vue     # 构建计划 + 模式卡 + 确认弹窗 + scaleX 进度 + 离开恢复
    │       └── StepAsk.vue       # 示例问句 / 提问 / 来源 / 历史
    ├── styles/main.css     # 设计变量 + 全部样式（深色 = data-theme="dark"）
    └── views/
        ├── Dashboard.vue   # 工作台
        ├── Chat.vue        # 对话（SSE 流式）
        ├── Kb.vue          # 知识库
        ├── Staff.vue       # 员工管理
        ├── Settings.vue    # 权限配置
        └── Setup.vue       # 四步导入向导（/setup）
```

## 页面与路由

| 路由（`/v2/#...`） | 页面 | 关键接口 |
|---|---|---|
| `/` | 工作台：账号 / 企业 / 等级 / 能力清单；`/stats` 概况卡（仅 `can.stats`）；数据空间卡；快捷入口 | `GET /whoami`、`GET /stats`、`GET /api/kb/overview` |
| `/chat` | 对话：SSE 流式问答、思维链、来源列表、SQL 原文 / 查询结果、检索过程、缓存与错误态 | `POST /qa/stream` |
| `/kb` | 知识库：文档数 / 切片数 / 画像数 / 构建时间 / 数据状态条 / 文档矩阵；企业管理员可重建（轮询进度）与清空；只读账号显示 `readonly_reason` | `GET /api/kb/overview`、`POST /api/wizard/build`、`GET /api/wizard/build/{task_id}`、`POST /api/kb/clear` |
| `/staff` | 员工管理：成员列表 / 状态筛选 / 搜索 / 审核通过 / 拒绝 / 改角色 / 停用启用；邀请码卡（复制、重置）；系统管理员看企业总览 | `GET /admin/users`、`POST /admin/users/{id}/approve|reject|role|status`、`POST /admin/enterprise/invite-code/reset`、`GET /admin/enterprises` |
| `/settings` | 权限配置（仅 `can.ops`）：等级 × 能力矩阵、角色 → 默认等级、一键全开、恢复默认、人员授权只读 | `GET /admin/permissions`、`PUT /admin/permissions`、`POST /admin/permissions/reset` |
| `/setup` | 四步导入向导（仅管理员）：上传 → 确认字段 → 选择「追加更新 / 覆盖重建」构建（3s 轮询、可离开页面）→ 提问验证。侧边栏「数据导入」入口即此页；旧的 `/wizard` 页面由后端 **302 重定向**到 `/v2/#/setup` | `GET /api/wizard/plan`、`POST /api/wizard/upload`、`POST /api/wizard/upload/remove`、`GET /api/wizard/upload/{id}`、`GET /api/wizard/sample`、`POST /api/wizard/build`、`GET /api/wizard/build/{task_id}`、`GET /api/wizard/build/active`、`GET /api/wizard/examples`、`POST /api/wizard/query` |

侧边栏「数据导入」指向 `#/setup`（仅管理员可见）；旧 `/wizard` 已不提供服务端页面，由后端 302 到本页。

## 四步导入向导（`/setup`）

| 步骤 | 做什么 | 用到的接口 / 字段 |
|---|---|---|
| 1 上传 | 交易 CSV（.csv/.txt）与规则文档（.md）两块拖拽区、多文件追加、逐条移除、示例数据一键填满、下载文档模板；`csv_files` / `md_files` / `summary` / `warnings` / `rejected` 全部来自服务端 state；`localStorage[v2-wizard-upload-id]` 记住批次，刷新后 `GET /api/wizard/upload/{id}` 恢复（404/403 静默回空态） | `POST /api/wizard/upload`（multipart `files` + 可选 `upload_id`）、`GET /api/wizard/sample`、`POST /api/wizard/upload/remove`、`GET /api/wizard/upload/{upload_id}` |
| 2 确认字段 | `fields[]`（key/label/required/hint/detected/column/from_file/options）渲染成映射表；关键字段（user_id）未映射时禁用下一步并说明后果；`warnings`、`docs[]`（name/h1/h2/h3/est_chunks/chars）、summary 卡片；会员等级来源当场提示 | 数据来自第 1 步返回的 `state.fields` / `docs` / `warnings` / `summary` |
| 3 构建 | 进入本步先 `GET /api/wizard/plan?upload_id=`：两张模式卡——**「追加更新」默认选中**（展示本次新增 CSV / 文档数、已有 N 个用户不受影响；`can_incremental=false` 时禁用并显示 `incremental_block_reason`）、**「覆盖重建」**（展示现有规模 + 上次全量用时）。选覆盖重建点开始 → **二次确认弹窗**（现有画像/文档规模、上次全量用时、建议追加更新、构建期间可离开页面）。确认后 `POST /api/wizard/build` 只传 `{upload_id, fields, mode}`（**绝不传 dataset / simulate_failure**）；**3000ms** 轮询，总进度与五步进度条都用 `transform: scaleX()` + CSS transition（GPU，无 rAF 逐帧改 width）；done 展示后端 `note` + `result`（full：profiles/rows/index_total；incremental：profiles_new/profiles_updated/docs_new/docs_updated/rows_incremental）；failed 显示 `error` 可重试；404 提示「任务过期，请重新构建」 | `GET /api/wizard/plan`、`POST /api/wizard/build`、`GET /api/wizard/build/{task_id}` |
| 3.1 离开恢复 | `task_id` 存 `localStorage[v2-wizard-build-task-id]`；回到 `/setup` 先 `GET /api/wizard/build/active`：running → 自动进第 3 步继续轮询；刚完成 → 展示结果并解锁第 4 步；`active` 未就绪时用 localStorage 的 task_id 兜底查询；过期 id（404）自动清掉；组件卸载清定时器 | `GET /api/wizard/build/active`、`GET /api/wizard/build/{task_id}` |
| 4 提问 | `GET /api/wizard/examples?upload_id=` 动态示例问句；`POST /api/wizard/query` 只传 `{question, upload_id}`；Markdown 正文 + `[来源N]` 可点击跳来源、sources 卡片、route/busy/cached/elapsed_ms 元信息；「去完整对话页 → /chat」；提问记录仅内存保留最近 5 条 | `GET /api/wizard/examples`、`POST /api/wizard/query` |

视觉/动效：浅色渐变毛玻璃 hero（深色模式同样成立）、步骤条滑动 pill + 连线进度（文字有不透明底色，连线不会穿透文字）、上下步方向相反的 `<Transition>`（≈160~240ms 弹性曲线）、拖拽区 hover 内发光 / dragover 流光 / drop 脉冲 / 键盘 Enter·Space 选择、构建进度渐变光带 + 五步状态配色（全部走 `transform: scaleX()` GPU 动画）、覆盖重建二次确认弹窗、全部尊重 `prefers-reduced-motion`。

文案降维（全站）：技术词 `索引新鲜度` 统一显示为 **数据状态**；`fresh` → 「已就绪，可随时提问」、`stale` → 「数据有更新，请重新构建」、`unknown` → 「尚未构建，建议先构建一次」；技术值（fresh/stale/unknown）只放在元素的 `title` 里。涉及 `Kb.vue` / `Dashboard.vue` / `StepBuild.vue` / `StepAsk.vue`（构建完成 note 里的同类词也会被降维）。

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

## 硬性约束

1. **前端绝不传 `dataset` / `tenant_id` 选库**：重建只传 `upload_id + fields`，清空只传 `confirm`（与后端推导出的 dataset 字面值比对），向导构建只传 `{upload_id, fields, mode}`、向导提问只传 `{question, upload_id}`。读哪个库永远由登录账号推导。
2. **不写死业务事实**：文档数、切片数、构建时间、成员数、邀请码、等级、能力全部运行时从接口取；示例问句只写"问法"，不写具体取值（向导的示例问句由 `/api/wizard/examples` 按上传数据的真实取值生成）。
3. 后端接口契约见 `docs/接口文档.md` §10（企业后台）与 §9（导入向导）。

## 构建自检

```bash
cd web && npm install && npm run build
```

预期：`vite` 构建成功、0 报错，`web/dist/` 下生成 `index.html` + `assets/*.js|css`。
构建产物体积示例见上；不通过就不要提交（后端 `/v2` 会挂到旧产物上，表现为「改了没生效」）。

## 已知缺口 / 限制

- **依赖第五轮新后端接口**：`GET /api/wizard/plan` 与 `GET /api/wizard/build/active` 由后端任务实现。未就绪时本页自动降级：读不到 plan → 只允许「覆盖重建」并给出提示；`active` 不可用 → 用 localStorage 的 task_id 兜底恢复；两者都不可用时回到第 1 步（上传批次仍会恢复）。
- **分块大小 / 重叠没有配置项**：后端暂未提供对应接口，本页不做假配置（切分参数仍在服务端默认值里）。真要可配置，应先加读写接口，再在向导第 2 步补一块表单。
- **权限页的人员授权**：只读展示 `config.user_levels`，编辑（grant / revoke）留给下一迭代；矩阵、角色默认等级、一键全开、恢复默认已实现。
- **对话历史不持久化**：刷新即丢；「新对话」会清空当前上下文（单轮问答，无多轮记忆）。向导第 4 步的提问记录也只在内存里保留最近 5 条。
- **SSE 边界**：已处理 `replace`（后置审查整体覆盖正文）、`reasoning`、缓存命中提示；未接 mermaid 图表渲染（旧版有，新版代码块原样展示），也不做断线自动重连（可手动重试）。
- **构建进度是后端进程内状态**：后端重启后 `task_id` 失效，页面会提示「任务过期，请重新构建」并清掉本地 task_id；不传 `dataset`，因此构建/重建目标永远是当前账号的数据空间。
- **构建与提问的写/读路径**：自检时不在 8000 上触发真实构建（写库红线）；第 3 步的 plan / 模式卡 / 二次确认 / scaleX 进度 / 离开恢复（active + localStorage 兜底 + 过期清理）/ 增量完成结果，均用拦截 `fetch` 的契约假响应做过渲染验证（0 控制台报错）；真实构建 → 提问由 Lead 用临时企业账号做 E2E 验证。第 1/2 步、文案降维、深色、移动端已真机验证。
- 未做 i18n、无障碍的完整键盘焦点陷阱；对话长列表未做虚拟滚动（当前量级不需要）。

## 与旧版的关系

- `/`、`/static/*` 仍是旧版；`#/staff`、`#/settings` 旧视图保留，但新版只在 `/v2/` 维护。
- **旧版「知识库管理」已冻结**：入口移除，书签/手敲旧 `#/kb` 会跳转到 `/v2/#/kb`。
- **导入向导已迁移**：新版 `/v2/#/setup` 替代旧 `/static/wizard` 的四步页面；旧 `/wizard` 由后端 302 到 `/v2/#/setup`（Vue 不处理该路径），旧版侧边栏入口也已指向 `/v2/#/setup`。向导的字段识别、构建、问答接口原样复用，未改后端。
- 新版接口调用与旧版 `static/app.js`、`static/wizard.js` 的口径保持一致，便于对照排查。
