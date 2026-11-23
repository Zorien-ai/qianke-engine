# M6 增量治理计划与状态（2026-11-23）

> 基线：M5 发布候选已冻结  
> 原则：不再追求一次性清零所有 P2；后续按增量修复，每次保留证据

## 1. 冻结基线

- [M5 冻结记录](2026-11-23-m5-candidate.md)
- [M5 文章校验和 manifest](2026-11-23-m5-candidate.json)
- [M5 最终验收报告](2026-11-23-final-quality-acceptance.md)

冻结时的已知限制继续有效：剩余 P2 未全量清零；全量 Eval、生产并发与 SLO 未执行。

## 2. M6 三个方向

| 方向 | 内容 | 状态 |
|---|---|---|
| M6.1 内容一致性治理 | HITL、Prompt Injection、Tool Gateway 等剩余 P2 | 首批已修复，持续增量 |
| M6.2 文档工程化 | 构建、路由、死链、状态检查接入 CI | 已落地本地脚本与 workflow，待 CI 首次运行 |
| M6.3 工程质量验收 | 全量 pytest、Regression/Benchmark、生产并发与 SLO | 独立计划，尚未执行 |

## 3. 增量规则

```text
1. 每次只处理一个主题或一个批次，不重写整站；
2. 修改前后记录文章 SHA256；M6 变更记录见 2026-11-23-m6-change-log.md；
3. 每次修改跑 docs-site 构建 + content check + 受影响路由；
4. 涉及代码事实的修改重新对照代码，未运行测试不得写成已验证；
5. 未纳入本轮的低优先 P2 保持原状，不假装已修复。
```

## 4. 当前验证

```text
docs-site build              exit 0
content check                60 articles, 0 errors, 1 warning（V0.5.1 归档提示）
公开路由                     60/60 本地 200、公网 200
```

M6.2 的 GitHub Actions 尚未在远端实际运行，不能写成 CI 已通过；本地脚本已跑通。
