"""企业微信卡片审批：签名审批页 + 模板卡片消息。

应用消息的模板卡片按钮回调在企业微信应用回调里并不可靠，
因此这里采用「卡片 + 签名审批页」：卡片点击打开固定域名的审批页，
页面上完成同意/驳回；文本命令仍保留为回退。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import time
from typing import Any
from urllib.parse import quote

from rag_demo.superagent import runtime as sa_runtime
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import wecom_send

DEFAULT_BASE_URL = "https://qianke.qiankeagent.com"
TOKEN_TTL_SECONDS = 24 * 3600


def _secret() -> str:
    return (
        os.environ.get("QIANKE_APPROVAL_CARD_SECRET")
        or os.environ.get("QIANKE_SUPERAGENT_WEBHOOK_SECRET")
        or ""
    ).strip()


def base_url() -> str:
    return (os.environ.get("QIANKE_PUBLIC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _sign(work_item_id: str, expires: int) -> str:
    message = f"{work_item_id}:{expires}".encode("utf-8")
    return hmac.new(_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()


def make_token(work_item_id: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    expires = int(time.time()) + max(60, int(ttl))
    payload = base64.urlsafe_b64encode(
        json.dumps({"w": work_item_id, "e": expires}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{payload}.{_sign(work_item_id, expires)}"


def verify_token(work_item_id: str, token: str) -> tuple[bool, str]:
    if not _secret():
        return False, "CARD_SECRET_NOT_CONFIGURED"
    try:
        payload, signature = (token or "").split(".", 1)
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:  # noqa: BLE001
        return False, "TOKEN_INVALID"
    if str(data.get("w") or "") != work_item_id:
        return False, "TOKEN_WORK_ITEM_MISMATCH"
    expires = int(data.get("e") or 0)
    if expires < int(time.time()):
        return False, "TOKEN_EXPIRED"
    expected = _sign(work_item_id, expires)
    if not hmac.compare_digest(expected, signature):
        return False, "TOKEN_SIGNATURE_INVALID"
    return True, ""


def approval_url(item: dict[str, Any]) -> str | None:
    if not _secret():
        return None
    if (item.get("approval") or {}).get("status") != "PENDING":
        return None
    token = make_token(item["work_item_id"])
    return f"{base_url()}/api/superagent/approval-card/{quote(item['work_item_id'])}?token={quote(token)}"


def _action(item: dict[str, Any]) -> dict[str, Any]:
    approval = item.get("approval") or {}
    return approval.get("action") or (item.get("result") or {}).get("action") or {}


def build_card(item: dict[str, Any]) -> dict[str, Any] | None:
    url = approval_url(item)
    if not url:
        return None
    action = _action(item)
    action_type = str(action.get("action_type") or "").upper()
    code = item["work_item_id"][-6:]
    order_id = str(action.get("order_id") or "")
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
    title = title_map.get(action_type, "待审批：Super-agent 动作")
    summary = str((item.get("result") or {}).get("summary") or "").strip()[:120]
    horizontal = [
        {"keyname": "工作项", "value": code},
        {"keyname": "动作", "value": action_type or "-"},
    ]
    if order_id:
        horizontal.append({"keyname": "订单", "value": order_id})
    return {
        "card_type": "text_notice",
        "main_title": {"title": title, "desc": f"订单 {order_id}" if order_id else "千客 Super-agent"},
        "sub_title_text": summary + (f"\n也可回复：同意 {code} 仅退款 / 驳回 {code}" if summary else f"回复：同意 {code} 仅退款 / 驳回 {code}"),
        "horizontal_content_list": horizontal,
        "card_action": {"type": 1, "url": url},
    }


def notify_card(item: dict[str, Any]) -> dict[str, Any]:
    user, agent_id = wecom_send._recipient(item)  # noqa: SLF001
    if not user:
        return {"sent": False, "reason": "NO_WECOM_TRIGGER"}
    card = build_card(item)
    if card is None:
        return {"sent": False, "reason": "CARD_NOT_READY"}
    return wecom_send.send_template_card(user, card, agent_id=agent_id)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{margin:0;background:#f5f4f1;color:#1d1c1a;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:560px;margin:0 auto;padding:28px 18px}}
.card{{background:#fff;border:1px solid #e6e2da;border-radius:16px;padding:22px;box-shadow:0 8px 28px #0000000a}}
h1{{font-size:20px;margin:0 0 10px}} .muted{{color:#77716a;font-size:13px}}
.kv{{border-top:1px solid #eee9e1;margin-top:14px;padding-top:14px}}
.row{{display:flex;justify-content:space-between;gap:12px;padding:5px 0}} .row b{{font-weight:600;text-align:right;word-break:break-all}}
button{{border:0;border-radius:12px;padding:13px 18px;font-size:16px;font-weight:600;margin:8px 8px 0 0;cursor:pointer}}
.ok{{background:#1d1c1a;color:#fff}} .warn{{background:#f1e5d0;color:#7a4b00}} .no{{background:#eee9e1;color:#5f5a53}}
input[type=text]{{width:100%;box-sizing:border-box;border:1px solid #d9d3ca;border-radius:10px;padding:12px;font-size:16px;margin-top:8px}}
.note{{margin-top:14px;color:#77716a;font-size:13px}}
</style></head><body><main><div class="card">{body}</div></main></body></html>"""


def render_page(item: dict[str, Any], token: str, error: str = "") -> str:
    action = _action(item)
    action_type = str(action.get("action_type") or "").upper()
    order_id = html.escape(str(action.get("order_id") or "-"))
    reason = html.escape(str(action.get("reason") or "").strip()[:500])
    code = item["work_item_id"][-6:]
    error_html = f'<p style="color:#a33">{html.escape(error)}</p>' if error else ""
    forms = []
    if action_type == "CREATE_AFTER_SALE":
        for label, value, cls in (
            ("仅退款", "approve:REFUND_ONLY", "ok"),
            ("退货退款", "approve:RETURN_REFUND", "warn"),
        ):
            forms.append(
                f'<form method="post" action="/api/superagent/approval-card/{html.escape(item["work_item_id"])}" style="display:inline">'
                f'<input type="hidden" name="token" value="{html.escape(token)}">'
                f'<input type="hidden" name="decision" value="{value}">'
                f'<button class="{cls}" type="submit">{label}</button></form>'
            )
    elif action_type == "SHIP_ORDER":
        forms.append(
            f'<form method="post" action="/api/superagent/approval-card/{html.escape(item["work_item_id"])}">'
            f'<input type="hidden" name="token" value="{html.escape(token)}">'
            f'<input type="hidden" name="decision" value="approve:SHIP">'
            '<label class="muted">运单号</label><input type="text" name="tracking_no" required placeholder="SF123456789">'
            '<label class="muted">承运商（可选）</label><input type="text" name="carrier" placeholder="顺丰">'
            '<button class="ok" type="submit">确认发货</button></form>'
        )
    elif action_type == "ISSUE_COMPENSATION":
        forms.append(
            f'<form method="post" action="/api/superagent/approval-card/{html.escape(item["work_item_id"])}">'
            f'<input type="hidden" name="token" value="{html.escape(token)}">'
            f'<input type="hidden" name="decision" value="approve:COMPENSATION">'
            '<label class="muted">补偿金额（元，上限由服务端配置）</label><input type="text" name="amount" required placeholder="20">'
            '<label class="muted">补偿原因</label><input type="text" name="reason" required placeholder="物流延迟补偿">'
            '<button class="ok" type="submit">确认发放</button></form>'
        )
    else:
        forms.append(
            f'<form method="post" action="/api/superagent/approval-card/{html.escape(item["work_item_id"])}" style="display:inline">'
            f'<input type="hidden" name="token" value="{html.escape(token)}">'
            f'<input type="hidden" name="decision" value="approve">'
            '<button class="ok" type="submit">同意执行</button></form>'
        )
    forms.append(
        f'<form method="post" action="/api/superagent/approval-card/{html.escape(item["work_item_id"])}" style="display:inline">'
        f'<input type="hidden" name="token" value="{html.escape(token)}">'
        '<input type="hidden" name="decision" value="reject">'
        '<button class="no" type="submit">驳回</button></form>'
    )
    return _page(
        "千客审批",
        f"<h1>千客 Super-agent</h1><p class=\"muted\">工作项 {html.escape(item['work_item_id'])} · 短码 {html.escape(code)}</p>"
        f"{error_html}<div class=\"kv\">"
        f"<div class=\"row\"><span>动作</span><b>{html.escape(action_type or '-')}</b></div>"
        f"<div class=\"row\"><span>订单</span><b>{order_id}</b></div>"
        f"<div class=\"row\"><span>状态</span><b>{html.escape(str(item.get('status') or '-'))}</b></div>"
        f"</div><p class=\"muted\">{reason}</p>{''.join(forms)}"
        "<p class=\"note\">审批链接 24 小时有效；所有执行仍走白名单动作和 ACTION Job。</p>",
    )


def render_result(title: str, message: str) -> str:
    return _page(title, f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>")


def approve_from_card(
    work_item_id: str,
    *,
    decision: str,
    tracking_no: str = "",
    carrier: str = "",
    amount: str = "",
    reason: str = "",
) -> tuple[bool, str]:
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        return False, "工作项不存在"
    if item.get("status") != "WAITING_APPROVAL":
        return False, f"工作项当前状态为 {item.get('status')}，不能审批"
    action = _action(item)
    action_type = str(action.get("action_type") or "").upper()
    if decision == "reject":
        rejected = sa_store.decide_approval(work_item_id, approved=False, note="企业微信卡片驳回")
        wecom_send.notify_work_item(rejected, stage="REJECTED")
        return True, f"工作项 {work_item_id[-6:]} 已驳回"
    params: dict[str, Any] = {}
    if decision.startswith("approve:"):
        value = decision.split(":", 1)[1]
        if action_type == "CREATE_AFTER_SALE":
            if value not in {"REFUND_ONLY", "RETURN_REFUND"}:
                return False, "售后卡片参数不合法"
            params["sale_type"] = value
        elif action_type == "SHIP_ORDER":
            if not tracking_no.strip():
                return False, "发货需要运单号"
            params["tracking_no"] = tracking_no.strip()
            if carrier.strip():
                params["carrier"] = carrier.strip()
        elif action_type == "ISSUE_COMPENSATION":
            try:
                value_amount = float(amount or 0)
            except ValueError:
                return False, "补偿金额必须是数字"
            if value_amount <= 0:
                return False, "补偿金额必须大于 0"
            params["amount"] = value_amount
            if reason.strip():
                params["reason"] = reason.strip()[:300]
    elif action_type == "CREATE_AFTER_SALE":
        return False, "售后审批必须选择仅退款或退货退款"
    try:
        if params:
            sa_store.update_approval_action(work_item_id, params)
        sa_store.decide_approval(work_item_id, approved=True, note="企业微信卡片审批")
        if not sa_runtime.start_action(work_item_id):
            return False, "执行任务已存在或无法启动"
    except sa_store.store.CStoreError as exc:
        return False, f"{exc.code}: {exc.message}"
    return True, f"工作项 {work_item_id[-6:]} 已通过，正在执行，结果会回写企业微信"
