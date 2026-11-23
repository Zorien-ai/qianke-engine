# M5 发布候选冻结记录（2026-11-23）

> 状态：**frozen_candidate**  
> 冻结时间：2026-11-23T18:30:00+08:00  
> 基线文章：`01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md`  
> Git HEAD：`32ad31bc26365e8d0cefe503e6c09cfcd2876eaa`  
> 公开文章：**60 篇**（6 分类 × 10）

## 冻结内容

- 60 篇公开文章源码哈希：`2026-11-23-m5-candidate.json`
- VitePress 配置、主题、依赖锁文件哈希
- 构建产物 `docs-site/.vitepress/dist/index.html` 哈希
- M5 最终验收报告：[2026-11-23-final-quality-acceptance.md](../reviews/2026-11-23-final-quality-acceptance.md)

## 冻结时验收

```text
docs build             exit 0
公开路由               60/60 本地 200、公网 200
pytest                 34 passed, 1 warning
Mermaid / 搜索 / 移动端 已验证
```

## 冻结策略

```text
1. 本候选作为 M6 增量修改的基线；
2. 后续内容修复不覆盖此记录，追加新的 release/change 记录；
3. 每次 M6 修改必须记录文件、原因、证据、验证结果；
4. 未重新验收的改动不得改写本冻结记录的验收字段。
```

## 已知限制（冻结时）

```text
- 仍有 P2 未全量清零：HITL / Prompt Injection / Tool Gateway 等一致性差异；
- 全量 pytest、Regression、Benchmark、生产并发、SLO 未执行；
- docs/agent.md 等历史内部文档仍有漂移；
- 外部链接未逐条自动检查。
```
