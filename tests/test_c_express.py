"""快递100适配层：签名、状态归一化、缓存与未配置边界。"""
from __future__ import annotations

import hashlib
import json
import urllib.parse

import pytest

from rag_demo.c_end import express


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._raw


@pytest.fixture(autouse=True)
def clean_express(monkeypatch):
    monkeypatch.setenv("QIANKE_KUAIDI100_CUSTOMER", "test-customer")
    monkeypatch.setenv("QIANKE_KUAIDI100_KEY", "test-key")
    express._CACHE.clear()
    yield
    express._CACHE.clear()


def test_unconfigured_returns_503(monkeypatch):
    monkeypatch.delenv("QIANKE_KUAIDI100_CUSTOMER")
    with pytest.raises(express.ExpressError) as exc:
        express.query_tracking("SF", "SF123456789")
    assert exc.value.code == "EXPRESS_NOT_CONFIGURED"
    assert exc.value.status_code == 503


def test_carrier_mapping_and_unknown():
    assert express.normalize_carrier("SF") == "shunfeng"
    assert express.normalize_carrier("中通") == "zhongtong"
    assert express.normalize_carrier("customcarrier") == "customcarrier"
    with pytest.raises(express.ExpressError) as exc:
        express.normalize_carrier("某某快递")
    assert exc.value.code == "UNSUPPORTED_CARRIER"


def test_query_uses_signed_request_and_normalizes(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["data"] = request.data
        captured["timeout"] = timeout
        return _FakeResponse({
            "status": "200",
            "state": "5",
            "data": [
                {"ftime": "2026-11-10 09:00:00", "context": "快件派送中"},
            ],
        })

    monkeypatch.setattr(express.urllib.request, "urlopen", fake_urlopen)
    result = express.query_tracking("SF", "SF123456789")
    assert result["state"] == "5"
    assert result["state_text"] == "派送中"
    assert result["events"][0]["text"] == "快件派送中"
    assert result["from_cache"] is False

    body = urllib.parse.parse_qs(captured["data"].decode("utf-8"))
    param = body["param"][0]
    expected_sign = hashlib.md5(
        f"{param}test-keytest-customer".encode("utf-8")
    ).hexdigest().upper()
    assert body["customer"] == ["test-customer"]
    assert body["sign"] == [expected_sign]
    assert json.loads(param)["com"] == "shunfeng"


def test_query_cache_avoids_second_upstream_call(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        return _FakeResponse({"status": "200", "state": "3", "data": []})

    monkeypatch.setattr(express.urllib.request, "urlopen", fake_urlopen)
    first = express.query_tracking("SF", "SF987654321")
    second = express.query_tracking("SF", "SF987654321")
    assert first["from_cache"] is False
    assert second["from_cache"] is True
    assert calls["n"] == 1


def test_provider_failure_is_structured(monkeypatch):
    def fake_urlopen(request, timeout):
        return _FakeResponse({"status": "400", "message": "单号不存在"})

    monkeypatch.setattr(express.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(express.ExpressError) as exc:
        express.query_tracking("SF", "SF000000001")
    assert exc.value.code == "EXPRESS_QUERY_FAILED"
    assert "单号不存在" in exc.value.message
