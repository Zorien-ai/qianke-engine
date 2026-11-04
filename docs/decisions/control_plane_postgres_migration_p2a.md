# 控制面 PostgreSQL 迁移 P2-A：Super-agent 回填与只读 repository

> 日期：2026-11-04 · 状态：P2-A 完成 · 运行时尚未切换

## 1. 本阶段交付

```text
sa_thread / sa_trigger / sa_work_item / sa_approval 回填脚本
sa_job → sa_queue.sa_job 队列统一回填
PostgresSuperagentRepository 只读查询
回填 + 只读契约测试
```

## 2. 回填脚本

```bash
python scripts/migrate_superagent_to_pg.py
python scripts/migrate_superagent_to_pg.py --yes
python scripts/migrate_superagent_to_pg.py --yes --skip-jobs
```

行为：

```text
默认 dry-run
读取 SQLite sa_*
创建/复用 qianke_control schema
按主键 UPSERT
sa_job 复制到 sa_queue.sa_job
输出 source/target 计数
```

幂等：

```text
重复执行不会重复插入
同一主键更新其余字段
```

## 3. 只读 repository

```python
from rag_demo.control import PostgresSuperagentRepository

repo = PostgresSuperagentRepository(schema="qianke_control")
repo.get_thread(thread_id)          # 含 triggers
repo.get_work_item(work_item_id)
repo.list_work_items(merchant_id=...)
repo.get_approval(work_item_id)
repo.counts()
repo.close()
```

## 4. 验证

手工回填：

```text
source sa_thread=2 sa_trigger=2 sa_work_item=2 sa_approval=0 jobs=0
target sa_thread=2 sa_trigger=2 sa_work_item=2 sa_approval=0
apply_exit=0
```

自动化：

```bash
pytest tests/test_superagent_pg_backfill.py -q
# 1 passed
```

覆盖：

```text
SQLite 创建 Thread/Trigger/WorkItem/Job
回填到临时 PG schema
target 计数正确
队列 Job 写入 sa_queue
幂等重跑计数不增长
只读 repository 读回 Thread/Trigger/WorkItem
```

完整套件：

```text
654 passed, 5 skipped, 1 warning
```

## 5. 已知限制

```text
API/Worker 仍读写 SQLite
没有双写
没有运行时 backend 开关
没有写入 repository（create/update/approve）
没有回填校验 checksum
没有 PG 写入后的反向同步
队列仍由 QIANKE_QUEUE_BACKEND 控制
```

## 6. 下一步 P2-B

```text
1. superagent/store.py 增加 backend 分支
2. create_trigger / start/finish / decide / complete 写 PG
3. 队列统一启用 sa_queue
4. 双后端 CRUD 契约测试
5. 测试环境切 PG 跑 Eval 烟测
6. 维护窗口切换预演
```
