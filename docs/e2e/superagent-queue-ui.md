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
关键词搜索：Job / WorkItem / Worker / 错误
分页：每页 50 条，上一页/下一页
5 秒自动刷新（可关闭）
最老 PENDING 时间
Job 列表：Job ID、WorkItem、类型、状态、attempts、worker、错误、更新时间
DEAD/FAILED 一键重放
```

## 2. 数据接口

```text
GET  /api/superagent/jobs?limit=50&offset=0&status=&kind=&q=
GET  /api/superagent/jobs/stats
POST /api/superagent/jobs/{job_id}/replay
```

`/jobs` 同时返回：

```text
jobs / total / offset / limit / stats
```

## 3. 浏览器验证

Playwright：

```text
导航 /v2/queue.html
标题：千客 · 队列管理
总任务 246
分页 1/5
搜索 saj_ed683b3e2bdb4b8f → 共 1 条
清空搜索 → 下一页 → 第 2/5 页
5s 自动刷新默认开启
console errors: 0
```

截图：

```text
.mcp/playwright-output/queue-page2.png
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
没有按时间范围过滤
自动刷新固定 5s，不可配置
没有批量重放
没有死信导出
```
