# -*- coding: utf-8 -*-
"""AI 实时监控 / Token 账单 / 管理端接口。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rag_demo import ai_monitor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["monitor"])


def register_monitor(app: FastAPI) -> None:
    app.include_router(router)


def _main():
    from rag_demo.api import main
    return main


def _scope(manager: bool = False) -> tuple[dict, str, bool]:
    api = _main()
    account = api._require_manager() if manager else api._require_login()
    dataset = api._tenant_dataset()
    admin = bool(account and account.get("is_system_admin"))
    return account, dataset, admin


def _tenant_name(account: dict) -> str:
    ent = account.get("enterprise") if account else None
    if ent and ent.get("name"):
        return str(ent["name"])
    return "平台方" if account and account.get("is_system_admin") else str(dataset_name(account))


def dataset_name(account: dict) -> str:
    return "demo" if account and account.get("is_system_admin") else (account.get("dataset") or "未绑定空间")


class RechargeIn(BaseModel):
    pack_id: str


class PriceItem(BaseModel):
    model: str
    input_sale_per_1k: float | None = None
    output_sale_per_1k: float | None = None


class PriceIn(BaseModel):
    items: list[PriceItem]


# ==================== 监控 ====================

@router.get("/api/monitor/overview")
def monitor_overview(range: str = "24h") -> dict:
    account, tenant, admin = _scope(manager=True)
    data = ai_monitor.overview(tenant, range, admin=admin)
    return {"dataset": tenant, "mode": "platform" if admin else "enterprise", **data}


@router.get("/api/monitor/timeseries")
def monitor_timeseries(range: str = "24h") -> dict:
    account, tenant, admin = _scope(manager=True)
    return {"dataset": tenant, "items": ai_monitor.timeseries(tenant, range, admin=admin)}


@router.get("/api/monitor/traces")
def monitor_traces(limit: int = 30) -> dict:
    account, tenant, admin = _scope(manager=True)
    return {"dataset": tenant, "items": ai_monitor.traces(tenant, limit, admin=admin)}


@router.get("/api/monitor/traces/{trace_id}")
def monitor_trace_detail(trace_id: str) -> dict:
    account, tenant, admin = _scope(manager=True)
    data = ai_monitor.trace_detail(tenant, trace_id, admin=admin)
    if data is None:
        raise HTTPException(status_code=404, detail="Trace 不存在或不属于当前数据空间")
    return {"dataset": tenant, **data}


# ==================== 账单 ====================

@router.get("/api/billing/wallet")
def billing_wallet() -> dict:
    account, tenant, _ = _scope(manager=True)
    return {"dataset": tenant, "wallet": ai_monitor.wallet(tenant, _tenant_name(account))}


@router.get("/api/billing/packs")
def billing_packs() -> dict:
    _scope()
    return {"items": ai_monitor.packs()}


@router.get("/api/billing/usage")
def billing_usage(range: str = "30d") -> dict:
    account, tenant, admin = _scope(manager=True)
    return {"dataset": tenant, "items": ai_monitor.usage_summary(tenant, range, admin=False)}


@router.post("/api/billing/recharge")
def billing_recharge(payload: RechargeIn) -> dict:
    account, tenant, _ = _scope(manager=True)
    try:
        result = ai_monitor.recharge(tenant, payload.pack_id, _tenant_name(account))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"dataset": tenant, **result}


@router.get("/api/billing/invoices")
def billing_invoices() -> dict:
    account, tenant, _ = _scope(manager=True)
    return {"dataset": tenant, "items": ai_monitor.invoices(tenant)}


@router.get("/api/billing/invoices/{invoice_id}")
def billing_invoice(invoice_id: str) -> dict:
    account, tenant, _ = _scope(manager=True)
    data = ai_monitor.invoice(tenant, invoice_id)
    if data is None:
        raise HTTPException(status_code=404, detail="发票不存在或不属于当前数据空间")
    return {"dataset": tenant, "invoice": data}


@router.get("/api/billing/invoices/{invoice_id}/html", response_class=HTMLResponse)
def billing_invoice_html(invoice_id: str) -> str:
    account, tenant, _ = _scope(manager=True)
    inv = ai_monitor.invoice(tenant, invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="发票不存在或不属于当前数据空间")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{inv['invoice_id']}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:24px;color:#1f2937}}
h1{{font-size:22px}}table{{width:100%;border-collapse:collapse;margin-top:24px}}
td,th{{border-bottom:1px solid #e5e7eb;padding:12px;text-align:left}}
.total{{font-size:20px;font-weight:700;color:#4f46e5}}</style></head><body>
<h1>千客引擎 · Token 服务发票</h1>
<p>发票编号：{inv['invoice_id']}<br>开票日期：{inv['created_at'] or ''}<br>抬头：{inv.get('title') or ''}</p>
<table><tr><th>项目</th><th>说明</th><th>数量</th><th>金额</th></tr>
<tr><td>Token 充值</td><td>{inv.get('note') or ''}</td><td>{inv.get('tokens', 0):,} tokens</td><td>¥{inv.get('amount', 0):,.2f}</td></tr></table>
<p class="total">合计：¥{inv.get('amount', 0):,.2f}</p>
<p style="color:#6b7280;font-size:12px">演示环境自动开票记录，未接入税务开票平台。</p>
</body></html>"""


# ==================== 管理端 ====================

@router.get("/api/admin/monitor/tenants")
def admin_monitor_tenants() -> dict:
    api = _main()
    api._require_system_admin()
    return {"items": ai_monitor.admin_tenants()}


@router.get("/api/admin/billing/prices")
def admin_billing_prices() -> dict:
    api = _main()
    api._require_system_admin()
    return {"items": ai_monitor.model_prices()}


@router.put("/api/admin/billing/prices")
def admin_billing_prices_update(payload: PriceIn) -> dict:
    api = _main()
    api._require_system_admin()
    ai_monitor.update_model_prices([item.model_dump() for item in payload.items])
    return {"items": ai_monitor.model_prices()}
