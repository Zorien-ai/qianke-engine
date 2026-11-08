"""观察报告汇总逻辑测试。"""
from __future__ import annotations

from scripts.observation_report import summarize


def _row(at: str, ready: int = 200, done: float = 1.0, pending: float = 0.0) -> dict:
    return {
        "at": at, "ready_status": ready, "metrics_status": 200,
        "queue_done": done, "queue_pending": pending, "queue_dead": 0.0,
        "work_items_waiting_approval": 10.0, "work_items_stuck": 0.0,
    }


def test_summarize_in_progress():
    rows = [_row("2026-11-09T00:00:00+00:00"), _row("2026-11-09T01:00:00+00:00", done=5)]
    result = summarize(rows, required_seconds=86400)
    assert result["verdict"] == "IN_PROGRESS"
    assert result["samples"] == 2
    assert result["queue_done_delta"] == 4
    assert result["ready_rate"] == 1.0


def test_summarize_fails_on_unready_sample():
    rows = [_row("2026-11-09T00:00:00+00:00"), _row("2026-11-09T00:01:00+00:00", ready=0)]
    result = summarize(rows, required_seconds=60)
    assert result["verdict"] == "FAIL"
    assert result["ready_fail"] == 1


def test_summarize_passes_after_window():
    rows = [_row("2026-11-09T00:00:00+00:00"), _row("2026-11-10T00:00:01+00:00")]
    result = summarize(rows, required_seconds=86400)
    assert result["verdict"] == "PASS"
