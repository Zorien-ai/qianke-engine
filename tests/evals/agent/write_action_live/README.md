# 受控写 Live Eval（真实 LLM + HTTP E2E）

**状态：** `live`，`baseline=not_recorded`。**默认 pytest 不运行**（CI 不会误红）。

真实 LLM 用例要求 `RUN_WRITE_ACTION_LIVE_EVAL=1` **且** `DEEPSEEK_API_KEY` 非空；HTTP E2E 只要求 `RUN_WRITE_ACTION_LIVE_EVAL=1`。完整说明与实际运行结果见 [docs/agent-write-action-live-eval.md](../../../../docs/agent-write-action-live-eval.md)。

## 文件

| 文件 | 作用 |
|---|---|
| `dataset.v1.json` | 3 个真实 LLM 场景（显式写 / 普通分析 / 诱导直写）+ HTTP E2E 期望清单 |
| `runner.py` | 门禁判定 + 真实 `run_agent` + FastAPI TestClient HTTP E2E + JSON 摘要 CLI |

判分逻辑只在本 `runner.py`：pytest（`tests/test_agent_write_action_live.py`）复用同一实现。

## 运行

```powershell
# 默认：全部 skip（不联网）
.\.venv\Scripts\python.exe -m pytest tests/test_agent_write_action_live.py -q

# HTTP E2E（不需要 key）
$env:RUN_WRITE_ACTION_LIVE_EVAL="1"
.\.venv\Scripts\python.exe -m pytest tests/test_agent_write_action_live.py::test_http_e2e_confirm_cancel_status_codes -q

# 真实 LLM + HTTP 全量（需要 key；先按团队方式注入 DEEPSEEK_API_KEY）
$env:RUN_WRITE_ACTION_LIVE_EVAL="1"
.\.venv\Scripts\python.exe -m pytest tests/test_agent_write_action_live.py -q

# runner：JSON 摘要（mode/total/passed/failed/skipped/checks/blockers）
.\.venv\Scripts\python.exe tests/evals/agent/write_action_live/runner.py --output var/write_action_live_summary.json
```

- runner 退出码：无 FAIL `0`；有 FAIL `1`；数据集非法 `2`；skipped 不计失败。
- 每个用例独立临时 `QIANKE_AGENT_ACTION_DB`，只写 `agent_action`，不写业务库。
- `main.py` import 失败只记录 blocker 并 skip，不修改被测文件。

## 判分

一个用例全部 `checks` 通过才记 `PASS`；摘要含 `total / passed / failed / skipped / check_total / check_passed / failed_items / blockers`。
本套结果受真实模型波动影响，**单次通过不等于稳定通过**，不写入稳定基线。
