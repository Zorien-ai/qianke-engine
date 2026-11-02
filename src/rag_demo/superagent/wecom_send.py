"""企业微信应用主动消息（结果回写）。

需要：
- QIANKE_WECOM_CORP_ID
- QIANKE_WECOM_CORP_SECRET（应用 Secret）
- QIANKE_WECOM_AGENT_ID（应用 AgentId）
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)
_TOKEN_LOCK = threading.Lock()
_TOKEN: dict[str, Any] = {"value": "", "expires_at": 0.0}


def configured() -> bool:
    return all(
        (os.environ.get(key) or "").strip()
        for key in (
            "QIANKE_WECOM_CORP_ID",
            "QIANKE_WECOM_CORP_SECRET",
            "QIANKE_WECOM_AGENT_ID",
        )
    )


def _fallback_group_enabled() -> bool:
    if (os.environ.get("QIANKE_WECOM_REPLY_FALLBACK_GROUP") or "0").strip() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    return bool((os.environ.get("QIANKE_ALERT_WEBHOOK_URL") or "").strip())


def _send_group_webhook(content: str) -> dict[str, Any]:
    """已有企业微信群机器人兜底；不是应用直发给用户。"""
    url = (os.environ.get("QIANKE_ALERT_WEBHOOK_URL") or "").strip()
    if not url:
        return {"sent": False, "reason": "NO_GROUP_WEBHOOK"}
    payload = {"msgtype": "markdown", "markdown": {"content": content[:3800]}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("企业微信群机器人兜底回写失败: %s", exc)
        return {"sent": False, "reason": "GROUP_DELIVERY_FAILED", "error": str(exc)[:300]}
    if int(data.get("errcode") or 0) != 0:
        return {
            "sent": False,
            "reason": "GROUP_WECOM_ERROR",
            "errcode": data.get("errcode"),
            "error": data.get("errmsg"),
        }
    return {"sent": True, "channel": "group_webhook"}


def _get_token() -> str:
    corp_id = (os.environ.get("QIANKE_WECOM_CORP_ID") or "").strip()
    secret = (os.environ.get("QIANKE_WECOM_CORP_SECRET") or "").strip()
    with _TOKEN_LOCK:
        now = time.time()
        if _TOKEN["value"] and _TOKEN["expires_at"] > now + 60:
            return str(_TOKEN["value"])
        query = urllib.parse.urlencode({"corpid": corp_id, "corpsecret": secret})
        with urllib.request.urlopen(
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{query}", timeout=10
        ) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
        if int(data.get("errcode") or 0) != 0:
            raise RuntimeError(f"企业微信 gettoken 失败: {data.get('errmsg')}")
        _TOKEN["value"] = data.get("access_token") or ""
        _TOKEN["expires_at"] = now + int(data.get("expires_in") or 7200)
        return str(_TOKEN["value"])


def _post_message(payload: dict[str, Any]) -> dict[str, Any]:
    token = _get_token()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={urllib.parse.quote(token)}",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def send_text(to_user: str, content: str, *, agent_id: str | None = None) -> dict[str, Any]:
    if not configured():
        if _fallback_group_enabled():
            result = _send_group_webhook(content)
            logger.info(
                "企业微信回写走群机器人兜底 sent=%s reason=%s",
                result.get("sent"),
                result.get("reason"),
            )
            return result
        return {"sent": False, "reason": "WECOM_SEND_NOT_CONFIGURED"}
    recipient = (to_user or "").strip()
    if not recipient:
        return {"sent": False, "reason": "NO_RECIPIENT"}
    agent = (agent_id or os.environ.get("QIANKE_WECOM_AGENT_ID") or "").strip()
    try:
        agent_id_int = int(agent)
    except ValueError:
        return {"sent": False, "reason": "INVALID_AGENT_ID"}
    text = (content or "").strip()
    if not text:
        return {"sent": False, "reason": "EMPTY_CONTENT"}
    # 企业微信文本消息上限 2048 字节，按字符保守截断。
    text = text[:1200]
    try:
        data = _post_message({
            "touser": recipient,
            "msgtype": "text",
            "agentid": agent_id_int,
            "text": {"content": text},
            "safe": 0,
        })
    except Exception as exc:  # noqa: BLE001 - 回写失败不影响主流程
        logger.warning("企业微信结果回写失败: %s", exc)
        return {"sent": False, "reason": "DELIVERY_FAILED", "error": str(exc)[:300]}
    if int(data.get("errcode") or 0) != 0:
        logger.warning("企业微信结果回写业务失败: %s", data.get("errmsg"))
        return {"sent": False, "reason": "WECOM_ERROR", "errcode": data.get("errcode"), "error": data.get("errmsg")}
    logger.info("企业微信应用结果回写成功 msgid=%s", data.get("msgid"))
    return {"sent": True, "msgid": data.get("msgid")}


def send_template_card(to_user: str, card: dict[str, Any], *, agent_id: str | None = None) -> dict[str, Any]:
    if not configured():
        return {"sent": False, "reason": "WECOM_SEND_NOT_CONFIGURED"}
    recipient = (to_user or "").strip()
    if not recipient:
        return {"sent": False, "reason": "NO_RECIPIENT"}
    agent = (agent_id or os.environ.get("QIANKE_WECOM_AGENT_ID") or "").strip()
    try:
        agent_id_int = int(agent)
    except ValueError:
        return {"sent": False, "reason": "INVALID_AGENT_ID"}
    try:
        data = _post_message({
            "touser": recipient,
            "msgtype": "template_card",
            "agentid": agent_id_int,
            "template_card": card,
            "safe": 0,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("企业微信卡片回写失败: %s", exc)
        return {"sent": False, "reason": "DELIVERY_FAILED", "error": str(exc)[:300]}
    if int(data.get("errcode") or 0) != 0:
        logger.warning("企业微信卡片回写业务失败: %s", data.get("errmsg"))
        return {
            "sent": False,
            "reason": "WECOM_ERROR",
            "errcode": data.get("errcode"),
            "error": data.get("errmsg"),
        }
    logger.info("企业微信审批卡片发送成功 msgid=%s", data.get("msgid"))
    return {"sent": True, "msgid": data.get("msgid")}


def _recipient(item: dict[str, Any]) -> tuple[str, str | None]:
    for trigger in item.get("triggers") or []:
        if trigger.get("source") != "wecom":
            continue
        metadata = trigger.get("metadata") or {}
        user = str(metadata.get("from_user") or "").strip()
        if user:
            agent = str(metadata.get("agent_id") or "").strip() or None
            return user, agent
    return "", None


def notify_work_item(item: dict[str, Any], *, stage: str) -> dict[str, Any]:
    """把调查/执行结果回写到发起消息的企业微信用户。"""
    user, agent_id = _recipient(item)
    if not user:
        return {"sent": False, "reason": "NO_WECOM_TRIGGER"}
    result = item.get("result") or {}
    approval = item.get("approval") or {}
    action = approval.get("action") or result.get("action") or {}
    if stage == "INVESTIGATED" and action:
        try:
            from rag_demo.superagent import approval_card

            card_result = approval_card.notify_card(item)
            if card_result.get("sent"):
                return {**card_result, "stage": stage, "card": True}
            logger.info("企业微信审批卡片未发送，回退文本: %s", card_result.get("reason"))
        except Exception:  # noqa: BLE001
            logger.exception("企业微信审批卡片发送异常，回退文本")
    lines = [
        "【千客 Super-agent】",
        f"工作项：{item.get('work_item_id')}",
        f"状态：{item.get('status')}",
    ]
    if stage == "INVESTIGATED":
        lines.append("调查已完成，等待人工审批。")
        summary = str(result.get("summary") or "").strip()
        if summary:
            lines.append(summary[:600])
        if action:
            lines.append(f"建议动作：{action.get('action_type')}")
            if action.get("order_id"):
                lines.append(f"订单：{action.get('order_id')}")
            code = str(item.get("work_item_id") or "")[-6:]
            if code:
                action_type = str(action.get("action_type") or "").upper()
                if action_type == "CREATE_AFTER_SALE":
                    lines.append(f"审批回复：同意 {code} 仅退款 / 同意 {code} 退货退款")
                elif action_type == "SHIP_ORDER":
                    lines.append(f"审批回复：同意 {code} 发货 <运单号>")
                else:
                    lines.append(f"审批回复：同意 {code}")
                lines.append(f"驳回：驳回 {code}")
    elif stage == "APPROVED":
        execution = approval.get("execution_result") or result.get("execution") or {}
        lines.append("人工已审批并执行。")
        lines.append(f"执行结果：{'成功' if approval.get('execution_status') == 'EXECUTED' else '失败'}")
        if execution.get("order_id"):
            lines.append(f"订单：{execution.get('order_id')}")
        if item.get("error"):
            lines.append(f"错误：{str(item.get('error'))[:300]}")
    elif stage == "REJECTED":
        lines.append("人工已驳回，未执行任何动作。")
    return send_text(user, "\n".join(lines), agent_id=agent_id)
