# -*- coding: utf-8 -*-
"""企业侧离线评测：题库校验、租户隔离、运行结果落盘与读取。"""
import json

import pytest

from rag_demo import tenant_eval


@pytest.fixture()
def eval_root(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_eval, "EVAL_ROOT", tmp_path / "eval")
    tenant_eval.ACTIVE_RUNS.clear()
    return tmp_path / "eval"


def _questions(n=2):
    return [
        {
            "id": f"Q-{i}",
            "module": "运营/市场",
            "question": f"问题 {i}",
            "acceptance": f"验收 {i}",
            "expect_sources": ["user_profile"],
        }
        for i in range(n)
    ]


def test_validate_questions_normalizes_and_trims():
    out = tenant_eval.validate_questions([
        {"id": " Q1 ", "question": " 客人 ", "acceptance": " 给答案 ", "module": ""},
        {"id": "Q2", "question": "q2", "acceptance": "a2", "expect_sources": [" x ", ""]},
    ])
    assert out[0]["id"] == "Q1"
    assert out[0]["module"] == "自定义"
    assert out[1]["expect_sources"] == ["x"]
    assert len(out) == 2


@pytest.mark.parametrize("raw", [[], {}, {"questions": []}, "not-list"])
def test_validate_questions_rejects_empty_or_non_list(raw):
    with pytest.raises(tenant_eval.EvalInputError):
        tenant_eval.validate_questions(raw)


def test_validate_questions_rejects_missing_duplicate_and_limits():
    with pytest.raises(tenant_eval.EvalInputError, match="缺少"):
        tenant_eval.validate_questions([{"id": "Q1", "question": "q"}])
    with pytest.raises(tenant_eval.EvalInputError, match="题号重复"):
        tenant_eval.validate_questions([
            {"id": "Q1", "question": "q", "acceptance": "a"},
            {"id": "Q1", "question": "q2", "acceptance": "a2"},
        ])
    with pytest.raises(tenant_eval.EvalInputError, match="最多"):
        tenant_eval.validate_questions(_questions(tenant_eval.MAX_QUESTIONS + 1))


def test_question_sets_isolated_by_dataset(eval_root):
    saved = tenant_eval.save_question_set("ent_101", "A 题库", _questions())
    assert tenant_eval.list_question_sets("ent_101")[0]["id"] == saved["id"]
    assert tenant_eval.list_question_sets("ent_102") == []
    with pytest.raises(FileNotFoundError):
        tenant_eval.load_question_set("ent_102", saved["id"])


def test_question_set_roundtrip_keeps_questions(eval_root):
    saved = tenant_eval.save_question_set("ent_101", "roundtrip", _questions(3))
    loaded = tenant_eval.load_question_set("ent_101", saved["id"])
    assert loaded["name"] == "roundtrip"
    assert len(loaded["questions"]) == 3
    assert loaded["questions"][0]["question"] == "问题 0"


def test_create_run_and_read_result(eval_root):
    saved = tenant_eval.save_question_set("ent_101", "run", _questions(2))
    qset = tenant_eval.load_question_set("ent_101", saved["id"])
    meta = tenant_eval.create_run("ent_101", qset)
    tenant_eval.mark_active(meta["id"])
    results = [
        {
            "id": "Q-0", "module": "运营/市场", "question": "问题 0", "acceptance": "验收 0",
            "answer": "ok", "actual_sources": ["user_profile"], "source_recall": {"recall": 1.0},
            "route": "rag", "elapsed_s": 1.2, "score": 1, "judge_reason": "通过",
            "judge_error": None, "answer_error": None, "expect_sources": ["user_profile"],
        },
        {
            "id": "Q-1", "module": "运营/市场", "question": "问题 1", "acceptance": "验收 1",
            "answer": "bad", "actual_sources": [], "source_recall": {"recall": 0.0},
            "route": "rag", "elapsed_s": 2.3, "score": 0, "judge_reason": "编造数字",
            "judge_error": None, "answer_error": None, "expect_sources": ["user_profile"],
        },
    ]
    summary = {
        "total": 2, "judged": 2, "passed": 1, "pass_rate": 0.5, "coverage": 1.0,
        "judge_errors": 0, "answer_errors": 0, "source_recall_avg": 0.5,
        "source_recall_micro": 0.5, "source_cases": 2, "elapsed_avg": 1.75, "elapsed_total": 3.5,
        "modules": {"运营/市场": {"total": 2, "judged": 2, "passed": 1, "pass_rate": 0.5, "recall": 0.5}},
    }
    tenant_eval.persist_run_result("ent_101", meta["id"], {
        "started_at": "2026-01-01 00:00:00", "finished_at": "2026-01-01 00:00:04",
        "judge_model": "deepseek-chat", "elapsed_total_s": 3.5,
        "summary": summary, "results": results, "report_text": "# report",
    })
    tenant_eval.mark_inactive(meta["id"])

    data = tenant_eval.read_run("ent_101", meta["id"])
    assert data["run"]["status"] == "completed"
    assert data["summary"]["pass_rate"] == 0.5
    assert data["modules"][0]["passed"] == 1
    assert [f["id"] for f in data["failures"]] == ["Q-1"]
    assert data["failures"][0]["judge_reason"] == "编造数字"
    assert len(data["failures"][0]["answer_excerpt"]) <= 1601


def test_stale_running_run_is_marked_interrupted(eval_root):
    saved = tenant_eval.save_question_set("ent_101", "stale", _questions())
    meta = tenant_eval.create_run("ent_101", tenant_eval.load_question_set("ent_101", saved["id"]))
    tenant_eval.update_run_progress("ent_101", meta["id"], {"status": "running"})
    # 不 mark_active：模拟服务重启后内存任务丢失
    latest = tenant_eval.latest_run("ent_101")
    assert latest["status"] == "interrupted"
    assert "中断" in latest["error"]
