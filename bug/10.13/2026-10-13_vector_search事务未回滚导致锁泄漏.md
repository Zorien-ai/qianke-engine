# vector_search 事务未回滚导致锁泄漏

**日期**：2026-10-13
**发现场景**：检索索引落库后的数据重导（`ingest_data` → `ingest_docs` → `build_search_index`）
**严重度**：🔴 高 —— 会阻塞所有 DDL，并长期持有事务快照

---

## 现象

数据重导时，`ingest_data.py` 的建索引阶段卡了 **21 分钟**：

```
20:59:37 | INFO | 建立新数据库连接...
21:21:03 | INFO | 结构化字段与索引已就绪        ← 中间 21 分 26 秒
```

随后 `ingest_docs.py` 彻底卡死：两条
`ALTER TABLE wiki_vectors ADD COLUMN IF NOT EXISTS metadata JSONB`
分别等待 **61 分钟**和 **30 分钟**，仍未拿到锁，两次执行都以工具端超时告终。

一开始误判为「数据量大所以慢」，但 8110 行建索引本应在秒级完成。

---

## 诊断

```sql
SELECT pid, state, wait_event_type, wait_event,
       now() - state_change AS since, left(query, 80)
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid();
```

```
1112 | idle in transaction | Client/ClientRead | 70 分钟
     | SELECT ... 1 - (embedding <=> '...') ... FROM wiki_vectors ...
1761 | active | Lock/relation | 61 分钟 | ALTER TABLE wiki_vectors ADD COLUMN IF NOT EXISTS metadata JSONB
1793 | active | Lock/relation | 30 分钟 | ALTER TABLE wiki_vectors ADD COLUMN IF NOT EXISTS metadata JSONB
```

未授予的锁：

```
(1793, wiki_vectors, AccessExclusiveLock, False)
(1761, wiki_vectors, AccessExclusiveLock, False)
```

**PID 1112 是罪魁**：它执行完一次向量检索后就停在 `idle in transaction`，
持续持有 `wiki_vectors` 的 `AccessShareLock`。而 `ALTER TABLE` 需要 `AccessExclusiveLock`，
两者互斥 —— 于是 ALTER 被无限期阻塞，而它自己又永远不结束事务。

`1761` / `1793` 是那两次超时的 `ingest_docs` 进程，进程没退出，还在后台干等锁。

---

## 根因

`hybrid_retriever.vector_search()` 只调 `cur.close()` 就返回：

```python
cur = get_conn().cursor()
...
cur.close()
return results
```

**psycopg2 的 `cur.close()` 不会结束事务。** 连接会停在 `idle in transaction`，
持有本次查询的快照与锁，直到下一次显式 `commit()` / `rollback()` 或连接断开。

对比同类函数——它们都回滚了，唯独这个漏了：

| 函数 | 是否回滚事务 |
|---|---|
| `sql_tool.execute_sql` | ✅ `conn.rollback()` in finally |
| `hybrid_retriever._load_bm25_corpus` | ✅ |
| `sparse_retriever.sparse_search` | ✅ |
| `api/main.py::stats` | ✅ |
| **`hybrid_retriever.vector_search`** | ❌ **缺失** |

值得注意的是，`db/connection.py::get_conn()` 的探活逻辑里专门写了
`_conn.rollback()  # 探活后立即清理事务，避免连接长期停在 idle in transaction`
—— 说明这个坑在设计时是意识到的，只是 `vector_search` 这一处没跟上。

---

## 影响

**不止是阻塞 ingest**：

1. **阻塞所有 DDL** —— `ALTER TABLE` / `CREATE INDEX` / `TRUNCATE` 都拿不到排他锁
2. **阻塞 VACUUM** —— 长期事务快照让死元组无法回收，表会持续膨胀
3. **连接被占死** —— 单例连接长期停在事务中；未设
   `idle_in_transaction_session_timeout` 时永不释放

对一个只有 8110 行的 Demo 库来说，表现为「莫名其妙的几十分钟卡顿」；
在生产库上则是更隐蔽的资源泄漏。

---

## 修复

```python
    try:
        ...  # 画像表 + wiki 表两次查询
    finally:
        conn.rollback()  # 结束事务，释放 AccessShareLock
        cur.close()

    return results
```

**代码锚点**：`retrieval/hybrid_retriever.py::vector_search`

---

## 验证

修复后重跑三步重导：

| 步骤 | 结果 | 备注 |
|---|---|---|
| `ingest_data.py` | 8110 条，会员分布 50/30/15/5 | 精确命中目标分布 |
| `ingest_docs.py` | 36 个分块 | **秒级完成**（修复前卡到超时） |
| `build_search_index.py` | 8146 行，零缺失 | **38.08s**（修复前同类操作卡 21 分钟） |

评测回归（`gpu_v11`）：20/20 执行成功、自动判定 17/20，与改造前基线一致，
**无路由变化**。

---

## 遗留

1. **未设 `idle_in_transaction_session_timeout`**。建议在连接初始化时加兜底，
   例如 `SET idle_in_transaction_session_timeout = '5min'`，
   让误留的事务能被数据库自动清理，而不是永久卡住 DDL。

2. **「记得回滚」目前是约定，不是机制**。每个检索函数各自记得写 `finally: rollback()`，
   靠的是人不出错 —— 这个 bug 正是一次漏写。可考虑统一封装成上下文管理器：

   ```python
   @contextmanager
   def db_cursor():
       conn = get_conn()
       cur = conn.cursor()
       try:
           yield cur
       finally:
           conn.rollback()
           cur.close()
   ```

   但这是较大重构，本次未做，先记录在案。

3. **操作提醒**：如果 uvicorn 正在运行，做 ingest 前应先停掉服务，
   否则同样会被它的连接挡住（本次就是这么触发的）。
