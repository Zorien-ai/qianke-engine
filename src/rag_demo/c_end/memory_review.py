"""C 端会话结束后的记忆复盘（Phase 3A）。

边界：
- 只处理 companion 会话；
- 只对「已空闲」的会话做一次复盘；
- 只生成 PENDING_CONFIRMATION 候选，不直接写 ACTIVE；
- 规则抽取，不调用 LLM，避免复盘本身产生幻觉；
- 依赖 QIANKE_C_MEMORY_WRITE_MODE=candidate；direct 模式跳过。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from rag_demo.c_end import store

logger = logging.getLogger(__name__)

DEFAULT_IDLE_MINUTES = 30
REVIEW_THREAD_ID = "companion"
DEFAULT_LOOKBACK_DAYS = 7


def idle_minutes() -> int:
    raw = os.environ.get("QIANKE_C_MEMORY_REVIEW_IDLE_MINUTES", str(DEFAULT_IDLE_MINUTES))
    try:
        return max(1, min(int(raw), 24 * 60))
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MINUTES


def _parse_iso(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _aware(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current


def _unique_user_items(messages: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    source_ids: list[str] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        if str(message.get("role") or "") != "user":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        extracted = store.extract_memories(content)
        if not extracted:
            continue
        message_id = str(message.get("message_id") or "")
        if message_id:
            source_ids.append(message_id)
        for item in extracted:
            key = (str(item.get("kind") or ""), str(item.get("content") or ""))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items, source_ids[-50:]


def review_owner(
    owner_id: str,
    *,
    now: datetime | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """复盘单个 C 端会话并生成候选；不改变 active memory。"""
    owner = str(owner_id or "").strip()
    if not owner:
        return {"owner_id": "", "ok": False, "reason": "OWNER_MISSING", "candidates": []}
    if store.memory_write_mode() != "candidate":
        return {
            "owner_id": owner,
            "ok": False,
            "reason": "CANDIDATE_MODE_DISABLED",
            "candidates": [],
        }

    current = _aware(now)
    cutoff = current - timedelta(minutes=idle_minutes())
    messages = store.list_app_messages(owner, REVIEW_THREAD_ID, limit=max(1, min(int(limit), 200)))
    if not messages:
        return {"owner_id": owner, "ok": False, "reason": "NO_MESSAGES", "candidates": []}

    last_at = _parse_iso(messages[-1].get("created_at"))
    if last_at is None:
        return {"owner_id": owner, "ok": False, "reason": "INVALID_MESSAGE_TIME", "candidates": []}
    if last_at > cutoff:
        return {
            "owner_id": owner,
            "ok": False,
            "reason": "NOT_IDLE",
            "last_message_at": last_at.isoformat(),
            "candidates": [],
        }

    items, source_ids = _unique_user_items(messages)
    if not items:
        return {"owner_id": owner, "ok": True, "reason": "NO_CANDIDATES", "candidates": []}

    candidates = store.create_memory_candidates(
        owner,
        items=items,
        source="session_review",
        source_message_ids=source_ids,
    )
    return {
        "owner_id": owner,
        "ok": True,
        "reason": "REVIEWED",
        "last_message_at": last_at.isoformat(),
        "reviewed_messages": len(messages),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def review_all(
    *,
    now: datetime | None = None,
    owners: list[str] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """复盘最近有消息的 owner；可显式传 owners 做单账号调试。"""
    current = _aware(now)
    if owners:
        selected = [str(owner).strip() for owner in owners if str(owner).strip()]
    else:
        start = (current - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
        selected = store.list_message_owner_ids_between(start, current.isoformat())

    results = [review_owner(owner, now=current, limit=limit) for owner in selected]
    return {
        "checked": len(results),
        "reviewed": sum(1 for item in results if item.get("reason") == "REVIEWED"),
        "candidates_created": sum(int(item.get("candidate_count") or 0) for item in results),
        "skipped": sum(1 for item in results if not item.get("ok")),
        "results": results,
    }
