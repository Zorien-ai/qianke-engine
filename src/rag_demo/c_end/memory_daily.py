"""C 端记忆生命周期：重要性、压缩、遗忘与每日日记。

设计约束：
- 日记和长期偏好严格分离：日记不自动反写偏好。
- 压缩只处理已有明确记忆，不新增“用户可能喜欢”。
- 重要性 5 的安全/边界记忆不自动压缩或遗忘。
- 失败安全：摘要写入成功后才归档原始记忆；日记失败不影响压缩。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from rag_demo.c_end import store

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
MEMORY_ACTIVE_LIMIT = 20
MEMORY_DIGEST_LIMIT = 10
DIARY_MAX_CHARS = 500

DiaryLLM = Callable[[list[dict[str, str]]], str]


def day_bounds_utc(day: str) -> tuple[str, str]:
    """把本地自然日转成 UTC ISO 区间。"""
    target = date.fromisoformat(str(day))
    start = datetime.combine(target, time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    end = datetime.combine(target + timedelta(days=1), time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    return start.isoformat(), end.isoformat()


def _transcript(rows: list[dict[str, Any]]) -> str:
    lines = []
    for row in rows:
        role = "用户" if row.get("role") == "user" else "小鱼"
        content = " ".join(str(row.get("content") or "").split())
        if content:
            lines.append(f"{role}：{content[:500]}")
    return "\n".join(lines)[-6000:]


def _fallback_llm(messages: list[dict[str, str]]) -> str:
    from rag_demo.generation.generator import chat_completion

    response = chat_completion(
        messages,
        temperature=0.4,
        max_tokens=300,
        deep_thinking=False,
        feature="c_diary",
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    return str(getattr(choices[0].message, "content", "") or "")


def _clean_diary(text: str) -> str:
    value = " ".join(str(text or "").split())
    if not value or len(value) > DIARY_MAX_CHARS:
        return ""
    # 日记不保存 PII；命中时宁可放弃当天的日记。
    from rag_demo.c_end.store import _MEMORY_PII_RE  # noqa: PLC0415

    if _MEMORY_PII_RE.search(value):
        return ""
    return value


def generate_diary(
    owner_id: str,
    day: str,
    *,
    llm: DiaryLLM | None = None,
) -> dict[str, Any] | None:
    """为开启日记的用户生成当天日记；已存在则幂等返回。"""
    if not store.get_diary_enabled(owner_id):
        return None
    existing = store.get_diary(owner_id, day)
    if existing is not None:
        return existing
    start, end = day_bounds_utc(day)
    rows = store.list_app_messages_between(owner_id, start, end)
    if not rows:
        return None
    transcript = _transcript(rows)
    if not transcript:
        return None
    messages = [
        {
            "role": "system",
            "content": (
                "你是 C 端伙伴小鱼。请只根据当天真实对话写一篇第一人称日记，"
                "不超过 500 字。不要推测用户没说过的偏好、身份或经历；"
                "不要写手机号、邮箱、地址；不要写营销话术。"
            ),
        },
        {"role": "user", "content": f"当天对话：\n{transcript}"},
    ]
    try:
        raw = (llm or _fallback_llm)(messages)
        content = _clean_diary(raw)
        if not content:
            return None
        return store.save_diary(
            owner_id,
            diary_date=day,
            content=content,
            source_message_count=len(rows),
        )
    except Exception:  # noqa: BLE001 - 日记失败不能影响压缩/遗忘
        logger.warning("C 端日记生成失败 owner=%s day=%s", owner_id, day, exc_info=True)
        return None


def _compress_group(owner_id: str, day: str, kind: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    contents: list[str] = []
    source_ids: list[str] = []
    importance = 1
    for item in items:
        content = str(item.get("content") or "").strip()
        if content and content not in contents:
            contents.append(content)
        source_ids.append(str(item.get("memory_id") or ""))
        importance = max(importance, int(item.get("importance") or 1))
    if not contents:
        return None
    digest = store.upsert_memory_digest(
        owner_id,
        period=day,
        kind=kind,
        content="；".join(contents)[:600],
        source_memory_ids=source_ids,
        importance=min(4, importance),
    )
    archived = store.archive_memories(owner_id, source_ids, digest_id=str(digest.get("digest_id") or ""))
    return {"digest_id": digest.get("digest_id"), "archived": archived, "kind": kind}


def compress_memories(owner_id: str, day: str) -> dict[str, Any]:
    """仅当 ACTIVE 记忆超过阈值时压缩低重要性内容。"""
    active = store.list_memories(owner_id, limit=500)
    if len(active) <= MEMORY_ACTIVE_LIMIT:
        return {"compressed": 0, "archived": 0, "digests": 0}
    candidates = [
        item for item in active
        if not int(item.get("pinned") or 0) and int(item.get("importance") or 3) < 5
    ]
    candidates.sort(key=lambda item: (int(item.get("importance") or 3), str(item.get("created_at") or "")))
    need = len(active) - MEMORY_ACTIVE_LIMIT
    selected = candidates[:need]
    if not selected:
        return {"compressed": 0, "archived": 0, "digests": 0}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        grouped.setdefault(str(item.get("kind") or "preference"), []).append(item)
    archived = 0
    digests = 0
    for kind, items in grouped.items():
        result = _compress_group(owner_id, day, kind, items)
        if result is None:
            continue
        digests += 1
        archived += int(result.get("archived") or 0)
    merged = store.merge_memory_digests(owner_id, limit=MEMORY_DIGEST_LIMIT)
    return {"compressed": len(selected), "archived": archived, "digests": digests, "digests_merged": merged}


def run_daily(owner_id: str, day: str, *, llm: DiaryLLM | None = None) -> dict[str, Any]:
    """单用户每日任务：降权 → 压缩/遗忘 → 写日记。"""
    decayed = 0
    compressed: dict[str, Any] = {"compressed": 0, "archived": 0, "digests": 0}
    diary = None
    error = ""
    try:
        decayed = store.decay_memories(owner_id)
    except Exception:  # noqa: BLE001
        logger.warning("C 端记忆降权失败 owner=%s", owner_id, exc_info=True)
        error = "DECAY_FAILED"
    try:
        compressed = compress_memories(owner_id, day)
    except Exception:  # noqa: BLE001
        logger.warning("C 端记忆压缩失败 owner=%s", owner_id, exc_info=True)
        error = "COMPRESS_FAILED"
    try:
        diary = generate_diary(owner_id, day, llm=llm)
    except Exception:  # noqa: BLE001
        logger.warning("C 端日记任务失败 owner=%s", owner_id, exc_info=True)
        error = "DIARY_FAILED"
    return {
        "owner_id": owner_id,
        "day": day,
        "decayed": decayed,
        "compressed": compressed,
        "diary_id": (diary or {}).get("diary_id") if diary else None,
        "error": error,
    }


def owners_for_day(day: str) -> list[str]:
    start, end = day_bounds_utc(day)
    return store.list_message_owner_ids_between(start, end)


def run_for_day(day: str, *, llm: DiaryLLM | None = None, limit: int = 1000) -> dict[str, Any]:
    owners = owners_for_day(day)[:limit]
    results = [run_daily(owner, day, llm=llm) for owner in owners]
    failed = [item for item in results if item.get("error")]
    return {
        "day": day,
        "owners": len(owners),
        "ok": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
