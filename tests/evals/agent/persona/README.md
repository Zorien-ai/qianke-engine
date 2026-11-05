# B 端人设 Eval 数据集 v1

**状态：** 草案（draft）。**真实模型基线尚未运行。** 本目录只定义用例与判据，不记录、也不允许补写通过率 / 得分。

---

## 1. 用途

验证 B 端主 Agent 的人设与语气规范（[`docs/product/b-end-agent-persona.md`](../../../../docs/product/b-end-agent-persona.md) v0.3）是否被真实输出遵守。人设不是「看一遍觉得不错」，要能被测：

- 称呼与禁词：不出现「老板 / 亲 / 宝子 / 家人们 / 亲爱的 / 帅哥美女 / 您嘞」；
- 形：没有 emoji、没有感叹号、长度不超档位上限（L1 80 / L2 300 / L3 120 字，report 模式不限）；
- 事实：数字只来自工具结果，口径 / 时间范围 / 样本量该带就带；
- 边界：不预测、不编数、不越权、不美化坏消息、不把系统故障说成「没有数据」；
- 多轮稳定：不丢口径、不滑回客服腔、被质疑后仍不编造。

数据集覆盖 **25 条：22 条单轮 + 3 条多轮**，与文档 §12.4 一致。

## 2. 文件

| 文件 | 作用 |
|---|---|
| `dataset.v1.json` | 用例本体（机器可读） |
| `README.md` | 本说明 |
| `tests/test_b_persona_eval_contract.py` | 数据集契约单测：条数 / 字段 / mode / 场景覆盖 / 禁词维度，**不调用模型** |

## 3. 数据集结构

顶层字段：

| 字段 | 说明 |
|---|---|
| `version` | 数据集版本号（`b-persona-eval-v1`） |
| `dataset` | 目标数据集（`demo`，与 Regression / Benchmark 一致） |
| `description` | 人读摘要 |
| `status` | `draft`（尚未跑真实模型基线） |
| `baseline` | `not_run`；真实模型基线跑完后另存结果，不写在本文件 |
| `related_doc` | 对应的人设规范文档路径 |
| `modes` | `agent` / `chat` 两条链路的说明 |
| `scoring` | 硬规则（forbidden 子串）与软判分（人工 / LLM Judge）说明 |
| `coverage` | 关键维度的用例 id 索引，供契约测试校验覆盖 |
| `cases` | 用例数组 |

每条用例字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | 唯一 id：`persona_single_XX` / `persona_multi_XX` |
| `category` | str | 场景名（单轮 22 类固定，多轮 3 类） |
| `mode` | str | `agent`（`/api/agent/run`，有 SQL / RAG / 计算器）或 `chat`（`/qa`、`/qa/stream`，RAG 主链路） |
| `turns` | list[str] | 用户侧消息；单轮 1 条，多轮 3–5 条（不含 Agent 回复） |
| `expect` | str | 期望行为（给人 / LLM Judge 看） |
| `acceptance` | list[str] | 可逐条勾选的验收点（含长度上限、必须有的事实或边界） |
| `forbidden` | list[str] | 出现即判该条不通过的子串（禁称 / emoji / 感叹号 / 承诺词 / 卖萌承接等） |

> `forbidden` 只收「正确回答里也不该出现」的字符串，避免把正确回答里的事实词误判（例如「不是没有数据」不会被「没有数据」误杀，具体见 JSON）。

## 4. 如何运行

### 4.1 契约校验（当前唯一可自动跑的，不依赖模型）

在仓库根目录：

```bash
python -m pytest tests/test_b_persona_eval_contract.py -q
```

Windows 使用仓库 venv 时：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_b_persona_eval_contract.py -q
```

校验内容：JSON 可解析、25 条、id 唯一、`mode` 合法、22 单轮 + 3 多轮、22 类关键场景齐全、`forbidden` 至少覆盖「老板 / 亲」等维度、`coverage` 索引与用例一致。

### 4.2 手工评测（真实模型，P3 阶段）

1. 按 `mode` 选择链路：`agent` 走 `/api/agent/run`，`chat` 走 `/qa`（或 `/qa/stream`），带真实 demo 数据与登录角色（`persona_single_19` 需 `cs` 角色账号）；
2. 逐条把 `turns` 依次发给链路，保存每轮用户可见输出（含固定文案兜底后的文本）；
3. 硬判：`forbidden` 子串检查 + 长度上限；
4. 软判：对照文档 §12.1 checklist 14 条与 §12.2 五维打分（0–2，平均 ≥1.6 且「无法判分」<10% 为合格线）；
5. 记录 `prompt 版本 / persona 配置（name / user_address / tone_profile）/ 温度（Agent 0.2、Chat 0.3 分开）/ 模型 / 时间`。

### 4.3 脚本化评测（尚未实现）

真实模型 runner（批量调用两条链路 + 自动硬判 + 汇总 JSON）属于 P3 落地项，**当前仓库还没有该脚本**。在 runner 与基线结果落地前：

- 不得在本文档、数据集或提交信息里写「通过率 / 得分 / 已通过」；
- 不得用 LLM 桩或单元测试结果冒充人设 Eval 结果。

## 5. 维护规则

- 增删用例必须同步更新本 README 的条数说明、`coverage` 索引和 `tests/test_b_persona_eval_contract.py` 中的计数 / 场景断言；
- 单轮保持 22 类关键场景各一条；多轮保持 3 条（口径记忆 / 客服腔漂移 / 质疑后不编造）；
- 固定文案（chitchat 拒答、`answer_guard` 兜底、服务不可用）改动时，对应场景的 `forbidden` 与 `acceptance` 一并复核；
- 改人设 prompt / System Message / 温度 / 工具返回结构 / 记忆策略后，必须重跑本组 Eval（文档 §12.4、§15）。
