# Qianke Engine Architecture Handbook · 现有 Docs 模块检查报告

> 状态：现状检查完成，未修改官网代码  
> 日期：2026-11-23  
> 范围：官网 Docs 入口、现有文档路由、Markdown 渲染、架构图、已有技术文档、构建与发布方式

> **后续状态（2026-11-23）**：本报告记录实施前现状；Architecture Handbook 已用 VitePress 落地并挂载到 `/docs`，Swagger 迁到 `/api/docs`。实施结果见 [handbook README](../README.md) 与 `docs-site/README.md`。

## 1. 结论

官网当前**没有公开的 Docs 模块**。

```text
GET /docs                         -> 404（公网当前配置）
/v2/#/home 的“文档”按钮           -> GitHub 快速开始弹窗
/v2/#/kb/docs                     -> 登录后的租户知识库管理，不是公开手册
```

因此不能在当前 Docs 上“继续加文章”。Architecture Handbook 需要一个**新的公开文档入口**。

同时，项目已有可复用资产：

```text
web/src/lib/markdown.js           轻量 Markdown 渲染
DocumentReader.vue                原文阅读器（内部知识库）
docs/agent.md                     Agent 实现说明
docs/agent-design-current-vs-target.md
docs/architecture-diagrams.md     Mermaid/架构图源
docs/数据模型.md / 接口文档.md    系统设计资料
docs/product/...                  产品与运行机制资料
```

但这些都是**内部工程文档**，不是面向官网读者的 Handbook 信息架构。

## 2. 官网现状

### 2.1 路由

`web/src/router.js` 当前公开路由只有：

```text
/home       官网首页
```

没有：

```text
/docs
/docs/:section
/docs/:section/:slug
```

`Landing.vue` 的文档入口：

```text
桌面导航“文档”：@click.prevent 打开 GitHub 弹窗
Footer“产品文档”：<a href="/docs">，直接请求 /docs
```

实测：

```text
GET /docs -> 404
```

结论：

```text
官网没有文档站
“文档”文案存在，但没有真实文档页面承接
Footer 已存在死链
```

### 2.2 内部知识库不等于官网 Docs

`/v2/#/kb/docs` 的实现：

```text
KbDocs.vue
DocumentReader.vue
GET /api/kb/documents
GET /api/kb/docs/{doc_id}/raw
```

特点：

```text
需要登录
按租户 dataset 隔离
展示的是客户上传/仓库 RAG 文档的切片与原文
偏“知识库管理”
```

不能直接作为公开 Handbook 使用：

```text
1. 鉴权模型不同
2. 数据是租户私有内容，不是公开知识
3. 没有分类、TOC、搜索、版本、状态
4. 没有面向开发者的导航
```

## 3. Markdown 渲染能力

### 3.1 已有能力

`web/src/lib/markdown.js` 是自研轻量渲染器：

```text
标题 # ~ ######
无序/有序列表、嵌套列表
表格
代码围栏
引用
粗体/斜体/删除线
行内代码
http(s) 链接
简单 Mermaid 流程树解析
[来源N] 引用钩子
```

安全：

```text
先 HTML 转义，再结构替换
不直通原始 HTML
链接只允许 http(s)
```

### 3.2 缺口

不能直接支撑 Architecture Handbook：

| 能力 | 当前 | Handbook 需要 |
|---|---|---|
| 标题锚点 | 无 id | 每级标题可链接 |
| 目录 TOC | 无 | 右侧自动目录 |
| 语法高亮 | 无 | Python/SQL/JSON/Bash/Mermaid |
| 代码复制 | 无 | 每块复制 |
| Frontmatter | 无 | 状态/版本/分类/更新时间 |
| 图片 | 渲染器未定义 | 架构图/截图 |
| 完整 Mermaid | 仅简单流程树 | flowchart/sequence/graph |
| 搜索 | 无 | 全站搜索 |
| 上一篇/下一篇 | 无 | 阅读连续性 |
| 版本/状态徽章 | 无 | 已实现/开发中/已设计/规划中 |
| 外链策略 | 只有 http(s) | 内外链、锚点、相对链接 |
| 链接校验 | 无 | 构建期死链检查 |

### 3.3 结论

```text
可以复用它的“安全转义”思想，
但不应把 DocumentReader 直接改造成公开文档站。
```

公开 Handbook 需要独立的文档渲染/构建体系。

## 4. 现有文档资产

### 4.1 可以直接作为来源

| 文件 | 可贡献章节 |
|---|---|
| `docs/agent.md` | Agent Runtime、State、Tool、Retry、Eval、限制 |
| `docs/agent-design-current-vs-target.md` | 当前/目标架构、三端 Graph |
| `docs/architecture-diagrams.md` | 系统分层、检索、数据流 |
| `docs/数据模型.md` | 多租户、表结构、数据平面 |
| `docs/接口文档.md` | API、认证、错误、响应 |
| `docs/评测落地方案.md` | Evaluation、线上观测 |
| `docs/decisions/` | ADR 与关键架构决策 |
| `docs/product/` | Agent Memory、身份、权限、业务规则 |

### 4.2 不能直接发布的原因

```text
1. 面向内部工程，不是学习型文档
2. 部分内容已过期：architecture-diagrams.md 自己标注“部分内容落后”
3. 没有统一 frontmatter / 状态 / 版本
4. 章节结构不统一
5. 与当前代码存在漂移风险
6. 没有外部权威引用规范
```

所以 Handbook 不是把 `docs/` 直接搬到官网，而是：

```text
以现有代码与文档为事实来源
+ 按 Handbook 模板重写
+ 标注实现状态
+ 建立交叉链接
```

## 5. 架构图现状

当前有：

```text
docs/architecture-diagrams.md          Mermaid 源码
docs/architecture-diagrams.html        静态渲染
docs/design/architecture-agent-runtime.html
docs/design/architecture-agent-memory.html
docs/assets/architecture-*.png
```

问题：

```text
1. 图形分散，命名不统一
2. Mermaid 与 HTML 两套来源，容易不一致
3. 现有前端渲染器只支持简单流程树
4. 没有图源与正文的校验
5. 没有为每张图提供 alt/说明
```

Handbook 需要：

```text
每张图有唯一图号、标题、源文件、正文引用
Mermaid 作为主源
构建期渲染为 SVG
正文图与文字同版本
```

## 6. 路由与发布方式

当前部署：

```text
FastAPI -> /v2 -> web/dist 静态挂载
```

`/docs` 没有挂载点。

另外：

```text
FastAPI 自身 Swagger 文档默认使用 /docs
公网当前 RAG_ENABLE_API_DOCS=0，因此 /docs 是 404
```

所以建设公开 `/docs` 前必须处理：

```text
1. FastAPI Swagger 的 /docs 冲突
2. 将 OpenAPI 文档迁移到 /api/docs 或 /api/openapi.json
3. 给 Handbook 建立独立静态挂载
4. 保持 /v2 应用路由不受影响
```

这是技术方案中的 P0 决策。

## 7. 当前测试与质量门禁

没有 Docs 专项测试：

```text
没有 /docs 路由测试
没有文档链接检查
没有 TOC/搜索测试
没有 Mermaid 渲染测试
没有移动端文档导航测试
没有文档 SEO/可访问性测试
```

现有测试只覆盖业务 API、知识库、前端核心功能。

## 8. 现状问题分级

### P0

```text
1. 官网没有公开文档模块，/docs 404
2. 没有公开文档路由和静态内容
3. FastAPI /docs 与官网 /docs 冲突尚未解决
4. 现有 Markdown 渲染器不足以支撑 Handbook
```

### P1

```text
1. 无分类/侧边栏/TOC/搜索/上下一篇
2. 无 frontmatter 状态/版本/更新时间
3. 无完整 Mermaid/代码高亮/复制
4. 现有 docs/ 内容过期且无统一规范
5. 无文档构建、死链、可访问性门禁
```

### P2

```text
1. 架构图源分散
2. 文档命名与 URL 不规范
3. 无内容负责人/审核流程
4. 无文档版本与发布记录
```

## 9. 结论与下一步

```text
官网 Docs 目前是“入口有文案、底层无系统”。
Architecture Handbook 应作为独立公开文档站建设，
不能复用内部租户知识库阅读器。
```

下一步输出：

```text
1. Handbook 信息架构与完整目录
2. 统一内容规范与状态模型
3. 第一阶段 Agent Architecture 详细规划
4. 第一篇完整文章
5. Docs 技术实施方案与验收标准
```
