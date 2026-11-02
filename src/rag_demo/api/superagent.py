"""Super-agent HTTP API：事件入口、Thread/WorkItem、审批、Watchdog。"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import worker as sa_worker

router = APIRouter(prefix="/api/superagent", tags=["superagent"])
_BACKGROUND_TASKS: set[asyncio.Task] = set()


class EventIn(BaseModel):
    source: str = Field(default="manual", max_length=64)
    content: str = Field(..., min_length=1, max_length=4000)
    channel: str = Field(default="manual", max_length=64)
    thread_key: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_run: bool = False


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
    task = asyncio.create_task(asyncio.to_thread(sa_worker.run_work_item, work_item_id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


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
    app.include_router(router)
