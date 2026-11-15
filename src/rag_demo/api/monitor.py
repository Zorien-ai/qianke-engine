# -*- coding: utf-8 -*-
"""AI 实时监控 / Token 账单 / 管理端接口。"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rag_demo import ai_monitor, agent_eval_store

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


class AgentTraceTagsIn(BaseModel):
    tags: list[str] = []


class AgentTraceFeedbackIn(BaseModel):
    score: int | None = None
    comment: str = ""


class AgentDatasetIn(BaseModel):
    name: str
    description: str = ""
    trace_ids: list[str] = []


class AgentExperimentIn(BaseModel):
    dataset_id: str
    name: str = ""


class AgentCommApprovalIn(BaseModel):
    action: str
    note: str = ""


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

@router.get("/api/admin/agent-traces")
def admin_agent_traces(
    range_key: str = Query("24h", alias="range"),
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    feedback: str | None = None,
    min_latency_ms: int | None = None,
    max_latency_ms: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    api = _main()
    api._require_system_admin()
    return ai_monitor.agent_traces(
        range_key,
        status=status,
        q=q,
        tag=tag,
        feedback=feedback,
        min_latency_ms=min_latency_ms,
        max_latency_ms=max_latency_ms,
        limit=limit,
        offset=offset,
    )


@router.patch("/api/admin/agent-traces/{trace_id}/tags")
def admin_agent_trace_tags(trace_id: str, payload: AgentTraceTagsIn) -> dict:
    api = _main()
    account = api._require_system_admin()
    tags = ai_monitor.set_agent_trace_tags(
        trace_id,
        payload.tags,
        actor=str((account or {}).get("username") or ""),
    )
    if tags is None:
        raise HTTPException(status_code=404, detail="Agent Trace 不存在")
    return {"trace_id": trace_id, "tags": tags}


@router.post("/api/admin/agent-traces/{trace_id}/feedback")
def admin_agent_trace_feedback(trace_id: str, payload: AgentTraceFeedbackIn) -> dict:
    api = _main()
    account = api._require_system_admin()
    try:
        score = ai_monitor.set_agent_trace_feedback(
            trace_id,
            score=payload.score,
            comment=payload.comment,
            actor=str((account or {}).get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if score is None:
        raise HTTPException(status_code=404, detail="Agent Trace 不存在")
    return {
        "trace_id": trace_id,
        "feedback_score": payload.score,
        "comment": payload.comment[:1000],
    }


@router.get("/api/admin/agent-traces/{trace_id}")
def admin_agent_trace_detail(trace_id: str) -> dict:
    api = _main()
    api._require_system_admin()
    data = ai_monitor.trace_detail("", trace_id, admin=True)
    if data is None:
        raise HTTPException(status_code=404, detail="Agent Trace 不存在")
    return data


@router.get("/api/admin/agent-datasets")
def admin_agent_datasets() -> dict:
    api = _main()
    api._require_system_admin()
    return {"items": agent_eval_store.list_datasets()}


@router.post("/api/admin/agent-datasets")
def admin_agent_dataset_create(payload: AgentDatasetIn) -> dict:
    api = _main()
    account = api._require_system_admin()
    try:
        data = agent_eval_store.create_dataset(
            payload.name,
            payload.description,
            payload.trace_ids,
            actor=str((account or {}).get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data


@router.get("/api/admin/agent-datasets/{dataset_id}")
def admin_agent_dataset_detail(dataset_id: str) -> dict:
    api = _main()
    api._require_system_admin()
    data = agent_eval_store.get_dataset(dataset_id)
    if data is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return data


def _run_eval_experiment(experiment_id: str, account: dict, target_dataset: str) -> None:
    try:
        agent_eval_store.run_experiment(
            experiment_id,
            account=account,
            target_dataset=target_dataset,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Agent 评测实验执行失败: %s", experiment_id)


@router.post("/api/admin/agent-experiments")
def admin_agent_experiment_create(payload: AgentExperimentIn) -> dict:
    api = _main()
    account = api._require_system_admin()
    target_dataset = api._agent_dataset(account)
    try:
        experiment = agent_eval_store.create_experiment(
            payload.dataset_id,
            payload.name,
            target_dataset=target_dataset,
            actor=str((account or {}).get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    thread = threading.Thread(
        target=_run_eval_experiment,
        args=(experiment["experiment_id"], dict(account or {}), target_dataset),
        daemon=True,
        name=f"agent-eval-{experiment['experiment_id'][:8]}",
    )
    thread.start()
    return experiment


@router.get("/api/admin/agent-experiments")
def admin_agent_experiments(dataset_id: str | None = None) -> dict:
    api = _main()
    api._require_system_admin()
    return {"items": agent_eval_store.list_experiments(dataset_id)}


@router.get("/api/admin/agent-experiments/{experiment_id}")
def admin_agent_experiment_detail(experiment_id: str) -> dict:
    api = _main()
    api._require_system_admin()
    data = agent_eval_store.get_experiment(experiment_id)
    if data is None:
        raise HTTPException(status_code=404, detail="实验不存在")
    return data


@router.get("/api/admin/agent-comm/approvals")
def admin_agent_comm_approvals(status: str | None = "PENDING") -> dict:
    api = _main()
    api._require_system_admin()
    from rag_demo.mcp_agent_comm.store import CommError, open_admin_store

    store = open_admin_store()
    try:
        all_items = store.list_approvals(status=None)
        items = [item for item in all_items if not status or item["status"] == status.upper()]
        return {
            "items": items,
            "stats": {
                "pending": sum(1 for item in all_items if item["status"] == "PENDING"),
                "approved": sum(1 for item in all_items if item["status"] == "APPROVED"),
                "rejected": sum(1 for item in all_items if item["status"] == "REJECTED"),
            },
            "ttl_days": store.ttl_days,
        }
    finally:
        store.close()


@router.post("/api/admin/agent-comm/approvals/{approval_id}/decision")
def admin_agent_comm_approval_decision(approval_id: str, payload: AgentCommApprovalIn) -> dict:
    api = _main()
    account = api._require_system_admin()
    from rag_demo.mcp_agent_comm.store import CommError, open_admin_store

    store = open_admin_store()
    try:
        try:
            result = store.decide_approval(
                approval_id,
                action=payload.action,
                note=payload.note,
                actor=str((account or {}).get("username") or "admin"),
            )
        except CommError as exc:
            raise HTTPException(status_code=404 if exc.code == "APPROVAL_NOT_FOUND" else 400, detail=exc.message) from exc
        return result
    finally:
        store.close()


@router.get("/api/admin/agent-comm/messages")
def admin_agent_comm_messages(limit: int = 30) -> dict:
    api = _main()
    api._require_system_admin()
    from rag_demo.mcp_agent_comm.store import open_admin_store

    store = open_admin_store()
    try:
        return {"items": store.recent_messages(limit=limit), "ttl_days": store.ttl_days}
    finally:
        store.close()


@router.post("/api/admin/agent-comm/purge")
def admin_agent_comm_purge() -> dict:
    api = _main()
    api._require_system_admin()
    from rag_demo.mcp_agent_comm.store import open_admin_store

    store = open_admin_store()
    try:
        return store.purge_expired()
    finally:
        store.close()


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
