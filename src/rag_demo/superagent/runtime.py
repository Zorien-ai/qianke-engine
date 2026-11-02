"""Super-agent Worker 运行管理：后台线程、协作式取消。"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rag_demo.superagent import store as sa_store
from rag_demo.superagent import worker as sa_worker

logger = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sa-worker")
_CANCEL_EVENTS: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def start_worker(work_item_id: str) -> bool:
    with _LOCK:
        if work_item_id in _CANCEL_EVENTS:
            return False
        event = threading.Event()
        _CANCEL_EVENTS[work_item_id] = event
    _EXECUTOR.submit(_run, work_item_id, event)
    return True


def _run(work_item_id: str, cancel_event: threading.Event) -> None:
    try:
        sa_worker.run_work_item(work_item_id, cancel_event=cancel_event)
    finally:
        with _LOCK:
            _CANCEL_EVENTS.pop(work_item_id, None)


def stop_worker(work_item_id: str, note: str = "cancelled by user") -> dict[str, Any]:
    with _LOCK:
        event = _CANCEL_EVENTS.get(work_item_id)
    if event is not None:
        event.set()
    return sa_store.cancel_work_item(work_item_id, note=note)


def stop_all() -> None:
    with _LOCK:
        events = list(_CANCEL_EVENTS.values())
    for event in events:
        event.set()
