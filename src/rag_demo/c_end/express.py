"""快递查询适配层：当前实现快递100，统一返回 C 端可展示的物流结构。

未配置 QIANKE_KUAIDI100_CUSTOMER / QIANKE_KUAIDI100_KEY 时明确返回
EXPRESS_NOT_CONFIGURED，绝不返回伪造轨迹。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

KUAIDI100_QUERY_URL = "https://poll.kuaidi100.com/poll/query.do"
CACHE_TTL_SECONDS = 300

_CARRIER_MAP = {
    "SF": "shunfeng",
    "SHUNFENG": "shunfeng",
    "顺丰": "shunfeng",
    "ZTO": "zhongtong",
    "ZHONGTONG": "zhongtong",
    "中通": "zhongtong",
    "YTO": "yuantong",
    "YUANTONG": "yuantong",
    "圆通": "yuantong",
    "STO": "shentong",
    "SHENTONG": "shentong",
    "申通": "shentong",
    "YUNDA": "yunda",
    "韵达": "yunda",
    "JD": "jd",
    "京东": "jd",
    "EMS": "ems",
    "POST": "youzhengguonei",
    "邮政": "youzhengguonei",
}
_STATE_TEXT = {
    "0": "在途",
    "1": "已揽收",
    "2": "疑难件",
    "3": "已签收",
    "4": "退签",
    "5": "派送中",
    "6": "退回",
    "7": "转单",
    "8": "清关",
    "14": "拒签",
}


class ExpressError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _customer() -> str:
    return (os.environ.get("QIANKE_KUAIDI100_CUSTOMER") or "").strip()


def _key() -> str:
    return (os.environ.get("QIANKE_KUAIDI100_KEY") or "").strip()


def is_configured() -> bool:
    return bool(_customer() and _key())


def normalize_carrier(carrier: str | None) -> str:
    raw = str(carrier or "").strip()
    if not raw:
        raise ExpressError("CARRIER_MISSING", "订单没有承运商信息", 400)
    mapped = _CARRIER_MAP.get(raw.upper()) or _CARRIER_MAP.get(raw)
    if mapped:
        return mapped
    if raw.isascii() and raw.replace("-", "").isalnum() and 2 <= len(raw) <= 20:
        return raw.lower()
    raise ExpressError("UNSUPPORTED_CARRIER", f"暂不支持承运商 {raw}", 400)


def _timeout() -> float:
    try:
        return max(1.0, min(float(os.environ.get("QIANKE_KUAIDI100_TIMEOUT") or "8"), 20.0))
    except ValueError:
        return 8.0


_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(carrier_code: str, tracking_no: str) -> dict[str, Any] | None:
    key = (carrier_code, tracking_no)
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is None or item[0] <= now:
            _CACHE.pop(key, None)
            return None
        return dict(item[1], from_cache=True)


def _cache_put(carrier_code: str, tracking_no: str, value: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _CACHE[(carrier_code, tracking_no)] = (time.monotonic() + CACHE_TTL_SECONDS, value)
        if len(_CACHE) > 500:
            cutoff = time.monotonic()
            for key, (expires, _) in list(_CACHE.items()):
                if expires <= cutoff:
                    _CACHE.pop(key, None)


def _normalize_events(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []
    events: list[dict[str, str]] = []
    for item in data[:20]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("context") or item.get("status") or "").strip()
        at = str(item.get("ftime") or item.get("time") or "").strip()
        if text:
            events.append({"time": at, "text": text})
    return events


def _query_remote(carrier_code: str, tracking_no: str) -> dict[str, Any]:
    customer = _customer()
    key = _key()
    if not customer or not key:
        raise ExpressError(
            "EXPRESS_NOT_CONFIGURED",
            "物流查询未配置快递100凭据",
            503,
        )
    param = json.dumps(
        {"com": carrier_code, "num": tracking_no, "resultv2": "1"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    sign = hashlib.md5(f"{param}{key}{customer}".encode("utf-8")).hexdigest().upper()
    body = urllib.parse.urlencode(
        {"customer": customer, "sign": sign, "param": param}
    ).encode("utf-8")
    request = urllib.request.Request(
        KUAIDI100_QUERY_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ExpressError("EXPRESS_UPSTREAM_UNAVAILABLE", "物流查询服务暂不可用", 502) from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ExpressError("EXPRESS_BAD_RESPONSE", "物流查询返回异常", 502) from exc
    if not isinstance(payload, dict) or str(payload.get("status")) != "200":
        raise ExpressError(
            "EXPRESS_QUERY_FAILED",
            str(payload.get("message") or "物流查询失败")[:120],
            502,
        )
    state = str(payload.get("state") if payload.get("state") is not None else "")
    normalized = {
        "provider": "kuaidi100",
        "carrier_code": carrier_code,
        "tracking_no": tracking_no,
        "state": state,
        "state_text": _STATE_TEXT.get(state, "物流状态未知"),
        "events": _normalize_events(payload.get("data")),
        "from_cache": False,
    }
    _cache_put(carrier_code, tracking_no, normalized)
    return normalized


def query_tracking(carrier: str | None, tracking_no: str) -> dict[str, Any]:
    """查询并归一化物流轨迹；调用方必须先确认订单归属。"""
    number = str(tracking_no or "").strip()
    if not (4 <= len(number) <= 64) or not all(ch.isalnum() or ch == "-" for ch in number):
        raise ExpressError("INVALID_TRACKING_NO", "运单号不合法", 400)
    carrier_code = normalize_carrier(carrier)
    cached = _cache_get(carrier_code, number)
    if cached is not None:
        return cached
    return _query_remote(carrier_code, number)
