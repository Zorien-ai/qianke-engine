"""企业微信原生按钮卡片（template_card button_interaction）。

默认关闭；开启后尝试发送原生按钮卡片，并把 template_card_event 回调
转换为现有的审批文本命令，复用同一套权限/参数/ACTION Job 逻辑。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return (os.environ.get("QIANKE_WECOM_NATIVE_CARD") or "0").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _key(action: str, work_item_id: str, sale_type: str = "") -> str:
    return json.dumps(
        {"a": action, "w": work_item_id, "s": sale_type},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_card(item: dict[str, Any]) -> dict[str, Any] | None:
    if not enabled():
        return None
    approval = item.get("approval") or {}
    if approval.get("status") != "PENDING":
        return None
    action = approval.get("action") or (item.get("result") or {}).get("action") or {}
    action_type = str(action.get("action_type") or "").upper()
    work_item_id = str(item.get("work_item_id") or "")
    if not work_item_id:
        return None
    code = work_item_id[-6:]
    title_map = {
        "CREATE_AFTER_SALE": "待审批：创建售后",
        "CANCEL_ORDER": "待审批：取消订单",
        "SHIP_ORDER": "待审批：订单发货",
        "COMPLETE_ORDER": "待审批：完成订单",
        "REFUND_AFTER_SALE": "待审批：售后退款",
        "RECEIVE_RETURN": "待审批：退货入库",
        "REJECT_AFTER_SALE": "待审批：驳回售后",
        "ISSUE_COMPENSATION": "待审批：发放补偿",
    }
    buttons = []
    if action_type == "CREATE_AFTER_SALE":
        buttons = [
            {"text": "仅退款", "style": 1, "key": _key("approve", work_item_id, "REFUND_ONLY")},
            {"text": "退货退款", "style": 1, "key": _key("approve", work_item_id, "RETURN_REFUND")},
            {"text": "驳回", "style": 2, "key": _key("reject", work_item_id)},
        ]
    elif action_type == "ISSUE_COMPENSATION":
        # 金额必须由人工填写，原生按钮只提供跳转审批页的选择。
        buttons = [
            {"text": "去填写补偿", "style": 1, "key": _key("page", work_item_id)},
            {"text": "驳回", "style": 2, "key": _key("reject", work_item_id)},
        ]
    else:
        buttons = [
            {"text": "同意执行", "style": 1, "key": _key("approve", work_item_id)},
            {"text": "驳回", "style": 2, "key": _key("reject", work_item_id)},
        ]
    return {
        "card_type": "button_interaction",
        "task_id": f"sa_{work_item_id}",
        "main_title": {
            "title": title_map.get(action_type, "待审批：Super-agent 动作"),
            "desc": f"工作项 {code}",
        },
        "sub_title_text": str((item.get("result") or {}).get("summary") or "")[:100],
        "button_list": buttons,
    }


def parse_event(message: dict[str, Any]) -> dict[str, Any] | None:
    if str(message.get("MsgType") or "").lower() != "event":
        return None
    if str(message.get("Event") or "") != "template_card_event":
        return None
    raw = str(message.get("EventKey") or "").strip()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    work_item_id = str(data.get("w") or "").strip()
    action = str(data.get("a") or "").strip()
    if not work_item_id or action not in {"approve", "reject", "page"}:
        return None
    return {
        "work_item_id": work_item_id,
        "action": action,
        "sale_type": str(data.get("s") or "").strip().upper(),
        "from_user": str(message.get("FromUserName") or "").strip(),
        "agent_id": str(message.get("AgentID") or "").strip() or None,
    }


def to_command(event: dict[str, Any]) -> str | None:
    code = event["work_item_id"][-6:]
    if event["action"] == "reject":
        return f"驳回 {code}"
    if event["action"] == "page":
        return None
    if event.get("sale_type") in {"REFUND_ONLY", "RETURN_REFUND"}:
        label = "仅退款" if event["sale_type"] == "REFUND_ONLY" else "退货退款"
        return f"同意 {code} {label}"
    return f"同意 {code}"


def _reply(from_user: str, text: str, agent_id: str | None) -> None:
    try:
        from rag_demo.superagent import wecom_send

        wecom_send.send_text(from_user, text, agent_id=agent_id)
    except Exception:  # noqa: BLE001
        logger.exception("原生卡片状态回复失败 user=%s", from_user)


def handle_event(message: dict[str, Any]) -> bool:
    event = parse_event(message)
    if event is None:
        return False
    from rag_demo.superagent import store as sa_store
    from rag_demo.superagent import wecom_approval

    item = sa_store.get_work_item(event["work_item_id"])
    logger.info(
        "原生卡片事件 from=%s work_item=%s action=%s",
        event["from_user"],
        event["work_item_id"],
        event["action"],
    )
    if item is None:
        return True
    if item.get("status") != "WAITING_APPROVAL":
        _reply(
            event["from_user"],
            f"工作项 {event['work_item_id'][-6:]} 当前状态为 {item.get('status')}，无需重复审批。",
            event["agent_id"],
        )
        return True
    command = to_command(event)
    if command is None:
        # 复杂参数走签名审批页。
        return True
    return wecom_approval.handle_message(
        {
            "MsgType": "text",
            "Content": command,
            "FromUserName": event["from_user"],
            "AgentID": event["agent_id"],
        }
    )
