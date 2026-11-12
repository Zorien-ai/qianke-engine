"""C 端消费者注册/登录的短信验证码与限流。

生产接入真实短信供应商时，替换 `_send_via_provider`，保持 `send_code` /
`verify_code` 契约不变。当前默认开发模式：固定验证码，页面明确标注仅演示。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from typing import Any

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
CODE_TTL_SECONDS = 300
CODE_MAX_ATTEMPTS = 5
SEND_COOLDOWN_SECONDS = 60
DAILY_PHONE_LIMIT = 10
DAILY_IP_LIMIT = 50

_DEV_CODE = os.environ.get("QIANKE_C_SMS_DEV_CODE", "123456").strip() or "123456"
_DEV_MODE = os.environ.get("QIANKE_C_SMS_DEV_MODE", "1") != "0"
_SECRET = os.environ.get("QIANKE_C_SMS_SECRET", "qianke-c-sms-dev-secret").encode("utf-8")

_lock = threading.Lock()
_codes: dict[str, dict[str, Any]] = {}
_last_sent: dict[str, float] = {}
_daily_phone: dict[str, list[float]] = {}
_daily_ip: dict[str, list[float]] = {}


def is_dev_mode() -> bool:
    return _DEV_MODE


def normalize_phone(phone: str) -> str:
    value = re.sub(r"[\s-]", "", str(phone or ""))
    if not _PHONE_RE.fullmatch(value):
        raise ValueError("请输入有效的 11 位手机号")
    return value


def _hash(phone: str, code: str) -> str:
    return hmac.new(_SECRET, f"{phone}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _day_key(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def _prune_day(items: list[float], now: float) -> list[float]:
    cutoff = now - 86400
    return [item for item in items if item >= cutoff]


def _send_via_provider(phone: str, code: str) -> None:
    """真实短信供应商适配点。

    当前项目没有配置供应商凭证；生产部署时必须实现这里，不能继续使用默认码。
    """
    provider = os.environ.get("QIANKE_SMS_PROVIDER", "").strip()
    if provider in ("", "dev"):
        if _DEV_MODE:
            return
        raise RuntimeError("短信供应商未配置：请实现 QIANKE_SMS_PROVIDER 适配器")
    raise RuntimeError("短信供应商未配置：请实现 QIANKE_SMS_PROVIDER 适配器")


def send_code(phone: str, *, client_ip: str = "") -> dict[str, Any]:
    phone = normalize_phone(phone)
    now = time.time()
    with _lock:
        last = _last_sent.get(phone, 0.0)
        if now - last < SEND_COOLDOWN_SECONDS:
            retry = int(SEND_COOLDOWN_SECONDS - (now - last)) + 1
            raise ValueError(f"验证码发送过于频繁，请 {retry} 秒后再试")
        phone_times = _prune_day(_daily_phone.get(phone, []), now)
        if len(phone_times) >= DAILY_PHONE_LIMIT:
            raise ValueError("该手机号今日验证码次数已达上限，请明天再试")
        if client_ip:
            ip_times = _prune_day(_daily_ip.get(client_ip, []), now)
            if len(ip_times) >= DAILY_IP_LIMIT:
                raise ValueError("当前网络今日验证码次数已达上限，请明天再试")
        code = _DEV_CODE if _DEV_MODE else f"{secrets.randbelow(1000000):06d}"
        _codes[phone] = {
            "hash": _hash(phone, code),
            "expires_at": now + CODE_TTL_SECONDS,
            "attempts": 0,
        }
        _last_sent[phone] = now
        phone_times.append(now)
        _daily_phone[phone] = phone_times
        if client_ip:
            ip_times.append(now)
            _daily_ip[client_ip] = ip_times
    try:
        _send_via_provider(phone, code)
    except Exception:
        with _lock:
            _codes.pop(phone, None)
        raise
    return {
        "ok": True,
        "cooldown_seconds": SEND_COOLDOWN_SECONDS,
        "expires_in": CODE_TTL_SECONDS,
        "dev_mode": _DEV_MODE,
        # 仅本地演示模式下发；生产模式绝不返回验证码。
        "dev_code": code if _DEV_MODE else None,
    }


def verify_code(phone: str, code: str) -> bool:
    phone = normalize_phone(phone)
    code = str(code or "").strip()
    if not code:
        return False
    now = time.time()
    with _lock:
        item = _codes.get(phone)
        if item is None:
            return False
        if item["expires_at"] < now:
            _codes.pop(phone, None)
            return False
        item["attempts"] += 1
        if item["attempts"] > CODE_MAX_ATTEMPTS:
            _codes.pop(phone, None)
            return False
        if not hmac.compare_digest(item["hash"], _hash(phone, code)):
            return False
        _codes.pop(phone, None)
        return True


def reset_for_tests() -> None:
    with _lock:
        _codes.clear()
        _last_sent.clear()
        _daily_phone.clear()
        _daily_ip.clear()
