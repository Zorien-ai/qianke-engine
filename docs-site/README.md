# Qianke Engine Architecture Handbook Docs Site

公开文档站源码，使用 VitePress 构建，内容来自 `../docs/handbook`。

## 开发

```powershell
cd docs-site
npm install
npm run dev
```

## 构建

```powershell
npm run build
```

构建产物：

```text
docs-site/.vitepress/dist
```

FastAPI 在存在构建产物时自动挂载：

```text
/docs
```

Swagger API 文档迁移到 `/api/docs`，避免与公开 Handbook 冲突。

## 内容约定

- 6 个分类 × 10 篇 = 60 篇正文
- 每篇保留 12 个二级章节
- 状态区分：已实现 / 部分实现 / 已设计 / 规划中 / 理论知识
- 代码、测试和运行证据优先，不把规划能力写成已实现
- 旧版本文章归档在 `docs/handbook/_meta/versions/`，不进入公开站
