# RRF 融合参数 k 消融实验结果（2026-10-30）

本目录是 `scripts/run_ablation_k.py` 在 33 题黄金测试集（`src/rag_demo/tests/eval_questions.json`）上的
纯检索口径消融产物：固定测试集 / 数据集 / 检索配置，只改变 RRF 的 k（10/30/60/100）。
**未调用 LLM 裁判**，因此没有 Pass Rate（报告与 `summary.json` 中显式标注，不伪造分数）。

| 文件 | 说明 |
| :--- | :--- |
| `report.md` | **最终报告**：主表 + 分层指标 + 差异归因 + 结论 + 限制（人工分析版） |
| `k_10.json` / `k_30.json` / `k_60.json` / `k_100.json` | 每个 k 的逐题明细（两层 sources/rank/耗时 + error）与该 k 汇总 |
| `summary.json` | 4 档汇总、实验元信息、`restored_default_k=60` |

结论一句话：**k∈[30,100] 指标不可区分；k=10 仅单题级抖动（MRR 略低 / Recall@5 略高，方向相反）；
最终上下文层 4 档逐题完全相同 —— k=60 位于平稳平台，保留默认是低风险选择**（详见 `report.md`）。

复现：

```bash
uv run python scripts/run_ablation_k.py --ks 10,30,60,100 --dataset demo
```
