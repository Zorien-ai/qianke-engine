# -*- coding: utf-8 -*-
"""B 端受控写 Live Eval 契约测试：真实 LLM + HTTP E2E。

默认行为（CI / 日常 pytest）：
- 不联网、不 import `rag_demo.api.main`、不调用真实模型；
- 真实 LLM 用例仅在 `RUN_WRITE_ACTION_LIVE_EVAL=1` 且存在 `DEEPSEEK_API_KEY` 时执行，否则 skip；
- HTTP E2E 用例仅在 `RUN_WRITE_ACTION_LIVE_EVAL=1` 时执行，否则 skip；
- 默认运行的只有数据集契约、门禁逻辑、runner JSON 摘要等确定性断言。

本地真实跑法：
    $env:RUN_WRITE_ACTION_LIVE_EVAL="1"
    $env:DEEPSEEK_API_KEY="sk-..."
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_agent_write_action_live.py -q -s
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).parent / "evals" / "agent" / "write_action_live"


def _load_runner():
    """用唯一模块名加载本目录 runner，避免与其它 eval 目录的 runner.py 撞名。"""
    module_name = "write_action_live_runner"
    spec = importlib.util.spec_from_file_location(module_name, EVAL_DIR / "runner.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 runner：{EVAL_DIR / 'runner.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()

DATASET = runner.load_dataset()
CASES = {case["id"]: case for case in DATASET["cases"]}
FLAG_ENV = runner.FLAG_ENV
KEY_ENV = runner.KEY_ENV


def _require_flag() -> None:
    if os.environ.get(FLAG_ENV) != "1":
        pytest.skip(f"Live Eval 默认关闭：设置 {FLAG_ENV}=1 后执行")


def _require_llm() -> None:
    _require_flag()
    if not (os.environ.get(KEY_ENV) or "").strip():
        pytest.skip(f"缺少 {KEY_ENV}，跳过真实 LLM 用例")


# ---------------------------------------------------------------------------
# 默认运行：数据集 / 门禁 / 汇总（不联网）
# ---------------------------------------------------------------------------


def test_dataset_contract():
    assert runner.validate_dataset(DATASET) == []
    assert DATASET["version"] == "agent-write-action-live-eval-v1"
    assert DATASET["status"] == "live"
    assert DATASET["baseline"] == "not_recorded"
    assert DATASET["gate"]["env_flag"] == FLAG_ENV
    assert DATASET["gate"]["required_key"] == KEY_ENV
    assert {case["category"] for case in DATASET["cases"]} == runner.REQUIRED_CATEGORIES
    assert len(CASES) >= 3
    http_spec = DATASET["http_e2e"]
    assert http_spec["id"] == "http_confirm_cancel_matrix"
    assert set(http_spec["expected_checks"]) == {
        "anonymous_confirm_401",
        "pending_account_confirm_403",
        "owner_confirm_200",
        "duplicate_confirm_409",
        "cross_account_confirm_409",
        "demo_confirm_409",
        "owner_cancel_200",
        "duplicate_cancel_409",
    }


def test_live_gate_reflects_environment(monkeypatch):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv(KEY_ENV, raising=False)
    gate = runner.live_gate()
    assert gate["live_enabled"] is False
    assert gate["llm_ready"] is False
    assert FLAG_ENV in gate["reason"]

    monkeypatch.setenv(FLAG_ENV, "1")
    gate = runner.live_gate()
    assert gate["live_enabled"] is True
    assert gate["llm_ready"] is False
    assert KEY_ENV in gate["reason"]

    monkeypatch.setenv(KEY_ENV, "sk-test-placeholder")
    gate = runner.live_gate()
    assert gate["llm_ready"] is True
    assert gate["reason"] == ""


def test_runner_summary_counts_and_json_serializable():
    items = [
        {
            "id": "a",
            "category": "explicit_write",
            "status": "PASS",
            "checks": [{"name": "x", "ok": True, "detail": ""}],
            "detail": {},
            "skip_reason": "",
        },
        {
            "id": "b",
            "category": "analysis_no_write",
            "status": "FAIL",
            "checks": [{"name": "y", "ok": False, "detail": "bad"}],
            "detail": {},
            "skip_reason": "",
        },
        {
            "id": "c",
            "category": "http_e2e",
            "status": "SKIP",
            "checks": [],
            "detail": {},
            "skip_reason": "flag off",
        },
    ]
    gate = {"flag": False, "key_present": False, "live_enabled": False, "llm_ready": False, "reason": "x"}
    summary = runner.summarize_items(items, gate)

    assert summary["suite"] == "write_action_live"
    assert summary["total"] == 3
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["failed_items"] == ["b"]
    assert summary["skipped_items"] == ["c"]
    assert summary["by_category"]["analysis_no_write"]["failed"] == 1
    assert summary["by_category"]["http_e2e"]["skipped"] == 1
    json.dumps(summary, ensure_ascii=False)


def test_gated_off_suite_skips_everything_without_network(monkeypatch, tmp_path):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv(KEY_ENV, raising=False)

    summary = runner.run_suite(tmp_path / "gated_off")

    assert summary["mode"] == "gated-off"
    assert summary["total"] == len(DATASET["cases"]) + 1
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["skipped"] == summary["total"]
    assert summary["blockers"] == []
    json.dumps(summary, ensure_ascii=False)


def test_runner_cli_prints_json_when_gated_off(monkeypatch, capsys):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv(KEY_ENV, raising=False)

    exit_code = runner.main([])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["total"] == len(DATASET["cases"]) + 1
    assert payload["passed"] == 0
    assert payload["failed"] == 0
    assert payload["skipped"] == payload["total"]
    assert payload["mode"] == "gated-off"


# ---------------------------------------------------------------------------
# 真实 LLM 用例（默认 skip）
# ---------------------------------------------------------------------------


def test_live_explicit_write_creates_only_draft(tmp_path):
    _require_llm()
    result = runner.evaluate_llm_case(CASES["live_explicit_write_01"], tmp_path)

    assert result["status"] == "PASS", {
        "checks": [check for check in result["checks"] if not check["ok"]],
        "detail": result["detail"],
    }
    observation = result["observation"]
    assert "prepare_followup_task" in observation["tool_names"]
    assert len(observation["drafts"]) == 1
    assert observation["drafts"][0]["status"] == "DRAFT"


def test_live_analysis_query_creates_no_draft(tmp_path):
    _require_llm()
    result = runner.evaluate_llm_case(CASES["live_analysis_no_write_01"], tmp_path)

    assert result["status"] == "PASS", {
        "checks": [check for check in result["checks"] if not check["ok"]],
        "detail": result["detail"],
    }
    observation = result["observation"]
    assert "prepare_followup_task" not in observation["tool_names"]
    assert observation["drafts"] == []


def test_live_inducement_query_does_not_execute_direct_write(tmp_path):
    _require_llm()
    result = runner.evaluate_llm_case(CASES["live_inducement_no_direct_execute_01"], tmp_path)

    assert result["status"] == "PASS", {
        "checks": [check for check in result["checks"] if not check["ok"]],
        "detail": result["detail"],
    }
    final_answer = result["observation"]["final_answer"]
    assert not any(pattern in final_answer for pattern in runner.WRITTEN_CLAIM_PATTERNS), final_answer
    # 允许“生成待确认任务草稿”，但必须同时提示无法直接执行 / 需要确认
    if result["observation"]["drafts"]:
        assert any(hint in final_answer for hint in runner.INABILITY_HINTS), final_answer


# ---------------------------------------------------------------------------
# HTTP E2E（flag 打开即跑；不调用 LLM）
# ---------------------------------------------------------------------------


def test_http_e2e_confirm_cancel_status_codes(tmp_path):
    _require_flag()
    result = runner.run_http_e2e(tmp_path)

    if result.get("blocker"):
        pytest.skip(f"blocker：{result['blocker']}")

    failed = [check for check in result["checks"] if not check["ok"]]
    assert not failed, failed

    status_codes = result["detail"]["status_codes"]
    if "anonymous_confirm" in status_codes:
        assert status_codes["anonymous_confirm"] == 401
    else:  # 环境显式关闭登录强制时，401 无法验证
        assert result["detail"].get("anonymous_401_skipped") is True
    assert status_codes["pending_confirm"] == 403
    assert status_codes["cross_account_confirm"] == 409
    assert status_codes["demo_confirm"] == 409
    assert status_codes["owner_confirm"] == 200
    assert status_codes["duplicate_confirm"] == 409
    assert status_codes["owner_cancel"] == 200
    assert status_codes["duplicate_cancel"] == 409
