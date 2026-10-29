"""C 端 IM 社交壳（MVP mock）。

第一版只解决：
- 好友列表（含 mock 店宠）
- 单聊消息持久化
- WebSocket / HTTP 双入口
- 店宠 @ 唤醒的确定性 mock 回复

不做真实双人推送、商家 Agent 实盘接入；这些在下一阶段换真实消息总线。
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable

from rag_demo.c_end import store

# 与 store._now() 产出的 ISO 时间戳对齐（毫秒/微秒、时区后缀都可选）。
_ISO_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS c_friend (
    owner_id   TEXT NOT NULL,
    friend_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, friend_id)
);

CREATE TABLE IF NOT EXISTS c_message (
    message_id TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL,
    friend_id  TEXT NOT NULL,
    sender_id  TEXT NOT NULL,
    receiver_id TEXT NOT NULL,
    content    TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_message_owner_friend
    ON c_message (owner_id, friend_id, created_at);
"""


def init() -> None:
    with store._DB_LOCK:
        conn = store._connect()
        try:
            conn.executescript(_SCHEMA)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(c_message)").fetchall()}
            if "metadata_json" not in cols:
                conn.execute("ALTER TABLE c_message ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
            conn.commit()
        finally:
            conn.close()


def _ensure_friends(conn, owner_id: str) -> None:
    seeds = [
        ("store_demo", "山野户外旗舰店", "merchant", "品牌店宠 · 售前/售后/砍价"),
        ("friend_demo", "小满", "user", "好友 · 周末徒步搭子"),
    ]
    for friend_id, name, kind, note in seeds:
        conn.execute(
            "INSERT OR IGNORE INTO c_friend(owner_id, friend_id, name, kind, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, friend_id, name, kind, note, store._now()),
        )


def list_friends(owner_id: str) -> list[dict[str, Any]]:
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_friends(conn, owner_id)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM c_friend WHERE owner_id = ? "
            "ORDER BY CASE kind WHEN 'merchant' THEN 0 ELSE 1 END, name",
            (owner_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _friend(conn, owner_id: str, friend_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM c_friend WHERE owner_id = ? AND friend_id = ?",
        (owner_id, friend_id),
    ).fetchone()
    return dict(row) if row else None


def _message_payload(row) -> dict[str, Any]:
    payload = dict(row)
    try:
        payload["metadata"] = json.loads(payload.pop("metadata_json", "{}") or "{}")
    except (TypeError, ValueError):
        payload["metadata"] = {}
    return payload


def _parse_message_cursor(before: str | None) -> tuple[str | None, str | None]:
    """把 before 游标解析成 (created_at, message_id)。

    支持两种格式：
    - `created_at|message_id`：稳定游标，同一时间戳有多条消息时也不会重复/遗漏；
    - `created_at`：兼容只传时间戳的旧调用方（同一时间戳的消息可能跨页）。

    空游标返回 (None, None)；合法时间戳但解析失败时同样返回 (None, None)，
    调用方据此把非法游标当成“没有更早消息”处理。
    """
    text = str(before or "").strip()
    if not text:
        return None, None
    if "|" in text:
        created_at, _, message_id = text.partition("|")
        created_at = created_at.strip()
        message_id = message_id.strip()
    else:
        created_at, message_id = text, ""
    if not _ISO_TS_RE.fullmatch(created_at):
        return None, None
    return created_at, (message_id or None)


def get_messages(
    owner_id: str,
    friend_id: str,
    limit: int = 20,
    before: str | None = None,
) -> list[dict[str, Any]]:
    """会话历史：返回最近 N 条（按时间正序），before 用于加载更早一页。

    排序键是 (created_at, message_id)：同一 created_at 下用 message_id 兜底，
    保证翻页稳定、无重复无遗漏。非法 before 不回退到最新页（否则前端会反复
    拉到同一页），而是返回空页，让分页自然结束。
    """
    init()
    conn = store._connect()
    try:
        _ensure_friends(conn, owner_id)
        conn.commit()
        if _friend(conn, owner_id, friend_id) is None:
            raise store.CStoreError("FRIEND_NOT_FOUND", "好友不存在")
        limit_value = max(1, min(int(limit), 200))
        cursor_ts, cursor_message_id = _parse_message_cursor(before)
        if str(before or "").strip() and cursor_ts is None:
            return []
        where = "owner_id = ? AND friend_id = ?"
        params: list[Any] = [owner_id, friend_id]
        if cursor_ts:
            if cursor_message_id:
                where += " AND (created_at < ? OR (created_at = ? AND message_id < ?))"
                params.extend([cursor_ts, cursor_ts, cursor_message_id])
            else:
                where += " AND created_at < ?"
                params.append(cursor_ts)
        params.append(limit_value)
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM c_message WHERE "
            f"{where} ORDER BY created_at DESC, message_id DESC LIMIT ?) "
            "ORDER BY created_at ASC, message_id ASC",
            params,
        ).fetchall()
        return [_message_payload(row) for row in rows]
    finally:
        conn.close()


def _insert_message(
    conn,
    *,
    owner_id: str,
    friend_id: str,
    sender_id: str,
    receiver_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message_id = f"msg_{uuid.uuid4().hex[:20]}"
    created_at = store._now()
    meta = metadata or {}
    conn.execute(
        "INSERT INTO c_message(message_id, owner_id, friend_id, sender_id, receiver_id, content, metadata_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (message_id, owner_id, friend_id, sender_id, receiver_id, content, json.dumps(meta, ensure_ascii=False), created_at),
    )
    return {
        "message_id": message_id,
        "owner_id": owner_id,
        "friend_id": friend_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "metadata": meta,
        "created_at": created_at,
    }


def _mock_store_reply(content: str) -> tuple[str, bool]:
    text = content.strip()
    if "@店宠" not in text and "店宠" not in text:
        return "（店宠未被唤醒：请 @店宠 并说明售前、售后或砍价需求）", False
    if "砍价" in text or "优惠" in text or "券" in text:
        return "喵~ 收到砍价请求。当前是 mock 店宠，优惠需要用户确认后才会生效。", True
    return "喵~ 店宠已收到你的问题，当前是 mock 回复，后续接入商家 Agent 后会查商品库和 SOP。", True


def send_message(
    owner_id: str,
    friend_id: str,
    content: str,
    *,
    reply_provider: Callable[[str], tuple[str, bool]] | None = None,
    commentary_provider: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise store.CStoreError("EMPTY_MESSAGE", "消息不能为空")
    if len(text) > 1000:
        raise store.CStoreError("MESSAGE_TOO_LONG", "消息不能超过 1000 字")

    init()
    # 先读好友并提交，避免在 SQLite 写事务里调用 LLM。
    check = store._connect()
    try:
        _ensure_friends(check, owner_id)
        check.commit()
        friend = _friend(check, owner_id, friend_id)
    finally:
        check.close()
    if friend is None:
        raise store.CStoreError("FRIEND_NOT_FOUND", "好友不存在")

    reply_text: str | None = None
    awakened = False
    reply_metadata: dict[str, Any] = {}
    commentary = ""
    if friend["kind"] == "merchant":
        if reply_provider is not None:
            try:
                provider_result = reply_provider(text)
                if hasattr(provider_result, "text"):
                    reply_text = str(provider_result.text)
                    awakened = bool(provider_result.awakened)
                    reply_metadata = dict(getattr(provider_result, "metadata", {}) or {})
                else:
                    reply_text, awakened = provider_result
                    reply_metadata = {}
            except Exception:  # noqa: BLE001 - 店宠失败不应吞掉用户消息
                reply_text, awakened = _mock_store_reply(text)
                reply_metadata = {}
        else:
            reply_text, awakened = _mock_store_reply(text)
        if commentary_provider is not None:
            try:
                commentary = str(commentary_provider(text, reply_text) or "").strip()
            except Exception:  # noqa: BLE001 - 伙伴失败不影响店宠回复
                commentary = ""
        if reply_metadata.get("quote_id"):
            try:
                store.create_quote(owner_id, friend_id, reply_metadata)
            except Exception:  # noqa: BLE001 - 报价落库失败不应吞消息
                pass

    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_friends(conn, owner_id)
        owner_message = _insert_message(
            conn,
            owner_id=owner_id,
            friend_id=friend_id,
            sender_id=owner_id,
            receiver_id=friend_id,
            content=text,
        )
        reply = None
        companion_message = None
        if reply_text is not None:
            reply = _insert_message(
                conn,
                owner_id=owner_id,
                friend_id=friend_id,
                sender_id=friend_id,
                receiver_id=owner_id,
                content=reply_text,
                metadata=reply_metadata,
            )
            reply["awakened"] = awakened
        if commentary:
            companion_message = _insert_message(
                conn,
                owner_id=owner_id,
                friend_id=friend_id,
                sender_id=f"companion_{owner_id}",
                receiver_id=owner_id,
                content=commentary[:120],
            )
        conn.commit()
        return {
            "message": owner_message,
            "reply": reply,
            "companion_message": companion_message,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
