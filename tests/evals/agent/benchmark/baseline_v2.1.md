# Agent Eval v2.1 · RAG Fallback

v2.1 基于 Runtime trace 做一项能力增强：混合检索失败时降级到关键词召回。

## 改动

`rag_search` 的 `hybrid_search` 异常时：

```text
hybrid_search(query)
   ↓ exception
keyword_search(query)
   ↓
结构化结果 / 来源
```

只有两路都失败才返回 `RAG_SEARCH_ERROR`。

## 测试

新增 `test_rag_falls_back_to_keyword_search`：

```text
hybrid_search raises
→ keyword_search returns
→ rag_search ok=true
```

## 说明

这是对 Runtime trace 中 RAG 错误的可恢复性补强，不修改题目和 Eval 判分口径。
