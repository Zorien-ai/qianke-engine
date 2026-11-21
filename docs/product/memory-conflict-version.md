# 记忆冲突、Supersede 与版本链

> 状态：Phase 3C 已落地  
> 前置：Phase 2B 候选记忆 / Phase 3A 自动复盘 / Phase 3B 身份消歧

## 1. 问题

同一客户先后说：

```text
我的预算 500 元
我的预算 800 元
```

两条都进入长期记忆会让 Agent 在 Prompt 里同时看到矛盾信息。  
不能简单覆盖删除：历史版本仍需可追溯；也不能让两条同时 ACTIVE。

## 2. 冲突键 conflict_key

Phase 3C 只对**确定性结构**生成冲突键，不做 LLM 模糊判断。

| 记忆 | conflict_key |
|---|---|
| `预算 500 元` / `预算 800 元` | `budget` |
| `尺码 42` / `尺码 43` | `size` |
| `喜欢跑步` / `不喜欢跑步` | `taste:跑步` |
| `不要推荐跑鞋` | `avoid:跑鞋` |
| `对花生过敏` | `allergy:花生` |

无冲突键的记忆不参与 supersede；多条可以共存。

## 3. 生命周期

```text
CANDIDATE / PENDING_CONFIRMATION
        │
        ▼
      ACTIVE ────── 新记忆确认且 conflict_key 相同
        │                  │
        │                  ▼
        │             SUPERSEDED
        │             superseded_by_memory_id
        │             superseded_at
        └──────── 新 ACTIVE（version = old.version + 1）
```

约束：

- 同一 `owner_id + conflict_key` 同时最多 1 条 ACTIVE；
- 旧版本不删除，状态改为 `SUPERSEDED`；
- `superseded_by_memory_id` 指向新版本；
- 新版本 `supersedes_memory_id` 指向直接前驱；
- 审计记录 `CONFIRM` + `SUPERSEDE`。

## 4. 版本号

- 无冲突：version = 1
- 有冲突：version = 旧版本最大 version + 1
- 同一内容重复出现：不新建版本，只强化当前 ACTIVE（或候选去重）

## 5. API

```text
GET /api/c/companion/memories/{memory_id}/history
```

返回：

```json
{
  "memory_id": "mem_new",
  "conflict_key": "budget",
  "versions": [
    {"memory_id": "mem_old", "version": 1, "content": "预算 500 元", "status": "SUPERSEDED", "superseded_by_memory_id": "mem_new"},
    {"memory_id": "mem_new", "version": 2, "content": "预算 800 元", "status": "ACTIVE"}
  ]
}
```

权限：只能查当前 buyer 自己的记忆；跨 owner 返回 404。

## 6. CApp

- ACTIVE 记忆显示 `v2` 版本号；
- `历史` 按钮展示版本链；
- 候选记忆若 `supersedes_memory_id` 非空，显示「将替换旧记忆」；
- 确认候选后显示新版本，旧版本进入历史。

## 7. 审计

```text
c_companion_memory_audit
  CONFIRM  新版本确认
  SUPERSEDE 旧版本被替换
```

审计 detail 包含：

```text
old_memory_id / new_memory_id
old_version / new_version
conflict_key
content
```

## 8. 验收用例

```text
conflict_key_budget
conflict_key_size
conflict_key_taste_positive_negative
confirm_supersedes_old_budget
different_key_does_not_supersede
version_chain_history
history_cross_owner_404
candidate_shows_supersedes
direct_save_supersedes
```

## 9. 非目标

```text
- LLM 判断两条偏好是否“语义冲突”
- 自动合并不同客户的记忆
- 删除旧版本（只标记 SUPERSEDED）
- 跨租户版本链
```


## 10. 实现状态（2026-11-21）

| 能力 | 状态 | 位置 |
|---|---|---|
| 确定性 conflict_key | ✅ | `c_end/store.py::memory_conflict_key` |
| 旧 ACTIVE → SUPERSEDED | ✅ | `_supersede_active_conflicts` |
| 版本号递增 | ✅ | `save_memories` / `confirm_memory_candidate` |
| 版本链查询 | ✅ | `list_memory_history` |
| 版本链 API | ✅ | `GET /api/c/companion/memories/{id}/history` |
| CApp 版本号 / 历史 / 替换提示 | ✅ | `web/src/views/CApp.vue` |
| 审计 CONFIRM + SUPERSEDE | ✅ | `c_companion_memory_audit` |

验证：

```text
pytest tests/test_c_memory_conflict_version.py        tests/test_c_memory_candidates.py        tests/test_c_end_memory.py -q

17 passed
```
