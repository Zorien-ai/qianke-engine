# -*- coding: utf-8 -*-
"""离线评测纯函数测试（不连库、不调 API）。"""
from rag_demo.eval_utils import (
    JUDGE_SYSTEM_PROMPT,
    build_judge_messages,
    excerpt,
    parse_judge_json,
    render_markdown_report,
    source_recall,
    summarize_results,
    unique_sources,
)


def test_parse_judge_json_valid_plain():
    assert parse_judge_json('{"score": 1, "reason": "符合"}') == {"score": 1, "reason": "符合"}
    assert parse_judge_json('{"score": 0, "reason": "编造数字"}') == {"score": 0, "reason": "编造数字"}


def test_parse_judge_json_fenced_and_noisy():
    raw = '好的，结果如下：\n```json\n{"score": 1, "reason": "引用完整"}\n```\n以上。'
    assert parse_judge_json(raw) == {"score": 1, "reason": "引用完整"}


def test_parse_judge_json_accepts_string_score():
    assert parse_judge_json('{"score": "1", "reason": "ok"}') == {"score": 1, "reason": "ok"}


def test_parse_judge_json_rejects_invalid():
    assert parse_judge_json("not json") is None
    assert parse_judge_json('{"score": 2, "reason": "out of range"}') is None
    assert parse_judge_json('{"score": true, "reason": "bool"}') is None
    assert parse_judge_json('{"reason": "missing score"}') is None


def test_build_judge_messages_contains_three_parts():
    item = {"question": "高价值用户怎么定义", "acceptance": "引用近90天前20%"}
    messages = build_judge_messages(item, "回答内容")
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == JUDGE_SYSTEM_PROMPT
    assert "高价值用户怎么定义" in messages[1]["content"]
    assert "回答内容" in messages[1]["content"]
    assert "引用近90天前20%" in messages[1]["content"]


def test_source_recall_partial_and_missing_expected():
    recall = source_recall(["user_profile", "tag_definitions.md"], ["user_profile", "user_profile", "segmentation.md"])
    assert recall["expected"] == ["user_profile", "tag_definitions.md"]
    assert recall["actual"] == ["user_profile", "segmentation.md"]
    assert recall["hit"] == ["user_profile"]
    assert recall["missing"] == ["tag_definitions.md"]
    assert recall["recall"] == 0.5

    empty = source_recall([], ["user_profile"])
    assert empty["recall"] is None
    assert empty["expected"] == []


def test_unique_sources_keeps_order():
    assert unique_sources(["a", "", "b", "a", None, "c"]) == ["a", "b", "c"]


def test_summarize_results_and_modules():
    results = [
        {
            "id": "A", "module": "运营", "score": 1, "judge_error": None, "answer_error": None,
            "elapsed_s": 10.0, "source_recall": {"expected": ["user_profile"], "hit": ["user_profile"], "actual": ["user_profile"], "recall": 1.0},
        },
        {
            "id": "B", "module": "运营", "score": 0, "judge_error": None, "answer_error": None,
            "elapsed_s": 20.0, "source_recall": {"expected": ["a.md", "b.md"], "hit": ["a.md"], "actual": ["a.md"], "recall": 0.5},
        },
        {
            "id": "C", "module": "边界", "score": None, "judge_error": "bad json", "answer_error": None,
            "elapsed_s": 5.0, "source_recall": {"expected": [], "hit": [], "actual": [], "recall": None},
        },
    ]
    summary = summarize_results(results)
    assert summary["total"] == 3
    assert summary["judged"] == 2
    assert summary["passed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["coverage"] == 2 / 3
    assert summary["judge_errors"] == 1
    assert summary["source_recall_avg"] == 0.75
    assert summary["source_recall_micro"] == 2 / 3
    assert summary["modules"]["运营"]["pass_rate"] == 0.5
    assert summary["modules"]["边界"]["judged"] == 0
    assert summary["modules"]["边界"]["pass_rate"] is None


def test_render_markdown_report_contains_sections_and_failure():
    results = [
        {
            "id": "B", "module": "边界", "question": "会员等级分布", "type": "gap",
            "acceptance": "说明数据缺失，不得编造", "expect_sources": [], "answer": "没有数据",
            "actual_sources": [], "source_recall": {"expected": [], "actual": [], "hit": [], "missing": [], "recall": None},
            "route": "rag", "elapsed_s": 12.3, "score": 0,
            "judge_reason": "回答编造了 2341 位用户", "judge_raw": '{"score":0}', "judge_error": None, "answer_error": None,
        }
    ]
    summary = summarize_results(results)
    text = render_markdown_report(
        results=results, summary=summary, dataset="demo", judge_model="deepseek-chat",
        questions_path="q.json", started_at="2026-10-18 18:00:00", elapsed_total=12.3,
    )
    assert "# 离线评测报告" in text
    assert "## 总体通过率" in text
    assert "## 分模块通过率" in text
    assert "## 来源召回明细" in text
    assert "## 失败案例复盘" in text
    assert "回答编造了 2341 位用户" in text
    assert "0.0%" in text


def test_excerpt_truncates():
    assert excerpt("abc", 10) == "abc"
    long = "x" * 30
    out = excerpt(long, 10)
    assert out.endswith("…")
    assert len(out) == 11
