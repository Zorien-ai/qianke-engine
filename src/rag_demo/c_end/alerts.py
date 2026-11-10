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
WEBHOOK_FORMAT_ENV = "QIANKE_ALERT_WEBHOOK_FORMAT"

_FORMATS = {"generic", "wecom", "dingtalk"}


def _format_name() -> str:
    name = (os.environ.get(WEBHOOK_FORMAT_ENV) or "generic").strip().lower()
    return name if name in _FORMATS else "generic"


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


def _markdown_text(payload: dict[str, Any]) -> str:
    lines = [
        "### 千客对账告警",
        f"> run `{payload.get('run_id')}` / {payload.get('trigger')} / "
        f"检查 {payload.get('checked')} 单 / 问题 {payload.get('issue_count')} 个",
    ]
    for item in (payload.get("alerts") or [])[:10]:
        severity = item.get("severity") or "WARNING"
        lines.append(f"- **{severity}** `{item.get('order_id')}`：{item.get('message')}")
        suggestion = str(item.get("suggestion") or "").strip()
        if suggestion:
            lines.append(f"  建议：{suggestion}")
    return "\n".join(lines)[:3800]


def format_payload(payload: dict[str, Any], fmt: str) -> dict[str, Any]:
    """把通用 payload 转成目标机器人格式；未知格式回退 generic。"""
    name = fmt if fmt in _FORMATS else "generic"
    if name == "wecom":
        return {"msgtype": "markdown", "markdown": {"content": _markdown_text(payload)}}
    if name == "dingtalk":
        return {
            "msgtype": "markdown",
            "markdown": {"title": "千客对账告警", "text": _markdown_text(payload)},
        }
    return payload


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
    fmt = _format_name()
    payload = format_payload(
        build_payload(
            run_id=run_id,
            trigger=trigger,
            checked=checked,
            legacy=legacy,
            issues=issues,
            alerts=alerts,
        ),
        fmt,
    )
    okay, status, error = _post_webhook(
        url,
        (os.environ.get(WEBHOOK_TOKEN_ENV) or "").strip() or None,
        payload,
    )
    if okay:
        logger.info(
            "对账告警已推送 run=%s alerts=%s format=%s status=%s",
            run_id,
            len(alerts),
            fmt,
            status,
        )
        return {"sent": True, "status": status, "alert_count": len(alerts), "format": fmt}
    logger.warning("对账告警推送失败 run=%s format=%s error=%s", run_id, fmt, error)
    return {"sent": False, "reason": "DELIVERY_FAILED", "error": error, "format": fmt}

# ---------------------------------------------------------------------------
# 库存告警：企业微信应用消息
# ---------------------------------------------------------------------------

INVENTORY_TOUSER_ENV = "QIANKE_INVENTORY_ALERT_WECOM_TOUSER"
INVENTORY_AGENT_ID_ENV = "QIANKE_INVENTORY_ALERT_WECOM_AGENT_ID"


def inventory_text(alerts: list[dict[str, Any]], *, limit: int = 20) -> str:
    lines = ["千客库存告警"]
    if alerts:
        lines.append(f"商家：{alerts[0].get('merchant_id') or '—'}")
    lines.append(f"低库存事件：{len(alerts)} 条")
    for item in alerts[:limit]:
        title = item.get("product_id") or "商品"
        spec = str(item.get("sku_spec") or "").strip()
        spec_text = f" / {spec}" if spec else ""
        lines.append(
            f"- {title}{spec_text}：可售 {item.get('available_qty') or 0}，"
            f"安全库存 {item.get('safety_stock') or 0}，建议补货 {item.get('reorder_qty') or 0} 件"
        )
    if len(alerts) > limit:
        lines.append(f"……其余 {len(alerts) - limit} 条见 B 工作台待发送队列")
    lines.append("请到 B 工作台确认处理；不是自动采购指令。")
    return "\n".join(lines)[:1200]


def deliver_inventory_alerts_wecom(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """通过企业微信应用消息推送库存告警；接收人必须显式配置。"""
    if not alerts:
        return {"sent": False, "reason": "NO_ALERTS"}
    recipient = (os.environ.get(INVENTORY_TOUSER_ENV) or "").strip()
    if not recipient:
        return {"sent": False, "reason": "NO_RECIPIENT"}
    try:
        from rag_demo.superagent import wecom_send

        if not wecom_send.configured():
            return {"sent": False, "reason": "NOT_CONFIGURED"}
        result = wecom_send.send_text(
            recipient,
            inventory_text(alerts),
            agent_id=(os.environ.get(INVENTORY_AGENT_ID_ENV) or "").strip() or None,
        )
    except Exception as exc:  # noqa: BLE001 - 外部通道失败不阻塞本地队列
        logger.warning("库存告警企业微信推送失败: %s", exc)
        return {"sent": False, "reason": "DELIVERY_FAILED", "error": str(exc)[:300]}
    if result.get("sent"):
        logger.info("库存告警企业微信推送成功 alerts=%s", len(alerts))
        return {**result, "channel": "wecom_app", "alert_count": len(alerts)}
    logger.warning("库存告警企业微信推送未成功: %s", result.get("reason"))
    return {**result, "channel": "wecom_app"}
