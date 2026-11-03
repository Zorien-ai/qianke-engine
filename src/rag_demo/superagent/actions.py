"""Super-agent 受控动作执行器。

边界：
- 只有人工审批后才调用；
- 只允许白名单动作；
- 复用现有 C/商家受控 API，不直接写数据库；
- 幂等键 = work_item_id，重复审批不会重复执行。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from rag_demo.c_end import store
from rag_demo.merchant import MerchantError, get_merchant_repository, get_merchant_write_repository
from rag_demo.superagent import store as sa_store

logger = logging.getLogger(__name__)

MERCHANT_ID = "m_gear_002"
ALLOWED_ACTIONS = {
    "CANCEL_ORDER",
    "CREATE_AFTER_SALE",
    "SHIP_ORDER",
    "COMPLETE_ORDER",
    "REFUND_AFTER_SALE",
    "RECEIVE_RETURN",
    "REJECT_AFTER_SALE",
    "ISSUE_COMPENSATION",
}


class ActionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _order_for_merchant(order_id: str, merchant_id: str) -> dict[str, Any]:
    order = store.get_order(order_id)
    if order is None:
        raise ActionError("ORDER_NOT_FOUND", "订单不存在")
    merchant_order = get_merchant_repository().get_order(order_id, merchant_id=merchant_id)
    if merchant_order is None:
        raise ActionError("ORDER_FORBIDDEN", "订单不属于当前商家")
    return order


def _ticket_for_order(order_id: str, statuses: set[str], ticket_id: str = "") -> dict[str, Any]:
    tickets = store.list_after_sales(order_id=order_id, limit=20)
    if ticket_id:
        for ticket in tickets:
            if ticket.get("ticket_id") == ticket_id:
                return ticket
    for ticket in tickets:
        if str(ticket.get("status") or "").upper() in statuses:
            return ticket
    raise ActionError(
        "AFTER_SALE_NOT_FOUND",
        f"订单 {order_id} 没有状态为 {'/'.join(sorted(statuses))} 的售后工单",
    )


def _execute(action: dict[str, Any], merchant_id: str) -> dict[str, Any]:
    action_type = str(action.get("action_type") or action.get("action") or "").strip().upper()
    if action_type not in ALLOWED_ACTIONS:
        raise ActionError("ACTION_NOT_ALLOWED", f"动作类型不在白名单：{action_type or 'EMPTY'}")
    policy = store.get_merchant_policy(merchant_id)
    if action_type not in policy["allowed_actions"]:
        raise ActionError("ACTION_NOT_ALLOWED_BY_POLICY", f"商家策略未开放动作：{action_type}")
    if policy.get("require_note") and not str(action.get("reason") or "").strip():
        raise ActionError("NOTE_REQUIRED", "商家策略要求填写动作原因")
    order_id = str(action.get("order_id") or "").strip()
    if not order_id:
        raise ActionError("INVALID_ACTION", "动作缺少 order_id")
    order = _order_for_merchant(order_id, merchant_id)
    buyer_id = order["buyer_id"]

    if action_type == "CANCEL_ORDER":
        if order["status"] == "CANCELLED":
            return {"action_type": action_type, "order_id": order_id, "already": "CANCELLED"}
        return {
            "action_type": action_type,
            **store.cancel_confirmed_order(
                buyer_id,
                order_id,
                request_id=f"superagent:{action.get('work_item_id') or order_id}",
                merchant_id=merchant_id,
            ),
        }

    if action_type == "CREATE_AFTER_SALE":
        sale_type = str(action.get("sale_type") or "").strip().upper()
        if sale_type not in {"REFUND_ONLY", "RETURN_REFUND"}:
            raise ActionError("INVALID_ACTION", "售后动作必须由人工明确 sale_type：REFUND_ONLY / RETURN_REFUND")
        reason = str(action.get("reason") or "Super-agent 调查后建议创建售后工单").strip()
        ticket = store.create_after_sale(buyer_id, order_id, sale_type=sale_type, reason=reason)
        return {"action_type": action_type, "order_id": order_id, "ticket": ticket}

    if action_type == "SHIP_ORDER":
        tracking_no = str(action.get("tracking_no") or "").strip()
        if not tracking_no:
            raise ActionError("INVALID_ACTION", "发货动作缺少物流单号")
        updated = get_merchant_write_repository().update_order_status(
            merchant_id,
            order_id,
            "SHIPPED",
            tracking_no=tracking_no,
            carrier=str(action.get("carrier") or "").strip() or None,
        )
        return {"action_type": action_type, "order": updated.to_dict()}

    if action_type == "COMPLETE_ORDER":
        updated = get_merchant_write_repository().update_order_status(
            merchant_id, order_id, "COMPLETED"
        )
        return {"action_type": action_type, "order": updated.to_dict()}

    if action_type == "REFUND_AFTER_SALE":
        ticket = _ticket_for_order(order_id, {"OPEN"}, str(action.get("ticket_id") or ""))
        refund_amount = float(ticket.get("refund_amount") or order.get("amount") or 0)
        allowed, code = store.check_action_policy(
            merchant_id, action_type, refund_amount=refund_amount
        )
        if not allowed:
            raise ActionError(code, f"退款金额 {refund_amount:.2f} 超出商家策略上限")
        resolved = store.resolve_after_sale(
            ticket["ticket_id"], approved=True, merchant_id=merchant_id
        )
        return {"action_type": action_type, "order_id": order_id, "ticket": resolved}

    if action_type == "RECEIVE_RETURN":
        ticket = _ticket_for_order(
            order_id, {"RETURN_SHIPPED"}, str(action.get("ticket_id") or "")
        )
        received = store.receive_after_sale(
            ticket["ticket_id"], accepted=True, merchant_id=merchant_id
        )
        return {"action_type": action_type, "order_id": order_id, "ticket": received}

    if action_type == "REJECT_AFTER_SALE":
        ticket = _ticket_for_order(order_id, {"OPEN"}, str(action.get("ticket_id") or ""))
        rejected = store.resolve_after_sale(
            ticket["ticket_id"], approved=False, merchant_id=merchant_id
        )
        return {"action_type": action_type, "order_id": order_id, "ticket": rejected}

    if action_type == "ISSUE_COMPENSATION":
        try:
            amount = float(action.get("amount") or 0)
        except (TypeError, ValueError):
            raise ActionError("INVALID_ACTION", "补偿金额必须是数字") from None
        cap = min(
            float(os.environ.get("QIANKE_COMPENSATION_MAX_AMOUNT") or "50"),
            float(policy["compensation_max_amount"]),
        )
        allowed, code = store.check_action_policy(
            merchant_id, action_type, amount=amount
        )
        if not allowed:
            raise ActionError(code, f"补偿金额超出商家策略上限 {cap:g} 元")
        if amount <= 0 or amount > cap:
            raise ActionError("INVALID_ACTION", f"补偿金额必须在 0~{cap:g} 元之间")
        reason = str(action.get("reason") or "Super-agent 售后补偿").strip()[:300]
        compensation = store.create_compensation(
            order_id=order_id,
            buyer_id=buyer_id,
            merchant_id=merchant_id,
            amount=amount,
            reason=reason,
            work_item_id=str(action.get("work_item_id") or ""),
        )
        return {"action_type": action_type, "order_id": order_id, "compensation": compensation}

    raise ActionError("ACTION_NOT_ALLOWED", action_type)


def execute_approved(work_item_id: str) -> dict[str, Any]:
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        raise ActionError("WORK_ITEM_NOT_FOUND", "工作项不存在")
    if item["status"] != "EXECUTING":
        raise ActionError("INVALID_STATUS", f"工作项状态为 {item['status']}，不能执行")
    approval = item.get("approval") or {}
    if approval.get("execution_status") == "EXECUTED":
        return item
    action = approval.get("action") or item.get("result", {}).get("action") or {}
    if not isinstance(action, dict) or not action:
        completed = sa_store.complete_execution(
            work_item_id,
            success=True,
            result={"executed": False, "reason": "NO_ACTION", "message": "仅记录人工审批，无执行动作"},
        )
        return completed
    try:
        merchant_id = item.get("merchant_id") or MERCHANT_ID
        result = _execute({**action, "work_item_id": work_item_id}, merchant_id)
        return sa_store.complete_execution(
            work_item_id,
            success=True,
            result={"executed": True, **result},
        )
    except (ActionError, store.CStoreError, MerchantError, ValueError) as exc:
        message = getattr(exc, "message", None) or str(exc)
        code = getattr(exc, "code", "EXECUTION_FAILED")
        logger.warning("Super-agent 动作执行失败 work_item=%s code=%s error=%s", work_item_id, code, message)
        return sa_store.complete_execution(
            work_item_id,
            success=False,
            result={"executed": False, "action": action},
            error=f"{code}: {message}",
        )
    except Exception as exc:  # noqa: BLE001 - 审计失败，不吞掉
        logger.exception("Super-agent 动作执行异常 work_item=%s", work_item_id)
        return sa_store.complete_execution(
            work_item_id,
            success=False,
            result={"executed": False, "action": action},
            error=str(exc)[:1000],
        )
