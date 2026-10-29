# -*- coding: utf-8 -*-
"""B 端受控写 Eval 契约 + 确定性执行测试（不调用真实 LLM / 网络）。

对应任务 task-34：
- 数据集契约：7 个必需覆盖维度、意图标签、账号矩阵、coverage 索引；
- Eval runner：18 个确定性 case 全量执行 + JSON 摘要 + pass_rate；
- 产品契约：SYSTEM_PROMPT 写意图门槛、Tool Contract 的“只出 DRAFT”语义；
- 反证：故意破坏期望时 runner 必须判 FAIL（防止判分逻辑空转）。
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).parent / "evals" / "agent" / "write_action"


def _load_runner():
    """用唯一模块名加载本目录 runner，避免与其它 eval 目录的 runner.py 撞名。"""
    module_name = "write_action_eval_runner"
    spec = importlib.util.spec_from_file_location(module_name, EVAL_DIR / "runner.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 runner：{EVAL_DIR / 'runner.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()

from rag_demo.agent import actions, loop  # noqa: E402
from rag_demo.agent.registry import get_tool_contracts, get_tool_schemas  # noqa: E402

DATASET = runner.load_dataset()
CASES = DATASET["cases"]
CASES_BY_ID = {case["id"]: case for case in CASES}

REQUIRED_SCENARIO_CATEGORIES = {
    "no_write_intent",
    "explicit_write_intent",
    "hitl_confirm",
    "hitl_duplicate_confirm",
    "hitl_cross_account",
    "hitl_cancel",
    "permission_allowed_roles",
    "permission_cs",
    "permission_guest",
    "permission_demo",
    "write_isolation",
}


# ---------------------------------------------------------------------------
# 数据集契约
# ---------------------------------------------------------------------------


def test_dataset_metadata_declares_deterministic_suite():
    assert DATASET["version"] == "agent-write-action-eval-v1"
    assert DATASET["suite"] == "write_action"
    assert DATASET["status"] == "deterministic"
    assert DATASET["baseline"] == "not_required"
    assert DATASET["llm"] == "scripted"
    assert DATASET["network"] == "none"
    assert DATASET["dataset"] == "test"
    assert DATASET["related_doc"] == "docs/agent-write-action-eval.md"
    assert DATASET["contract_doc"] == "docs/agent-write-action.md"
    assert DATASET["tool"] == "prepare_followup_task"
    assert DATASET["action_type"] == "followup_task"


def test_dataset_passes_runner_validator():
    assert runner.validate_dataset(DATASET) == []


def test_dataset_case_ids_unique_and_scenarios_known():
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        assert case["scenario"] in runner.SCENARIOS, case["id"]
        assert case["category"] in REQUIRED_SCENARIO_CATEGORIES, case["id"]
    assert len(CASES) == 18


def test_required_coverage_dimensions_are_present_and_reference_cases():
    coverage = DATASET["coverage"]
    assert set(runner.REQUIRED_COVERAGE) <= set(coverage)
    for dimension, case_ids in coverage.items():
        assert case_ids, f"coverage.{dimension} 为空"
        for case_id in case_ids:
            assert case_id in CASES_BY_ID, f"coverage.{dimension} 引用不存在的 case：{case_id}"
    covered = {case_id for case_ids in coverage.values() for case_id in case_ids}
    assert covered == set(CASES_BY_ID), "每个 case 都必须落入明确的覆盖维度"


def test_required_acceptance_points_have_dedicated_cases():
    """task-34 的 7 个验收点都必须有真实执行的 case（不是只写在文档里）。"""
    required = {
        "no_draft_without_intent": {"no_write_intent"},
        "draft_with_explicit_intent": {"explicit_write_intent"},
        "draft_to_confirmed": {"hitl_confirm"},
        "permission_demo_cs_guest": {"permission_cs", "permission_guest", "permission_demo"},
        "cross_account_confirm_denied": {"hitl_cross_account"},
        "duplicate_confirm_denied": {"hitl_duplicate_confirm"},
        "only_agent_action_table_written": {"write_isolation"},
    }
    for dimension, categories in required.items():
        referenced = {
            CASES_BY_ID[case_id]["category"]
            for case_id in DATASET["coverage"][dimension]
        }
        assert categories <= referenced, f"{dimension} 未覆盖 {categories - referenced}"


# ---------------------------------------------------------------------------
# 意图规则与产品契约
# ---------------------------------------------------------------------------


def test_intent_rule_only_flags_explicit_create_task_requests():
    assert runner.has_explicit_write_intent("把召回沉默客安排成跟进任务") is True
    assert runner.has_explicit_write_intent("给沉默客创建任务并指派负责人") is True
    assert runner.has_explicit_write_intent("这个结论记录成待办") is True
    # 隐式/顺带提一句不算明确要求创建任务
    assert runner.has_explicit_write_intent("沉默客流失挺严重的，看来要跟进一下") is False
    assert runner.has_explicit_write_intent("统计沉默客有多少人") is False
    assert runner.has_explicit_write_intent("沉默客占比是多少") is False


def test_dataset_intent_labels_match_deterministic_rule():
    for case in CASES:
        if case["category"] == "no_write_intent":
            assert not runner.has_explicit_write_intent(case["params"]["query"]), case["id"]
            assert case["expect"]["followup_drafts"] == 0
            assert case["expect"]["write_tool_results"] == 0
        if case["category"] == "explicit_write_intent":
            assert runner.has_explicit_write_intent(case["params"]["query"]), case["id"]
            assert case["expect"]["followup_drafts"] >= 1
            assert case["expect"]["write_tool_results"] >= 1


def test_system_prompt_declares_write_gating_rule():
    prompt = loop.SYSTEM_PROMPT
    assert "prepare_followup_task" in prompt
    assert "只有用户明确要求" in prompt
    assert "不要主动创建任务" in prompt
    assert "确认后才会写入" in prompt
    for marker in ("创建任务", "安排跟进", "记录成待办"):
        assert marker in prompt, f"System Prompt 未覆盖显式写意图措辞：{marker}"


def test_tool_contract_declares_draft_only_semantics():
    schemas = get_tool_schemas()
    assert runner.TOOL_NAME in schemas
    schema = schemas[runner.TOOL_NAME]
    assert schema["required"] == ["title"]
    properties = schema["properties"]
    assert properties["title"]["minLength"] == 2
    assert properties["title"]["maxLength"] == 80
    assert properties["description"]["maxLength"] == 1000
    assert properties["priority"]["default"] == "normal"
    assert properties["priority"]["pattern"] == "^(low|normal|high)$"

    contracts = get_tool_contracts()
    assert runner.TOOL_NAME in contracts
    contract = contracts[runner.TOOL_NAME]
    assert contract.name == runner.TOOL_NAME
    assert callable(contract.fn)
    assert "草稿" in (contract.description or "")
    assert "不会直接写入正式任务" in (contract.description or "")


def test_write_tool_requires_action_scope_context():
    """没有 action_scope 上下文时，写 Tool 必须结构化拒绝，不能落 DRAFT。"""
    payload = runner.prepare_followup_task.invoke(
        {"title": "无上下文任务", "description": "", "priority": "normal"}
    )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "ACTION_CONTEXT_MISSING"


# ---------------------------------------------------------------------------
# Eval 执行（确定性，tmp_path + QIANKE_AGENT_ACTION_DB + actions._DB_PATH）
# ---------------------------------------------------------------------------


def test_eval_suite_all_cases_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_AGENT_ACTION_DB", str(tmp_path / "base_actions.sqlite"))
    monkeypatch.setattr(actions, "_DB_PATH", None)

    summary = runner.run_suite(tmp_path / "eval")

    assert summary["suite"] == "write_action"
    assert summary["version"] == "agent-write-action-eval-v1"
    assert summary["deterministic"] is True
    assert summary["llm"] == "scripted"
    assert summary["network"] == "none"
    assert summary["total"] == len(CASES)
    assert summary["failed"] == 0, summary["failed_cases"]
    assert summary["passed"] == summary["total"]
    assert summary["pass_rate"] == 1.0
    assert summary["check_total"] > 0
    assert summary["check_passed"] == summary["check_total"]
    assert sum(
        bucket["total"] for bucket in summary["by_category"].values()
    ) == summary["total"]
    assert {row["id"]: row["status"] for row in summary["cases"]} == {
        case["id"]: "PASS" for case in CASES
    }
    # JSON 摘要可序列化（文档/CI 直接消费）
    json.dumps(summary, ensure_ascii=False)
    # runner 必须还原进程级状态，避免污染其它测试
    assert actions._DB_PATH is None
    assert os.environ["QIANKE_AGENT_ACTION_DB"] == str(tmp_path / "base_actions.sqlite")


def test_eval_suite_exposes_expected_skill_metrics(tmp_path):
    summary = runner.run_suite(tmp_path / "eval_metrics")
    by_category = summary["by_category"]

    for category in (
        "no_write_intent",
        "explicit_write_intent",
        "hitl_confirm",
        "hitl_duplicate_confirm",
        "hitl_cross_account",
        "permission_cs",
        "permission_guest",
        "permission_demo",
        "write_isolation",
    ):
        assert category in by_category, category
        assert by_category[category]["pass_rate"] == 1.0, category

    isolation_case = next(
        row for row in summary["cases"] if row["id"] == "wa_isolation_01"
    )
    detail = isolation_case["detail"]
    assert detail["write_targets"] == ["agent_action"]
    assert detail["business_tables"] == ["orders", "customers", "coupon_grants"]
    assert detail["action_db_tables"] == ["agent_action"]


def test_runner_and_validator_detect_broken_expectation(tmp_path):
    """反证：把期望改成错误值后 runner 必须 FAIL，避免“永远通过”的空判分。"""
    broken = copy.deepcopy(DATASET)
    target = next(case for case in broken["cases"] if case["id"] == "wa_explicit_01")
    target["expect"]["draft_fields"]["title"] = "被篡改的标题"

    summary = runner.run_suite(tmp_path / "eval_broken", broken)

    assert summary["total"] == len(CASES)
    assert summary["failed"] == 1
    assert summary["passed"] == len(CASES) - 1
    assert summary["pass_rate"] == round((len(CASES) - 1) / len(CASES), 4)
    assert summary["failed_cases"] == ["wa_explicit_01"]
    failed_case = next(row for row in summary["cases"] if row["status"] == "FAIL")
    failed_checks = [check["name"] for check in failed_case["checks"] if not check["ok"]]
    assert "draft.title" in failed_checks


def test_validator_rejects_no_intent_case_that_expects_draft():
    broken = copy.deepcopy(DATASET)
    target = next(case for case in broken["cases"] if case["category"] == "no_write_intent")
    target["expect"]["followup_drafts"] = 1

    problems = runner.validate_dataset(broken)

    assert any("无写意图用例必须期望 0 个 DRAFT" in problem for problem in problems)
    with pytest.raises(ValueError, match="数据集非法"):
        runner.run_suite(Path("unused-eval-workdir"), broken)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_validate_only_prints_json(capsys):
    exit_code = runner.main(["--validate-only"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["suite"] == "write_action"
    assert payload["valid"] is True
    assert payload["problems"] == []
    assert payload["total"] == len(CASES)


def test_cli_full_run_prints_json_summary_with_pass_rate(capsys):
    exit_code = runner.main([])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["total"] == len(CASES)
    assert payload["failed"] == 0
    assert payload["pass_rate"] == 1.0
    assert payload["deterministic"] is True
