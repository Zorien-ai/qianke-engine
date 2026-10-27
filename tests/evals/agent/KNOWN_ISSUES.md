# Agent Eval 已知问题与可信度说明

更新：2026-10-27

## P0：已处理

### 1. 公共 80 题标记为 Development Set

v1.8～v2.2 期间，新题由我们构造，并在看到失败后调整过：

- expected keyword 格式
- optional tool policy
- negative 判分口径
- fact-aware 判分

所以当前 `benchmark/dataset.v1.json` 的 80 题是：

```text
development set
```

不是独立 held-out，不能把 `Business Correctness 100%` 当作生产准确率。

### 2. 已建立本地 Private Holdout

路径：

```text
tests/evals/agent/private_holdout/
```

特点：

- 20 题
- 构建期未运行 Agent
- 已加入 `.gitignore`，不进入公共仓库
- 不用于 Prompt / 判分调优

首次运行结果（题目构造有 bug，已废弃）：

```text
Task Success        75.0%
Business Correctness 80.0%
Tool Policy         90.0%
```

首跑暴露出题目构造问题：

- `private_017` / `private_018`：negative 的 `expected_keywords` 非空，和 `expected_keywords_any` 重复
- `private_004`：金额千分位与 expected keyword 不一致
- `private_011` / `private_014`：calculator 实际可省略

修复题目构造后重跑，得到有效 private baseline：

```text
Task Success        85.0%
Business Correctness 85.0%
Tool Policy         100.0%
Tool Selection      100.0%
Tool Execution      93.5%
Error Recovery      50.0%
```

这组结果与公共集 96.2% 有明显差距，说明公共集确实偏乐观。

处理原则：

```text
这组 20 题不再用于调 Prompt / 不调公共集
下一轮重建新的 private holdout（不同题目）
```

## P1：明确延后、暂不修

以下问题已记录，等真实使用产生后果后再改：

1. **timeout 不是硬超时**
   - 当前只在 chatbot 节点开始前检查
   - 单次 LLM / tool 调用中无法立即中断
2. **cancellation 是协作式**
   - 在下一个节点检查点生效
3. **token budget 是事后检查**
   - 超预算可能已经多跑一次 LLM
4. **Runtime token 采集未做真实端到端验证**
   - callback 从 `llm_output.token_usage` 读取
   - 需要一次真实 API 调用验证 `total_tokens`
5. **API 缺少端到端测试**
   - 目前测试主要覆盖 loop / evaluator，不覆盖 HTTP 层
6. **部分新题质量一般**
   - multi_tool 可能只需 SQL
   - expected keyword 对格式敏感
7. **历史 baseline 的 `agent_commit` 仍是 pending**
   - v1.8.1 ~ v1.9.2 的旧基线无法严格复现
8. **本地分支尚未推送**
   - `origin/agent` 落后本地多个提交

## 结论

已经修掉的最大纰漏是：

```text
把“公共开发集”误当“独立评测集”
```

现在把公共 80 题降级为 development set，并建立了独立 private holdout。  
其余问题等出现真实后果再处理，不在本轮继续扩工程。
