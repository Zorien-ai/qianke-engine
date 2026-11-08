"""运维探针与指标：/ready、/metrics。"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(tags=["ops"])
_STARTED_AT = time.time()


def _check(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        fn()
        return {"name": name, "ok": True, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    except Exception as exc:  # noqa: BLE001 - 探针只暴露类型，不泄露连接串
        return {
            "name": name,
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": type(exc).__name__,
        }


def readiness() -> tuple[bool, dict[str, Any]]:
    from rag_demo.control import get_control_repository
    from rag_demo.merchant import get_merchant_repository
    from rag_demo.superagent import store as sa_store

    def control_health():
        repo = get_control_repository()
        try:
            return repo.health()
        finally:
            repo.close()

    checks = [
        _check("control_store", control_health),
        _check("superagent_store", lambda: sa_store.work_item_stats()),
        _check("queue", lambda: sa_store.job_stats()),
        _check(
            "merchant_store",
            lambda: get_merchant_repository().list_products(sa_store.DEFAULT_MERCHANT_ID, limit=1),
        ),
    ]
    ok = all(item["ok"] for item in checks)
    return ok, {"status": "ok" if ok else "degraded", "checks": checks, "at": int(time.time())}


def metrics_text() -> str:
    from rag_demo.c_end import store as c_store
    from rag_demo.superagent import store as sa_store

    lines = [
        "# HELP qianke_up 1 if the process is running",
        "# TYPE qianke_up gauge",
        "qianke_up 1",
        "# HELP qianke_process_start_time_seconds Process start time",
        "# TYPE qianke_process_start_time_seconds gauge",
        f"qianke_process_start_time_seconds {_STARTED_AT:.3f}",
    ]

    def add(name: str, help_text: str, values: dict[str, Any]) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        for key, value in sorted(values.items()):
            label = str(key).lower().replace('"', "")
            lines.append(f'{name}{{status="{label}"}} {value}')

    jobs = sa_store.job_stats()
    add("qianke_queue_jobs", "Super-agent jobs by status", {
        key: jobs.get(key, 0) for key in ("pending", "running", "done", "failed", "dead")
    })
    items = sa_store.work_item_stats()
    add("qianke_work_items", "Super-agent work items by status", items)
    approvals = sa_store.approval_stats()
    add("qianke_approvals", "Approvals by approval/execution status", approvals)
    try:
        tenants = c_store.list_tenants()
        lines.extend([
            "# HELP qianke_tenants Total merchant tenants",
            "# TYPE qianke_tenants gauge",
            f"qianke_tenants {len(tenants)}",
        ])
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines) + "\n"


def _check_metrics_token(request: Request, token: str | None) -> None:
    expected = (os.environ.get("QIANKE_METRICS_TOKEN") or "").strip()
    if not expected:
        return
    provided = (
        request.headers.get("X-Metrics-Token")
        or (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        or (request.query_params.get("token") if token is None else token)
        or ""
    ).strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="指标鉴权失败")


@router.get("/ready")
def ready() -> JSONResponse:
    ok, payload = readiness()
    return JSONResponse(status_code=200 if ok else 503, content=payload)


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request, token: str | None = Query(default=None)) -> str:
    _check_metrics_token(request, token)
    return metrics_text()


def register_ops(app) -> None:
    app.include_router(router)
