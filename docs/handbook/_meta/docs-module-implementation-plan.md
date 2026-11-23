# Qianke Engine Architecture Handbook · Docs 模块实施方案

> 状态：评审稿，等待批准，不修改代码  
> 日期：2026-11-23  
> 目标：在官网建立公开、可搜索、可维护的 Architecture Handbook，而不是复用内部知识库阅读器

## 1. 现状结论

```text
官网没有公开 Docs 模块
GET /docs -> 404
/v2/#/home 的文档按钮 -> GitHub 弹窗
/v2/#/kb/docs -> 登录后的租户知识库管理
```

现有 Markdown 渲染器：

```text
支持标题/列表/表格/代码/引用/链接/简单流程树
不支持完整 Mermaid、TOC、搜索、frontmatter、代码高亮/复制
```

结论：需要独立的公开文档站。

## 2. 方案对比

### 方案 A：在当前 Vue SPA 内新增 Docs 页面

```text
/router 新增 /docs
复用 lib/markdown.js
```

优点：

```text
最少新依赖
```

缺点：

```text
hash/CSR 影响 SEO
需要补齐 TOC/搜索/Mermaid/代码高亮/侧边栏
Markdown 渲染能力不足
文档内容与工作台应用耦合
```

结论：不推荐。

### 方案 B：VitePress 静态文档站（推荐）

```text
docs-site/ 独立 VitePress 项目
内容源：docs/handbook/
构建为静态 HTML
FastAPI 挂载 /docs
```

优点：

```text
Vue 生态一致
Markdown / 侧边栏 / 搜索 / TOC / 代码高亮 / 深链开箱可用
构建期生成静态 HTML，SEO 好
与主应用解耦，不影响 /v2 包体
```

缺点：

```text
新增 VitePress 依赖与独立构建
需要处理 FastAPI /docs 冲突
需要定制主题以匹配官网纸白设计
```

结论：**推荐**。

### 方案 C：Docusaurus

优点：成熟、生态大。  
缺点：React；与现有 Vue 3 项目不一致；不必要。  
结论：不采用。

## 3. 推荐架构

```text
docs/handbook/                     内容源（Markdown + frontmatter）
  README.md                         Handbook 首页
  _meta/                            审核/规范/规划，不发布
  01-agent-architecture/            第一阶段
  02-enterprise-governance/
  03-system-architecture/
  04-data-knowledge/
  05-reliability-evaluation/
  06-architecture-practice/

docs-site/                          VitePress 项目
  .vitepress/config.mjs
  .vitepress/theme/
  package.json

docs-site/.vitepress/dist/         构建产物
  index.html
  agent-architecture/...
```

FastAPI：

```text
GET /docs -> docs-site/.vitepress/dist/index.html
/assets 按 base /docs/ 解析
```

## 4. 路由设计

```text
/docs
/docs/agent-architecture/
/docs/agent-architecture/enterprise-agent-architecture
/docs/enterprise-governance/
/docs/system-architecture/
/docs/data-knowledge/
/docs/reliability-evaluation/
/docs/architecture-practice/
```

VitePress：

```js
export default {
  base: "/docs/",
  cleanUrls: true,
  // ...
}
```

要求：

```text
1. 每个页面有独立静态 HTML
2. 直接访问/刷新深链 200
3. 旧 unknown /docs/* -> 404 页面
4. 首页“文档”链接从 GitHub 弹窗改为 /docs
5. Footer“产品文档”改为 /docs
```

## 5. FastAPI 冲突处理（P0）

当前 FastAPI 默认：

```text
/docs          Swagger UI
/openapi.json  OpenAPI
```

公开 Handbook 也要 `/docs`，会冲突。

推荐：

```python
FastAPI(
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
```

并更新：

```text
1. 内部 API 文档链接
2. e2e 测试中的 /docs、/openapi.json 断言
3. 部署文档
4. 生产环境仍可通过 RAG_ENABLE_API_DOCS=0 关闭
```

然后挂载：

```python
app.mount(
    "/docs",
    StaticFiles(directory=DOCS_DIST, html=True),
    name="handbook",
)
```

要求：

```text
/docs 不经过登录
/v2/ 应用路由不受影响
/api/docs 与 /docs 不互相覆盖
```

## 6. Markdown 与渲染能力

### 6.1 内容格式

```text
Markdown + YAML frontmatter
代码围栏
Mermaid 代码块
表格
引用
内部链接/外部链接
图片
```

### 6.2 渲染方案

```text
Markdown 解析：VitePress 内置 Markdown-it
代码高亮：VitePress Shiki
Mermaid：Mermaid 插件/客户端懒加载
搜索：VitePress local search（MiniSearch）
目录：VitePress outline
上一篇/下一篇：sidebar 自动生成
```

Mermaid 要求：

```text
1. 支持 flowchart / sequenceDiagram / stateDiagram
2. 构建后页面无 Mermaid 源码裸露（JS 可用时）
3. JS 不可用时显示可读源码 fallback
4. 每张图有图号、标题、alt、说明
5. 图表颜色使用文档主题，不使用随机颜色
```

代码块要求：

```text
语言标识
复制按钮
可显示的标题/文件名
不泄露密钥、真实用户、生产连接串
超长代码折叠或分段
```

## 7. 页面布局

### 7.1 桌面

```text
顶部 64px：Handbook / 搜索 / GitHub / 返回官网
左侧 260px：六个分组 + 当前分类展开
内容 760–840px：文章
右侧 220px：本页 TOC
```

### 7.2 移动

```text
顶部：Logo + 菜单 + 搜索
菜单：全屏抽屉，按分类折叠
正文单列
TOC 折叠到正文顶部
代码块横向滚动，不撑破页面
```

### 7.3 视觉

遵循官网 UI 规范：

```text
纸白 #F7F7F5
卡片 #FFFFFF
正文 #171715
次要 #5C5C56
边框 #E4E4DE
强调 #6F8A8C / #587376
圆角 8/12/16
无渐变/发光/玻璃拟态
```

状态徽章：

```text
已实现   绿灰
开发中   黄褐
已设计   蓝灰
规划中   中性灰
理论知识 中性灰
```

## 8. 导航生成

内容目录固定：

```text
01-agent-architecture
02-enterprise-governance
03-system-architecture
04-data-knowledge
05-reliability-evaluation
06-architecture-practice
```

VitePress 配置可以显式维护 sidebar：

```js
sidebar: {
  "/agent-architecture/": [
    { text: "Agent Architecture", items: [...] }
  ]
}
```

规则：

```text
1. 目录顺序固定，不按字母
2. 每篇 order 必须与 sidebar 一致
3. 新文章必须同时更新 sidebar
4. 构建期检查 sidebar 与文件是否一致
```

可增加构建脚本：

```text
scripts/check_handbook.py
  - 检查 frontmatter 必填
  - 检查 slug 唯一
  - 检查 sidebar 引用
  - 检查内部链接
  - 检查状态值合法
```

## 9. 搜索

使用 VitePress local search：

```text
标题、正文、标题锚点
中文分词能力有限时，补充 tags/description
```

备选：

```text
Pagefind 构建索引
```

不采用：

```text
Algolia（外部 SaaS，需账号/数据出境评估）
后端全文搜索（增加 API 依赖）
```

## 10. 内容构建流程

```text
Markdown + frontmatter
→ VitePress Markdown 解析
→ Mermaid/代码高亮
→ 静态 HTML + 搜索索引
→ FastAPI /docs 静态挂载
```

发布前检查：

```text
1. frontmatter 完整
2. 标题层级正确
3. 内部链接有效
4. 外部链接可访问/已记录
5. 架构图源与正文一致
6. 状态标注准确
7. 移动端无横向溢出
8. 页面可直接刷新
```

## 11. 预计文件清单

### 新增

```text
docs/handbook/README.md
docs/handbook/01-agent-architecture/...
docs/handbook/02-enterprise-governance/...
docs/handbook/...（其余分类）
docs/handbook/_meta/docs-current-state-audit.md
docs/handbook/_meta/information-architecture.md
docs/handbook/_meta/docs-module-implementation-plan.md
docs-site/package.json
docs-site/.vitepress/config.mjs
docs-site/.vitepress/theme/index.js
docs-site/.vitepress/theme/custom.css
scripts/check_handbook.py
```

### 修改

```text
src/rag_demo/api/main.py         /docs 挂载；Swagger URL 迁移
web/src/views/Landing.vue        “文档”链接改为 /docs
web/src/components/...           若首页 Footer 使用 /docs，统一
web/README.md                    更新 /docs 说明
docs/...                         旧文档加“归档/被 Handbook 替代”标注
```

### 不修改

```text
/v2 工作台业务代码
B/C/A 业务路由
现有 KB 文档阅读器
主应用 package 依赖（除非选择在 web 内构建 VitePress）
```

## 12. 实施步骤

```text
Step 1  确定 /docs 路由与 FastAPI Swagger 迁移
Step 2  建立 VitePress 项目与主题
Step 3  接入 docs/handbook 内容源
Step 4  完成首页、分类页、文章页与侧边栏
Step 5  Mermaid、代码高亮、复制、TOC
Step 6  静态搜索与链接检查
Step 7  移动端与可访问性
Step 8  SEO/站点地图/robots
Step 9  与官网入口/Footer 联动
Step 10 验收与回归
```

## 13. 测试与验收

### 13.1 自动化

```text
[ ] VitePress build 成功
[ ] /docs 返回 200
[ ] 每个分类页/文章页返回 200
[ ] /docs 深链刷新 200
[ ] frontmatter 检查通过
[ ] sidebar 与文件一致
[ ] 内部链接 0 死链
[ ] 搜索索引包含所有文章
[ ] Mermaid 页面无渲染错误
[ ] 代码块可复制
[ ] /api/docs 与 /docs 不冲突
```

### 13.2 浏览器

```text
桌面 1440 / 1280
平板 1024 / 768
手机 390 / 320
键盘：Tab / Esc / Enter
搜索：打开、输入、跳转
目录：点击定位、高亮当前
移动菜单：打开/关闭/焦点恢复
```

### 13.3 可访问性

```text
[ ] 语义标题层级
[ ] 跳过导航链接
[ ] 焦点可见
[ ] 菜单/搜索键盘可达
[ ] 对比度 ≥ 4.5
[ ] Mermaid 图有替代文本/说明
[ ] 代码块可键盘滚动
```

### 13.4 SEO

```text
[ ] 每页独立 title/description
[ ] canonical
[ ] OG/Twitter
[ ] sitemap.xml
[ ] robots.txt
[ ] 初始 HTML 包含正文
[ ] hash 不用于文档 canonical
```

### 13.5 回归

```text
[ ] /v2/ 工作台正常
[ ] /v2/#/b 正常
[ ] /v2/#/c/app 正常
[ ] /login 正常
[ ] /ready 正常
[ ] 现有 pytest 全量通过
```

## 14. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| FastAPI /docs 冲突 | 新文档站覆盖 API 文档 | 先迁移 Swagger 到 /api/docs |
| 新增 VitePress 依赖 | 构建链变化 | 独立项目/独立脚本；不影响主包 |
| 内容过期 | 文档误导 | 状态标注 + 代码核对 + 审核流程 |
| Mermaid 体积/渲染失败 | 文档不可读 | 懒加载 + fallback + 构建测试 |
| 搜索中文效果 | 搜不到 | 标题/摘要/tags + Pagefind 备选 |
| 文档无负责人 | 长期腐烂 | 每篇 owner/updated；季度复审 |
| 与旧 docs/ 重复 | 读者困惑 | 旧文档归档/加跳转说明 |
| `/docs` 静态路径/base 错误 | 资源 404 | VitePress base=/docs/ + 真实浏览器验证 |
| 内容被 Google 收录为 app hash 页面 | SEO 重复 | canonical /docs；robots 规则 |

## 15. 验收结论

Docs 模块不是“加一个页面”，而是一个独立的文档产品：

```text
内容体系
+ 信息架构
+ 静态构建
+ 搜索/导航/目录
+ 状态与版本
+ 测试与发布流程
```

本方案批准后，先实现第一阶段 Agent Architecture 的 10 篇内容，再接入其余分类。
