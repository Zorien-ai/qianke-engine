"""Super-agent HTTP API：事件入口、Thread/WorkItem、审批、Watchdog。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import runtime as sa_runtime
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import triggers as sa_triggers
from rag_demo.superagent import watchdog as sa_watchdog

router = APIRouter(prefix="/api/superagent", tags=["superagent"])


class EventIn(BaseModel):
    source: str = Field(default="manual", max_length=64)
    content: str = Field(..., min_length=1, max_length=4000)
    channel: str = Field(default="manual", max_length=64)
    thread_key: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_run: bool = False


class BatchEventIn(BaseModel):
    events: list[EventIn] = Field(..., min_length=1, max_length=50)


class ApproveIn(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=1000)


class WatchdogIn(BaseModel):
    timeout_seconds: int = Field(default=180, ge=10, le=3600)


def _account() -> dict[str, Any]:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    if not account.get("is_system_admin"):
        from rag_demo.c_end import store as c_store

        if c_store.get_merchant_member(account["id"]) is None:
            raise HTTPException(status_code=403, detail="当前账号没有 Super-agent 权限")
    return account


def _start(work_item_id: str) -> None:
    if not sa_runtime.start_worker(work_item_id):
        raise HTTPException(status_code=409, detail="工作项已经在运行")


@router.post("/events")
async def ingest_event(req: EventIn) -> dict[str, Any]:
    _account()
    try:
        result = sa_router.ingest_event(
            source=req.source,
            content=req.content,
            channel=req.channel,
            thread_key=req.thread_key,
            metadata=req.metadata,
        )
    except sa_store.store.CStoreError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc
    if result.get("accepted") and req.auto_run and result.get("work_item"):
        item = result["work_item"]
        if item["status"] == "PENDING":
            _start(item["work_item_id"])
            result["auto_run_started"] = True
    return result


@router.post("/events/batch")
def ingest_event_batch(req: BatchEventIn) -> dict[str, Any]:
    """批量事件：Router 一次处理多条 Trigger，同一 Thread 只建一个 WorkItem。"""
    _account()
    payload = [event.model_dump() for event in req.events]
    for event in payload:
        event.pop("auto_run", None)
    return sa_router.ingest_batch(payload)


@router.post("/webhooks/{provider}")
async def inbound_webhook(provider: str, request: Request) -> dict[str, Any]:
    """通用 IM/外部事件入口；用共享密钥保护，供企业微信/飞书中转调用。"""
    provided = request.headers.get("X-Superagent-Secret")
    if not sa_triggers.verify_webhook_secret(provided):
        raise HTTPException(status_code=401, detail="Webhook 密钥未配置或不正确")
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="请求体必须是 JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体必须是对象")
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    return sa_triggers.ingest_async(
        source=f"webhook:{provider[:32]}",
        content=content,
        channel=str(body.get("channel") or provider)[:64],
        thread_key=str(body.get("thread_key") or "").strip() or None,
        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
    )


@router.get("/threads")
def list_threads(limit: int = 50) -> dict[str, Any]:
    _account()
    return {"threads": sa_store.list_threads(limit=limit)}


@router.get("/work-items")
def list_work_items(limit: int = 50) -> dict[str, Any]:
    _account()
    return {"work_items": sa_store.list_work_items(limit=limit)}


@router.get("/work-items/{work_item_id}")
def get_work_item(work_item_id: str) -> dict[str, Any]:
    _account()
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="工作项不存在")
    return item


@router.post("/work-items/{work_item_id}/run")
async def run_work_item(work_item_id: str) -> dict[str, Any]:
    _account()
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="工作项不存在")
    if item["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"工作项当前状态为 {item['status']}，不能启动")
    sa_store.start_work_item(work_item_id)
    _start(work_item_id)
    return {"work_item_id": work_item_id, "status": "RUNNING", "started": True}


@router.post("/work-items/{work_item_id}/stop")
def stop_work_item(work_item_id: str) -> dict[str, Any]:
    _account()
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="工作项不存在")
    if item["status"] not in ("PENDING", "RUNNING"):
        raise HTTPException(status_code=409, detail=f"工作项当前状态为 {item['status']}，不能停止")
    updated = sa_runtime.stop_worker(work_item_id)
    return {"work_item_id": work_item_id, "status": updated.get("status"), "stopped": True}


@router.post("/work-items/{work_item_id}/approve")
def approve_work_item(work_item_id: str, req: ApproveIn) -> dict[str, Any]:
    _account()
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="工作项不存在")
    if item["status"] != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail="工作项不在待审批状态")
    return sa_store.decide_approval(work_item_id, approved=req.approved, note=req.note)


@router.post("/watchdog")
def watchdog(req: WatchdogIn) -> dict[str, Any]:
    _account()
    stuck = sa_store.scan_stuck_work_items(timeout_seconds=req.timeout_seconds)
    return {"stuck_count": len(stuck), "work_items": stuck}


def register_superagent(app) -> None:
    # 主应用使用 lifespan；on_startup/on_event 在这个 FastAPI 版本不会被执行。
    # 常驻 Watchdog 是独立 daemon 线程，在注册 API 时启动，测试环境由 env 关闭。
    if sa_watchdog.enabled():
        sa_watchdog.start()
    app.include_router(router)
