"""观察器必须携带 metrics token，否则队列统计会因 401 丢失。"""
from __future__ import annotations

from scripts import observe_control_pg as observer


def test_sample_sends_metrics_token(monkeypatch):
    calls = []

    def fake_get(url, timeout=5.0, headers=None):
        calls.append((url, headers))
        if url.endswith("/ready"):
            return 200, '{"status":"ok"}'
        return 200, 'qianke_queue_jobs{status="done"} 3\n'

    monkeypatch.setattr(observer, "_get", fake_get)
    monkeypatch.setattr(observer, "_metrics_token", lambda: "token-123")
    row = observer.sample("http://127.0.0.1:8000")
    assert row["ready_status"] == 200
    assert row["metrics_status"] == 200
    assert row["queue_done"] == 3.0
    assert calls[1] == ("http://127.0.0.1:8000/metrics", {"X-Metrics-Token": "token-123"})
