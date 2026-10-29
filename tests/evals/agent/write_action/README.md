# 受控写 Eval：prepare_followup_task + HITL

**状态：** 确定性 Eval（`status=deterministic`）。不调用真实 LLM、不连网络、不连业务库；真实模型基线（`baseline=not_required`）不在本套范围内。

本目录是经营分析 Agent 首个写功能（运营跟进任务）的**确定性评测套件**，对应需求文档 [docs/agent-write-action.md](../../../../docs/agent-write-action.md)，评测说明 [docs/agent-write-action-eval.md](../../../../docs/agent-write-action-eval.md)。

## 文件

| 文件 | 作用 |
|---|---|
| `dataset.v1.json` | 18 个确定性用例：意图门槛 / 显式写 / HITL / 权限 / 写入隔离 |
| `runner.py` | 确定性 runner：脚本化 LLM 轨迹 + 真实 `loop.run_agent` / `actions` 链路，输出 JSON 摘要与通过率 |
| `../write_action/README.md` | 本说明 |

判分与数据集校验逻辑只存在于 `runner.py`，`tests/test_agent_write_action_eval.py` 复用同一份实现，不另写一套。

## 运行

在仓库根目录（Windows 用仓库 venv）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_write_action_eval.py -q

.\.venv\Scripts\python.exe tests/evals/agent/write_action/runner.py
.\.venv\Scripts\python.exe tests/evals/agent/write_action/runner.py --validate-only
.\.venv\Scripts\python.exe tests/evals/agent/write_action/runner.py --output var/write_action_eval.json
```

- runner 默认 stdout 输出 JSON 摘要（含 `pass_rate`），退出码：全过 `0` / 有失败 `1` / 数据集非法 `2`；
- `--validate-only` 只校验数据集契约，不执行用例；
- 每个 case 使用独立临时 SQLite（`QIANKE_AGENT_ACTION_DB` + 重置 `actions._DB_PATH`），不写 `var/agent_actions.sqlite`。

## 判分

- 一个 case 的全部 `checks` 都通过才记 `PASS`；
- 汇总输出 `total / passed / failed / pass_rate / by_category / failed_cases / cases[].checks`；
- `tests/test_agent_write_action_eval.py` 里有一条**反证用例**：故意篡改期望值后 runner 必须判 FAIL，防止判分空转。

详细场景映射、JSON 摘要示例与未覆盖项见 [docs/agent-write-action-eval.md](../../../../docs/agent-write-action-eval.md)。
