"""企业微信内审批：文本命令解析与执行。

命令（只支持精确格式，不做模糊自然语言写入）：
    同意 <work_item 短码> 仅退款
    同意 <work_item 短码> 退货退款
    同意 <work_item 短码> 发货 <运单号> [承运商]
    同意 <work_item 短码>
    驳回 <work_item 短码>
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from rag_demo.superagent import runtime as sa_runtime
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import wecom_send

logger = logging.getLogger(__name__)

_CODE = r"[A-Za-z0-9_]{4,64}"
_APPROVE_RE = re.compile(
    rf"^同意\s+(?P<code>{_CODE})(?:\s+(?P<param>仅退款|退货退款|发货(?:\s+(?P<tracking>[A-Za-z0-9_-]{{4,64}}))?(?:\s+(?P<carrier>.+))?))?$"
)
_REJECT_RE = re.compile(rf"^驳回\s+(?P<code>{_CODE})$")
_USAGE = (
    "审批格式：\n"
    "同意 <短码> 仅退款\n"
    "同意 <短码> 退货退款\n"
    "同意 <短码> 发货 <运单号> [承运商]\n"
    "驳回 <短码>"
)


def parse_command(content: str) -> dict[str, Any] | None:
    text = " ".join((content or "").strip().split())
    if not text:
        return None
    match = _REJECT_RE.match(text)
    if match:
        return {"decision": "REJECT", "code": match.group("code")}
    match = _APPROVE_RE.match(text)
    if not match:
        return None
    param = (match.group("param") or "").strip()
    result: dict[str, Any] = {"decision": "APPROVE", "code": match.group("code")}
    if param == "仅退款":
        result["sale_type"] = "REFUND_ONLY"
    elif param == "退货退款":
        result["sale_type"] = "RETURN_REFUND"
    elif param.startswith("发货"):
        tracking = (match.group("tracking") or "").strip()
        if not tracking:
            return {"error": "发货命令缺少运单号"}
        result["tracking_no"] = tracking
        carrier = (match.group("carrier") or "").strip()
        if carrier:
            result["carrier"] = carrier
    return result


def _approvers() -> set[str]:
    return {
        item.strip()
        for item in (os.environ.get("QIANKE_WECOM_APPROVERS") or "").split(",")
        if item.strip()
    }


def _find_work_item(code: str) -> tuple[dict[str, Any] | None, str]:
    scope = (os.environ.get("QIANKE_WECOM_MERCHANT_ID") or sa_store.DEFAULT_MERCHANT_ID).strip()
    items = sa_store.list_work_items(limit=200, merchant_id=scope)
    matches = [
        item for item in items
        if item["status"] == "WAITING_APPROVAL" and item["work_item_id"].lower().endswith(code.lower())
    ]
    if not matches:
        return None, "没有找到待审批的工作项。"
    if len(matches) > 1:
        return None, "短码匹配到多个工作项，请发送完整工作项 ID。"
    return sa_store.get_work_item(matches[0]["work_item_id"]), ""


def _sender(item: dict[str, Any]) -> tuple[str, str | None]:
    for trigger in item.get("triggers") or []:
        if trigger.get("source") != "wecom":
            continue
        metadata = trigger.get("metadata") or {}
        user = str(metadata.get("from_user") or "").strip()
        if user:
            return user, str(metadata.get("agent_id") or "").strip() or None
    return "", None


def _reply(to_user: str, text: str, agent_id: str | None = None) -> None:
    try:
        wecom_send.send_text(to_user, text, agent_id=agent_id)
    except Exception:  # noqa: BLE001
        logger.exception("企业微信审批回复失败 user=%s", to_user)


def handle_message(message: dict[str, Any]) -> bool:
    """处理企业微信文本审批；返回 True 表示已消费，不再进入 Router。"""
    content = str(message.get("Content") or "")
    command = parse_command(content)
    if command is None:
        return False
    from_user = str(message.get("FromUserName") or "").strip()
    agent_id = str(message.get("AgentID") or "").strip() or None
    if not from_user:
        return True
    if "error" in command:
        _reply(from_user, command["error"] + "\n" + _USAGE, agent_id)
        return True

    item, error = _find_work_item(command["code"])
    if item is None:
        _reply(from_user, error or "工作项不存在。", agent_id)
        return True
    initiator, trigger_agent = _sender(item)
    approvers = _approvers()
    allowed = {from_user, *approvers}
    if (initiator and initiator not in allowed) or (not initiator and from_user not in approvers):
        _reply(from_user, "你没有权限审批这个工作项。", agent_id)
        return True
    agent_id = agent_id or trigger_agent
    work_item_id = item["work_item_id"]
    approval = item.get("approval") or {}
    action = approval.get("action") or (item.get("result") or {}).get("action") or {}
    action_type = str(action.get("action_type") or "").upper()

    if command["decision"] == "REJECT":
        rejected = sa_store.decide_approval(work_item_id, approved=False, note=f"企业微信驳回 by {from_user}")
        wecom_send.notify_work_item(rejected, stage="REJECTED")
        _reply(from_user, f"已驳回工作项 {work_item_id[-6:]}，未执行任何动作。", agent_id)
        return True

    params: dict[str, Any] = {}
    if action_type == "CREATE_AFTER_SALE":
        sale_type = command.get("sale_type")
        if sale_type not in {"REFUND_ONLY", "RETURN_REFUND"}:
            _reply(from_user, "售后审批需要指定：仅退款 或 退货退款。\n" + _USAGE, agent_id)
            return True
        params["sale_type"] = sale_type
    elif action_type == "SHIP_ORDER":
        tracking = command.get("tracking_no")
        if not tracking:
            _reply(from_user, "发货审批需要指定运单号。\n" + _USAGE, agent_id)
            return True
        params["tracking_no"] = tracking
        if command.get("carrier"):
            params["carrier"] = command["carrier"]
    elif command.get("sale_type") or command.get("tracking_no"):
        _reply(from_user, f"动作 {action_type or '无'} 不需要这些参数。", agent_id)
        return True

    try:
        if params:
            sa_store.update_approval_action(work_item_id, params)
        sa_store.decide_approval(work_item_id, approved=True, note=f"企业微信审批 by {from_user}")
        if not sa_runtime.start_action(work_item_id):
            _reply(from_user, "审批已记录，但执行任务已存在或无法启动，请在 B 工作台检查。", agent_id)
            return True
    except sa_store.store.CStoreError as exc:
        _reply(from_user, f"审批失败：{exc.message}", agent_id)
        return True
    _reply(
        from_user,
        f"已通过工作项 {work_item_id[-6:]}，正在执行。\n执行完成后会再发送结果。",
        agent_id,
    )
    return True
