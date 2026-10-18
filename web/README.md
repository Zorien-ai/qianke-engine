# 千客引擎 · Vue 3 前端（web/）

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
dist/index.html                  1.13 kB │ gzip:  0.75 kB
dist/assets/index-*.css         95.90 kB │ gzip: 18.35 kB
dist/assets/index-*.js         824.87 kB │ gzip: 234.73 kB  # 含 three.js 0.186（WebGL 星云）
dist/assets/{setup,chat,kb}-*.png  共约 627 kB（官网场景截图）
```

> 依赖：仅新增 `three@^0.186.1`（Three.js WebGL 星云 + UnrealBloomPass）；无其它新依赖。

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
    │   ├── setup/              # 四步向导拆件
    │   │   ├── SetupStepper.vue  # 滑动 pill + 连线进度
    │   │   ├── StepUpload.vue    # 双拖拽区 / 文件列表 / 示例数据
    │   │   ├── StepFields.vue    # 字段映射 / 文档结构 / 提示
    │   │   ├── StepBuild.vue     # 构建计划 + 模式卡 + 确认弹窗 + scaleX 进度 + 离开恢复
    │   │   └── StepAsk.vue       # 示例问句 / 提问 / 来源 / 历史
    │   └── landing/
    │       └── HeroNebula.vue    # 官网 Hero：原生 Canvas 粒子星云 + 三阶段叙事
    ├── styles/main.css     # 应用外壳样式（深色 = data-theme="dark"）
    ├── styles/landing.css  # 官网样式：暗色沉浸 Hero + 暖白营销区（独立于应用主题）
    ├── assets/shots/       # 官网场景截图（setup.png / chat.png / kb.png）
    └── views/
        ├── Landing.vue     # 官网首页（/home，公开可匿名访问）
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
| `/home` | **公开官网 Landing Page**（匿名可看）：全幅暗色沉浸 Hero（Canvas 粒子星云 + 三阶段叙事）、暖白营销区（真实场景截图 + CSS 高亮、产品能力卡、私有化部署 CTA）、极简 Footer。未登录访问其它页面会先回这里 | 只读 `GET /whoami`（判断登录态，用于切换「免费体验 Demo / 进入工作台」） |
| `/` | 工作台：账号 / 企业 / 等级 / 能力清单；`/stats` 概况卡（仅 `can.stats`）；数据空间卡；快捷入口 | `GET /whoami`、`GET /stats`、`GET /api/kb/overview` |
| `/chat` | 对话：SSE 流式问答、思维链、来源列表、SQL 原文 / 查询结果、检索过程、缓存与错误态 | `POST /qa/stream` |
| `/kb` | 知识库：文档数 / 切片数 / 画像数 / 构建时间 / 数据状态条 / 文档矩阵；企业管理员可重建（轮询进度）与清空；只读账号显示 `readonly_reason` | `GET /api/kb/overview`、`POST /api/wizard/build`、`GET /api/wizard/build/{task_id}`、`POST /api/kb/clear` |
| `/staff` | 员工管理：成员列表 / 状态筛选 / 搜索 / 审核通过 / 拒绝 / 改角色 / 停用启用；邀请码卡（复制、重置）；系统管理员看企业总览 | `GET /admin/users`、`POST /admin/users/{id}/approve|reject|role|status`、`POST /admin/enterprise/invite-code/reset`、`GET /admin/enterprises` |
| `/settings` | 权限配置（仅 `can.ops`）：等级 × 能力矩阵、角色 → 默认等级、一键全开、恢复默认、人员授权只读 | `GET /admin/permissions`、`PUT /admin/permissions`、`POST /admin/permissions/reset` |
| `/setup` | 四步导入向导（仅管理员）：上传 → 确认字段 → 选择「追加更新 / 覆盖重建」构建（3s 轮询、可离开页面）→ 提问验证。侧边栏「数据导入」入口即此页；旧的 `/wizard` 页面由后端 **302 重定向**到 `/v2/#/setup` | `GET /api/wizard/plan`、`POST /api/wizard/upload`、`POST /api/wizard/upload/remove`、`GET /api/wizard/upload/{id}`、`GET /api/wizard/sample`、`POST /api/wizard/build`、`GET /api/wizard/build/{task_id}`、`GET /api/wizard/build/active`、`GET /api/wizard/examples`、`POST /api/wizard/query` |

侧边栏「数据导入」指向 `#/setup`（仅管理员可见）；旧 `/wizard` 已不提供服务端页面，由后端 302 到本页。

## 公开官网 Landing Page（`/home`）

- **匿名访问策略**：`/home` 的 `meta.public=true`，未登录可直接看；未登录访问其它页面 → 回 `/home`（不再粗暴跳 `/login`）；已登录访问 `/home` 正常展示，主按钮变「进入工作台」→ `/`。`store.doBoot()` 不再负责跳转，只记录 `authenticated`，跳转交给路由守卫。
- **应用外壳**：`route.meta.public` 的页面不渲染侧边栏 / topbar / 移动抽屉，只有 RouterView + ToastHost；未登录时 `store.account` 为空也不会报错。
- **结构（task-15 对话式叙事）**：Hero 左右 50/50——左侧文案初始隐藏，右侧 WebGL 星云播放 **约 8.2 秒「人和星云的对话」**：
  `typing 0–1.6s` 顶部「你」毛玻璃输入框 + 打字机（问题「找出最近一个月高客单的美妆女性用户」）+ 右侧圆形发送按钮（呼吸光晕）
  → `send 1.6–2.4s` 发送按钮按下/ripple，问题胶囊沿弧线（抬升+加速+blur 0→8px+scale→0.25+光尾迹）飞向星云中心
  → `process 2.4–4.4s` 胶囊没入，Bloom 爆闪 + 旋转加速 +「星云处理中 ···」跳动点
  → `cards 4.4–6s` 星云吐出 4 张真实 demo 用户画像卡（深色玻璃底 `rgba(10,9,8,.66)` + backdrop blur，错峰 90~120ms 从中心飞向四槽位；cards/final 阶段星云整体压暗 ~15% 提升可读性）
  → `return 6–7s` 带「返回」标签的发光胶囊沿弧线飞向答案槽（尾迹+沿线光点），到达后答案卡 blur(0)→blur(20px) 浮出（带「星云」角色标签 +「演示」角标）
  → `final 7–8.2s` 星云恢复呼吸，左侧文案 stagger 登场；顶部保留「你」的问题气泡（小头像 + 完整问题，形成「你问 → 星云答」结构），4 张用户卡轻移四角/opacity 0.82，答案卡保持；done 后固定不循环。
  发送/返回都走真实动效；typing 阶段仍是输入框，send 用同一条消息的克隆飞行，落地后顶部人消息气泡保持（不会同时出现两条）。发送按钮在 typing 阶段点击立即发送（跳过剩余打字）；done 后按钮变为「重播」并固定在舞台右上角留白处（不压卡片/答案），点击重播整段（重置时间轴，无需刷新）。暂停/续播、卸载清空 timer、`prefers-reduced-motion` 直接最终静态排版均保留。调试：`window.__heroStoryDebug = { phase, elapsed, cards }`、`window.__nebulaDebug`，QA 冻结钩子 `__heroFreeze/__nebulaPause`。
- **demo 数据（task-14/15）**：`GET /api/public/demo/users?limit=400`（匿名只读，demo 合成数据，不碰企业库）挂载时请求一次；`users` 映射到每颗粒子（`users[i % users.length]`）。用户卡优先取 `matched_users` 前 4 条（不足用 `users`/内置 fallback 兜底），卡片展示真实 `uid/性别/年龄/会员等级/客单价/偏好品类`；答案卡 = `query` 的 `matched` / `age_min-age_max` / `avg_amount`（floor + 千分位）；图例 = `每个光点，都是一位 demo 用户 · 共 total_profiles 位`。**接口失败静默降级**回旧文案/数字/图例（无 JS 报错）。
- **星云节点交互（task-14）**：3D 粒子每帧投影到屏幕，鼠标 14px 内最近点命中；玻璃 tooltip 显示 demo 用户 `uid / 性别 / 年龄 / 会员等级 / 客单价 / 订单数 / 偏好品类 / 城市 / 最近购买`（缺字段自动隐藏）；`cursor: pointer`；点击 pin/unpin（空白处取消、pinned 卡加强高亮），移动端 390 可 tap；命中/固定状态同步到 `__nebulaDebug.hovered/pinned`。只读、不改时间轴。
- **Hero 视觉**：背景近纯黑 `#050506`；文案纯白、无斜体；主按钮白底黑字、次按钮微光通透。**WebGL 星云只在右 50% 舞台内播放**（不是整屏背景）：`HeroNebula` 挂载在 `.l-hero-stage` 内、canvas 100% 占满右列，`mask-image`（左右 9% + 椭圆径向，`mask-composite: intersect`）让右列边缘融入黑底、无矩形边界；左半屏只有 CSS 深色渐变。搜索框/标签/结果卡均为右列内的 DOM + CSS 玻璃拟态。
- **首屏文字量**：1064 → 约 **310 字**（去掉空白字符的 textContent，含 4 张用户卡演示字段与答案卡文案）。
- **移动端（390）**：上下结构；4 张用户卡在窄屏只展示 2 张 + 「共 4 位 demo 用户」计数，答案卡在下方；发送按钮可 tap、无横向滚动；图例在窄屏隐藏避免遮挡。
- **Hero 字体**：主标题纯白 `#FFFFFF`、现代无衬线（Inter / system-ui / SF Pro / PingFang SC）、`font-weight: 800`、`letter-spacing: -0.03em`，无背景渐变/无斜体；副标题 17px、`rgba(255,255,255,.48)`；文案区占左半屏。
- **顶部导航**：品牌 + 2 个锚点（产品 / 安全）+「文档 / 登录」；Hero 上透明亮色（`is-dark`），滚出 Hero 后切浅色吸顶（`is-scrolled`，白底/深字/阴影）；锚点滚动补偿导航高度。
- **Hero 背景（task-13 终极特效）**：`three@0.186` WebGL 渲染——3D 粒子云 1600 颗（近大远小 + additive + 正弦扰动）、中心暖金泛光 sprite、`EffectComposer + RenderPass + UnrealBloomPass + OutputPass` Bloom（strength 1.25，absorb 瞬间 ×3）、~280 颗 kNN 密集网络连线（LineSegments additive）+ 缓慢自转；整体只在右 50% 舞台内。**WebGL 不可用时降级 Canvas2D**（大 radial gradient + `lighter` + 正弦粒子 + 600 条连线），不会白屏；卸载 dispose 所有 geometry/material/texture/renderer。
- **WebGL 性能**：headless SwiftShader 下 Bloom 较重，实测页面 rAF ≈ 14fps；组件内会按帧率自动降级（level1 renderScale 0.5/bloomScale 0.38，level2 0.42/0.3）。真机 GPU 预期 60fps（quality level0：renderScale 0.6、bloomScale 0.5、DPR 1）。Canvas2D 降级在 headless 实测 **60fps**。`IntersectionObserver` + `visibilitychange` 停/恢复；reduced-motion 单帧静态（仍支持悬停 tooltip）。
- **产品展示区**：媒体轨道 `1.42fr`，三张 Mac 截图在 1440 / 1000 / 390 三视口宽度完全相等（实测 849/849/849、601×3、358×3），外框加大范围弥散阴影（`0 70px 140px -52px rgba(15,18,28,.42)` 等三层）模拟真实光照；每张图只配一行标题。
- **Hero 收尾（task-13）**：已移除旧的 240px 灰白渐变块；Hero 底部保持纯黑 + 向下渐隐（`::after`），下一屏白色以干净边缘开始，整页不再有大块灰白横带。
- **右下悬浮组件**：首屏无任何客服/调试悬浮球（DOM fixed 右下小圆钮 = 0），QA 钩子只暴露到 `window` 不渲染 UI。
- **真实截图**：`web/src/assets/shots/setup.png`、`chat.png`、`kb.png`，`import.meta.glob` 引用（缺图不炸构建）；Mac 外框 + 绝对定位百分比高亮框，坐标按 1440×900 真机截图校准。
- **滚动动效**：`v-reveal` 指令 + IntersectionObserver，24px / 0.9s / `cubic-bezier(.22,.61,.36,1)`，元素可用 `--reveal-delay` 错峰；reduced-motion 全部关闭。
- 本页只读 `/whoami`，不调用写接口、不写死业务数据（截图是设计素材）。

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

- **官网截图素材随构建打包**：`web/src/assets/shots/{setup,chat,kb}.png` 会被打进 dist（三张约 0.6MB）。换图后需要重新 `npm run build`；高亮框用绝对定位百分比，坐标按当前 **1440×900** 截图校准，换图或改截图窗口尺寸后需同步微调 `Landing.vue` 里的 `highlightStyle`。
- **官网固定暖白**：`/home` 是营销页，不跟随应用内深色主题（有意如此，保证品牌观感一致）。
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
