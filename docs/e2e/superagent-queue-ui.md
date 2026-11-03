# 队列管理页面

> 日期：2026-11-03 · 状态：`/v2/queue.html` 浏览器验证通过

## 1. 页面

```text
http://127.0.0.1:8000/v2/queue.html
```

仅系统管理员可访问。

功能：

```text
Job 总数 / PENDING / RUNNING / DONE / FAILED / DEAD
按状态过滤
按类型过滤（WORKER / ACTION）
最老 PENDING 时间
Job 列表：Job ID、WorkItem、类型、状态、attempts、worker、错误、更新时间
DEAD/FAILED 一键重放
```

## 2. 数据接口

```text
GET  /api/superagent/jobs?limit=100&status=...&kind=...
GET  /api/superagent/jobs/stats
POST /api/superagent/jobs/{job_id}/replay
```

`/jobs` 同时返回 `jobs` 和 `stats`。

## 3. 浏览器验证

Playwright：

```text
导航 /v2/queue.html
标题：千客 · 队列管理
总任务 149 / DONE 149
状态、类型过滤器渲染
列表显示 100 条
console errors: 0
```

截图：

```text
.mcp/playwright-output/queue-admin.png
```

## 4. 重放交互

```text
DEAD / FAILED 行显示「重放」
确认后 POST replay
attempts 归零 → PENDING
成功提示 → 自动刷新
```

预发环境冒烟：

```text
saj_c42054cd8681437b / DEAD
replay 200 / PENDING / attempts=0
再次 replay 409 / RUNNING
```

## 5. 测试

后端无新增测试（复用已覆盖的 job stats/replay 测试）。

```text
pytest tests/ -q
631 passed, 5 skipped, 1 warning

npm run build
✓ built in 4.46s
```

## 6. 已知限制

```text
没有分页，最多显示 100 条
没有自动刷新/轮询
没有按 WorkItem/Worker 搜索
没有批量重放
没有死信导出
```
