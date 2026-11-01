"""对账告警外部通道（通用 JSON Webhook）。

安全边界：
- URL/Token 只从环境变量读取，不接受请求参数，避免 SSRF/密钥从接口注入；
- 只支持 http/https；默认未配置时完全不发请求；
- 推送失败只记日志，不影响对账主流程。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

WEBHOOK_URL_ENV = "QIANKE_ALERT_WEBHOOK_URL"
WEBHOOK_TOKEN_ENV = "QIANKE_ALERT_WEBHOOK_TOKEN"
WEBHOOK_TIMEOUT_ENV = "QIANKE_ALERT_WEBHOOK_TIMEOUT_SECONDS"


def _timeout() -> float:
    try:
        value = float(os.environ.get(WEBHOOK_TIMEOUT_ENV, "3"))
    except (TypeError, ValueError):
        value = 3.0
    return max(0.5, min(value, 30.0))


def build_payload(
    *,
    run_id: str,
    trigger: str,
    checked: int,
    legacy: int,
    issues: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "event": "reconciliation.alert",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "trigger": trigger,
        "checked": int(checked),
        "legacy": int(legacy),
        "issue_count": len(issues),
        "alerts": [
            {
                "order_id": item.get("order_id"),
                "issue": item.get("issue"),
                "severity": item.get("severity"),
                "message": item.get("message"),
                "suggestion": item.get("suggestion"),
                "last_seen_at": item.get("last_seen_at"),
            }
            for item in alerts
        ],
    }


def _post_webhook(url: str, token: str | None, payload: dict[str, Any]) -> tuple[bool, int, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:  # noqa: S310 - env-trusted URL
            return True, int(response.status), ""
    except urllib.error.HTTPError as exc:
        return False, int(exc.code), f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - 外部通道失败不影响对账
        return False, 0, str(exc)


def deliver_reconciliation_alerts(
    *,
    run_id: str,
    trigger: str,
    checked: int,
    legacy: int,
    issues: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    url = (os.environ.get(WEBHOOK_URL_ENV) or "").strip()
    if not url:
        return {"sent": False, "reason": "NOT_CONFIGURED"}
    if not url.lower().startswith(("http://", "https://")):
        logger.warning("对账 Webhook URL 非 http/https，跳过推送")
        return {"sent": False, "reason": "INVALID_URL"}
    if not alerts:
        return {"sent": False, "reason": "NO_ALERTS"}
    payload = build_payload(
        run_id=run_id,
        trigger=trigger,
        checked=checked,
        legacy=legacy,
        issues=issues,
        alerts=alerts,
    )
    okay, status, error = _post_webhook(
        url,
        (os.environ.get(WEBHOOK_TOKEN_ENV) or "").strip() or None,
        payload,
    )
    if okay:
        logger.info("对账告警已推送 run=%s alerts=%s status=%s", run_id, len(alerts), status)
        return {"sent": True, "status": status, "alert_count": len(alerts)}
    logger.warning("对账告警推送失败 run=%s error=%s", run_id, error)
    return {"sent": False, "reason": "DELIVERY_FAILED", "error": error}
