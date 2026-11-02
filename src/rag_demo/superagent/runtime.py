"""Super-agent 持久化 Worker 队列：原子 claim、租约、重试、启动恢复。"""
from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rag_demo.superagent import store as sa_store
from rag_demo.superagent import worker as sa_worker

logger = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sa-worker")
_CANCEL_EVENTS: dict[str, threading.Event] = {}
_JOB_BY_WORK_ITEM: dict[str, str] = {}
_LOCK = threading.Lock()
_DISPATCHER: threading.Thread | None = None
_WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _dispatcher_enabled() -> bool:
    return (os.environ.get("QIANKE_SUPERAGENT_QUEUE_DISPATCHER") or "1").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }


def start_worker(work_item_id: str) -> bool:
    """入队并提交执行；同一 WorkItem 不会重复建 Job。"""
    job = sa_store.enqueue_job(work_item_id, kind="WORKER")
    if job.get("status") != "PENDING":
        return False
    _submit(job["job_id"])
    return True


def start_action(work_item_id: str) -> bool:
    """审批通过后入队执行动作；与 Worker 使用同一持久化队列。"""
    job = sa_store.enqueue_job(work_item_id, kind="ACTION")
    if job.get("status") != "PENDING":
        return False
    _submit(job["job_id"])
    return True


def resume_job(job_id: str) -> bool:
    """死信/失败 Job 重放后，通知本地 dispatcher 立即尝试领取。"""
    job = sa_store.get_job(job_id)
    if job is None or job.get("status") != "PENDING":
        return False
    _submit(job_id)
    return True


def _submit(job_id: str) -> None:
    with _LOCK:
        if job_id in _CANCEL_EVENTS:
            return
        event = threading.Event()
        _CANCEL_EVENTS[job_id] = event
        _JOB_BY_WORK_ITEM[sa_store.get_job(job_id)["work_item_id"]] = job_id
    _EXECUTOR.submit(_run_job, job_id, event)


def _run_job(job_id: str, cancel_event: threading.Event) -> None:
    job = sa_store.claim_job(job_id, _WORKER_ID)
    if job is None:
        with _LOCK:
            _CANCEL_EVENTS.pop(job_id, None)
        return
    _execute_claimed(job, cancel_event)
    with _LOCK:
        _CANCEL_EVENTS.pop(job_id, None)
        _JOB_BY_WORK_ITEM.pop(job["work_item_id"], None)


def _heartbeat(job_id: str, worker_id: str, stop: threading.Event) -> None:
    import time

    while not stop.wait(60):
        try:
            sa_store.renew_lease(job_id, worker_id)
        except Exception:  # noqa: BLE001
            logger.exception("Super-agent Job 续租失败 job=%s", job_id)


def _execute_claimed(job: dict[str, Any], cancel_event: threading.Event | None = None) -> None:
    job_id = job["job_id"]
    work_item_id = job["work_item_id"]
    cancel_event = cancel_event or threading.Event()
    stop_heartbeat = threading.Event()
    heartbeat = None
    if job.get("worker_id"):
        heartbeat = threading.Thread(
            target=_heartbeat,
            args=(job_id, job["worker_id"], stop_heartbeat),
            name=f"sa-heartbeat-{job_id[-6:]}",
            daemon=True,
        )
        heartbeat.start()
    try:
        if job["kind"] == "ACTION":
            _run_action_job(job, work_item_id)
            return
        current = sa_store.get_work_item(work_item_id)
        if current is None:
            sa_store.finish_job(job_id, "FAILED", error="work item not found")
            return
        if current["status"] not in ("PENDING", "RUNNING"):
            sa_store.finish_job(job_id, "DONE", error=f"skipped status={current['status']}")
            return
        result = sa_worker.run_work_item(work_item_id, cancel_event=cancel_event)
        status = result.get("status")
        job_status = "DONE" if status in {
            "WAITING_APPROVAL",
            "DONE",
            "REJECTED",
            "CANCELLED",
            "EXECUTING",
            "EXECUTION_FAILED",
        } else "FAILED"
        sa_store.finish_job(job_id, job_status, error=str(result.get("error") or ""))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Super-agent Job 执行异常 job=%s", job_id)
        if int(job.get("attempts") or 0) < int(job.get("max_attempts") or 2):
            sa_store.retry_job(job_id, error=str(exc))
        else:
            sa_store.finish_job(job_id, "DEAD", error=str(exc))
    finally:
        stop_heartbeat.set()
        if heartbeat is not None:
            heartbeat.join(timeout=2)


def _run_action_job(job: dict[str, Any], work_item_id: str) -> None:
    from rag_demo.superagent import actions as sa_actions
    from rag_demo.superagent import wecom_send

    current = sa_store.get_work_item(work_item_id)
    if current is None:
        sa_store.finish_job(job["job_id"], "FAILED", error="work item not found")
        return
    if current["status"] != "EXECUTING":
        sa_store.finish_job(job["job_id"], "DONE", error=f"skipped status={current['status']}")
        return
    result = sa_actions.execute_approved(work_item_id)
    try:
        wecom_send.notify_work_item(result, stage="APPROVED")
    except Exception:  # noqa: BLE001
        logger.exception("Super-agent 动作结果回写失败 work_item=%s", work_item_id)
    sa_store.finish_job(
        job["job_id"],
        "DONE",
        error=str(result.get("error") or ""),
    )


def stop_worker(work_item_id: str, note: str = "cancelled by user") -> dict[str, Any]:
    with _LOCK:
        job_id = _JOB_BY_WORK_ITEM.get(work_item_id)
        event = _CANCEL_EVENTS.get(job_id) if job_id else None
    if event is not None:
        event.set()
    return sa_store.cancel_work_item(work_item_id, note=note)


def stop_all() -> None:
    with _LOCK:
        events = list(_CANCEL_EVENTS.values())
    for event in events:
        event.set()


def recover_jobs() -> int:
    """启动恢复：过期租约重新入队，PENDING Job 重新提交。"""
    requeued = sa_store.requeue_expired_jobs()
    pending = sa_store.pending_jobs(limit=50)
    for job in pending:
        _submit(job["job_id"])
    if requeued or pending:
        logger.info("Super-agent 队列恢复 requeued=%s pending=%s", requeued, len(pending))
    return len(pending)


def _dispatch_loop() -> None:
    import time

    while True:
        try:
            recover_jobs()
        except Exception:  # noqa: BLE001
            logger.exception("Super-agent 队列 dispatcher 失败")
        time.sleep(15)


def start_dispatcher() -> bool:
    """API 启动时调用；负责重启恢复和后续 PENDING Job 的重新提交。"""
    global _DISPATCHER
    if not _dispatcher_enabled():
        return False
    with _LOCK:
        if _DISPATCHER is not None and _DISPATCHER.is_alive():
            return False
        _DISPATCHER = threading.Thread(target=_dispatch_loop, name="sa-queue-dispatcher", daemon=True)
        _DISPATCHER.start()
        logger.info("Super-agent 队列 dispatcher 已启动")
        return True


def run_worker_loop(poll_seconds: float = 2.0, stop_event: threading.Event | None = None) -> None:
    """独立 Worker 进程主循环：轮询 claim_next_job，带租约心跳。"""
    import time

    stop_event = stop_event or threading.Event()
    sa_store.requeue_expired_jobs()
    logger.info("Super-agent 独立 Worker 启动 worker_id=%s", _WORKER_ID)
    while not stop_event.is_set():
        try:
            job = sa_store.claim_next_job(_WORKER_ID)
            if job is None:
                stop_event.wait(max(0.2, float(poll_seconds)))
                continue
            logger.info("Super-agent Worker 领取 job=%s kind=%s", job["job_id"], job["kind"])
            _execute_claimed(job)
        except Exception:  # noqa: BLE001
            logger.exception("Super-agent 独立 Worker 循环异常")
            stop_event.wait(max(0.5, float(poll_seconds)))
