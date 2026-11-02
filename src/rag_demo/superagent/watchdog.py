"""Super-agent 常驻 Watchdog：定期标记卡住的 RUNNING 工作项。"""
from __future__ import annotations

import logging
import os
import threading
import time

from rag_demo.superagent import store

logger = logging.getLogger(__name__)
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()


def _interval() -> int:
    try:
        return max(10, min(int(os.environ.get("QIANKE_SUPERAGENT_WATCHDOG_INTERVAL", "60")), 3600))
    except ValueError:
        return 60


def _timeout() -> int:
    try:
        return max(30, min(int(os.environ.get("QIANKE_SUPERAGENT_WATCHDOG_TIMEOUT", "180")), 7200))
    except ValueError:
        return 180


def scan_once() -> list[dict]:
    stuck = store.scan_stuck_work_items(timeout_seconds=_timeout())
    if stuck:
        logger.warning("Super-agent Watchdog 标记卡住工作项: %s", [item["work_item_id"] for item in stuck])
    return stuck


def _loop() -> None:
    while not _STOP.is_set():
        try:
            scan_once()
        except Exception:  # noqa: BLE001 - Watchdog 自身不能退出
            logger.exception("Super-agent Watchdog 扫描失败")
        _STOP.wait(_interval())


def start() -> bool:
    """幂等启动；由 API startup 事件调用。"""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="sa-watchdog", daemon=True)
        _THREAD.start()
        logger.info("Super-agent Watchdog 已启动 interval=%ss timeout=%ss", _interval(), _timeout())
        return True


def stop() -> None:
    _STOP.set()
    with _LOCK:
        global _THREAD
        _THREAD = None


def enabled() -> bool:
    return (os.environ.get("QIANKE_SUPERAGENT_WATCHDOG_ENABLED") or "0").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }
