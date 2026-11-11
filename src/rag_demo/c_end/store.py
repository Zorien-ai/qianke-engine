"""C 端模拟商品/订单存储（SQLite，第一版 mock）。

设计约束：
- 商品价格、库存、订单金额来自确定性存储，不由 LLM 生成。
- 订单创建必须经过 prepare → 用户确认 → confirm 两步。
- confirm 绑定 confirmation_token + 订单快照；内容变化后旧 token 失效。
- request_id 唯一，重复确认不会重复扣库存/重复生成订单。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rag_demo.c_end import mentions
from rag_demo.c_end import persona as c_persona
from rag_demo.config import BASE_DIR
from rag_demo.merchant import (
    MerchantError,
    get_merchant_repository,
    get_merchant_write_repository,
)

_DB_LOCK = threading.Lock()
_DB_PATH: Path | None = None

# C 端店宠/商城使用的商家数据域。真实接入时 merchant_id 必须由登录态推导，
# 不允许从请求体传入；这里只有单一的联调店铺映射。
_MERCHANT_ID = "m_gear_002"
_MERCHANT_BUYER_IDS = {
    "buyer_1": "b_2001",
    "buyer_2": "b_2002",
}


def _merchant_buyer_id(buyer_id: str) -> str:
    return _MERCHANT_BUYER_IDS.get(str(buyer_id or ""), str(buyer_id or ""))


class CStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        raw = os.environ.get("QIANKE_C_END_DB") or str(Path(BASE_DIR) / "var" / "c_end_mock.sqlite")
        _DB_PATH = Path(raw)
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


# ==================== 自定义头像（受控文件存储） ====================
# 安全边界：
# - 只接受 PNG / JPEG / WebP，且同时校验声明的 MIME、大小与文件魔数；
# - 文件名与相对路径完全由服务端生成（owner token + kind + uuid），用户无法控制；
# - DB 只存相对路径，读取时再次校验必须落在受控根目录内；
# - 每个 owner 一个子目录，读取接口只解析当前登录账号自己的记录。
AVATAR_KINDS = ("companion", "user")
AVATAR_MAX_BYTES = 1024 * 1024
AVATAR_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}
_AVATAR_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_AVATAR_PATH_RE = re.compile(r"^[0-9a-f]{16}/(companion|user)_[0-9a-f]{32}\.(png|jpg|webp)$")
_AVATAR_COLUMNS = {"companion": "avatar_path", "user": "user_avatar_path"}
_AVATAR_ROOT: Path | None = None


def _avatar_root() -> Path:
    """头像受控根目录；QIANKE_C_END_AVATAR_DIR 可覆盖（测试/部署用）。"""
    global _AVATAR_ROOT
    if _AVATAR_ROOT is None:
        raw = os.environ.get("QIANKE_C_END_AVATAR_DIR") or str(
            Path(BASE_DIR) / "var" / "c_end_avatars"
        )
        _AVATAR_ROOT = Path(raw)
        _AVATAR_ROOT.mkdir(parents=True, exist_ok=True)
    return _AVATAR_ROOT


def _normalize_avatar_kind(kind: str) -> str:
    value = str(kind or "").strip().lower()
    if value not in AVATAR_KINDS:
        raise CStoreError("INVALID_AVATAR_KIND", "头像类型只支持 companion / user")
    return value


def _detect_avatar_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate_avatar(data: bytes, content_type: str) -> tuple[str, str]:
    """服务端校验头像：MIME 白名单 + 大小上限 + 文件魔数。返回 (扩展名, 标准 MIME)。"""
    mime = str(content_type or "").split(";")[0].strip().lower()
    ext = AVATAR_CONTENT_TYPES.get(mime)
    if ext is None:
        raise CStoreError("INVALID_AVATAR_TYPE", "头像只支持 PNG / JPEG / WebP")
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise CStoreError("EMPTY_AVATAR", "头像文件为空")
    if len(data) > AVATAR_MAX_BYTES:
        raise CStoreError("AVATAR_TOO_LARGE", "头像不能超过 1MB")
    if _detect_avatar_type(bytes(data)) != ext:
        raise CStoreError("INVALID_AVATAR_CONTENT", "头像内容与声明的图片类型不一致")
    return ext, _AVATAR_MEDIA_TYPES[ext]


def _avatar_owner_token(owner_id: str) -> str:
    return hashlib.sha256(str(owner_id).encode("utf-8")).hexdigest()[:16]


def _resolve_avatar_path(relative: str) -> Path | None:
    """把 DB 中的相对路径解析成受控目录内的真实文件；非法路径一律拒绝。"""
    rel = str(relative or "").strip()
    if not rel:
        return None
    if not _AVATAR_PATH_RE.fullmatch(rel):
        raise CStoreError("AVATAR_NOT_FOUND", "头像路径不合法")
    root = _avatar_root().resolve()
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        raise CStoreError("AVATAR_NOT_FOUND", "头像路径不合法")
    return candidate if candidate.is_file() else None


def _delete_avatar_file(relative: str) -> None:
    try:
        path = _resolve_avatar_path(relative)
    except CStoreError:
        return
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # 清理旧文件失败不影响新头像生效。
            pass


def _avatar_url(path: str | None, kind: str) -> str:
    """对外 URL 由服务端拼接；带内容版本号，换头像后能绕过浏览器缓存。"""
    rel = str(path or "").strip()
    if not rel:
        return ""
    version = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:12]
    return f"/api/c/companion/avatar/{kind}?v={version}"


def save_companion_avatar(
    owner_id: str,
    kind: str,
    data: bytes,
    content_type: str,
) -> dict[str, Any]:
    """保存买家/伙伴头像：唯一写入口，文件与 DB 路径均由服务端生成。"""
    normalized_kind = _normalize_avatar_kind(kind)
    ext, media_type = validate_avatar(data, content_type)
    column = _AVATAR_COLUMNS[normalized_kind]
    init()
    relative = f"{_avatar_owner_token(owner_id)}/{normalized_kind}_{uuid.uuid4().hex}.{ext}"
    root = _avatar_root()
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.tmp")
    try:
        temp_path.write_bytes(bytes(data))
        os.replace(temp_path, target)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise CStoreError("AVATAR_WRITE_FAILED", "头像保存失败，请稍后重试") from exc

    previous_path = ""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_companion(conn, owner_id)
        previous_path = str(row[column] or "")
        conn.execute(
            f"UPDATE c_companion SET {column} = ?, updated_at = ? WHERE owner_id = ?",
            (relative, _now(), owner_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        target.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

    if previous_path and previous_path != relative:
        _delete_avatar_file(previous_path)

    payload = get_companion(owner_id)
    payload["uploaded_avatar"] = {
        "kind": normalized_kind,
        "content_type": media_type,
        "bytes": len(data),
        "url": payload["avatar_url"] if normalized_kind == "companion" else payload["user_avatar_url"],
    }
    return payload


def clear_companion_avatar(owner_id: str, kind: str) -> dict[str, Any]:
    """恢复默认头像：清空 DB 相对路径并删除受控目录内的旧文件。"""
    normalized_kind = _normalize_avatar_kind(kind)
    column = _AVATAR_COLUMNS[normalized_kind]
    init()
    previous_path = ""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_companion(conn, owner_id)
        previous_path = str(row[column] or "")
        conn.execute(
            f"UPDATE c_companion SET {column} = '', updated_at = ? WHERE owner_id = ?",
            (_now(), owner_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if previous_path:
        _delete_avatar_file(previous_path)
    payload = get_companion(owner_id)
    payload["cleared_avatar"] = {"kind": normalized_kind}
    return payload


def get_companion_avatar(owner_id: str, kind: str) -> tuple[bytes, str] | None:
    """读取当前 owner 自己的头像字节；未设置或文件缺失返回 None。"""
    normalized_kind = _normalize_avatar_kind(kind)
    column = _AVATAR_COLUMNS[normalized_kind]
    init()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM c_companion WHERE owner_id = ?", (owner_id,)).fetchone()
        relative = str(row[column] or "") if row is not None else ""
    finally:
        conn.close()
    path = _resolve_avatar_path(relative)
    if path is None:
        return None
    ext = path.suffix.lstrip(".").lower()
    media_type = _AVATAR_MEDIA_TYPES.get(ext, "application/octet-stream")
    try:
        return path.read_bytes(), media_type
    except OSError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_APP_MSG_CLOCK = datetime(2000, 1, 1, tzinfo=timezone.utc)
_APP_MSG_CLOCK_LOCK = threading.Lock()


def _next_message_time() -> str:
    """消息时间戳单调递增，避免 Windows 时钟粒度导致同秒排序不稳定。"""
    global _APP_MSG_CLOCK
    with _APP_MSG_CLOCK_LOCK:
        now = datetime.now(timezone.utc)
        if now <= _APP_MSG_CLOCK:
            now = _APP_MSG_CLOCK + timedelta(microseconds=1)
        _APP_MSG_CLOCK = now
        return now.isoformat(timespec="microseconds")


_next_app_message_time = _next_message_time


_CEND_PG_INITIALIZED_SCHEMA: str | None = None


def _cend_pg_enabled() -> bool:
    value = (os.environ.get("QIANKE_CEND_BACKEND") or "sqlite").strip().lower()
    return value in {"postgres", "postgresql", "pg"}


def _ensure_pg_schema() -> None:
    global _CEND_PG_INITIALIZED_SCHEMA
    from rag_demo.control.postgres_repository import PostgresControlRepository
    from rag_demo.control.settings import pg_settings

    schema = pg_settings()["schema"]
    if _CEND_PG_INITIALIZED_SCHEMA == schema:
        return
    repo = PostgresControlRepository()
    try:
        repo.init_schema()
    finally:
        repo.close()
    _CEND_PG_INITIALIZED_SCHEMA = schema
    # 首次启动补默认店宠映射；schema 保持纯结构，契约测试仍能看到空表。
    try:
        from rag_demo.control.pg_compat import connect as pg_connect
        conn = pg_connect()
        try:
            row = conn.execute(
                "SELECT 1 AS ok FROM c_merchant_store_friend WHERE friend_id = ?",
                ("store_demo",),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO c_merchant_store_friend(merchant_id, friend_id, created_at) "
                    "VALUES (?, ?, ?)",
                    ("m_gear_002", "store_demo", _now()),
                )
                conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - 启动补种失败不阻断控制面
        pass


def _connect() -> sqlite3.Connection:
    if _cend_pg_enabled():
        from rag_demo.control.pg_compat import connect

        _ensure_pg_schema()
        return connect()  # type: ignore[return-value]
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS c_product (
    product_id  TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       REAL NOT NULL CHECK (price >= 0),
    stock       INTEGER NOT NULL CHECK (stock >= 0),
    status      TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS c_order (
    order_id          TEXT PRIMARY KEY,
    buyer_id          TEXT NOT NULL,
    status            TEXT NOT NULL,
    total_amount      REAL NOT NULL,
    original_amount   REAL NOT NULL DEFAULT 0,
    discount_amount   REAL NOT NULL DEFAULT 0,
    quote_id          TEXT,
    policy_ids_json   TEXT NOT NULL DEFAULT '[]',
    confirmation_hash TEXT,
    snapshot_json     TEXT NOT NULL,
    idempotency_key   TEXT UNIQUE,
    source_order_id   TEXT,
    created_at        TEXT NOT NULL,
    confirmed_at      TEXT
);

CREATE TABLE IF NOT EXISTS c_quote (
    quote_id          TEXT PRIMARY KEY,
    buyer_id          TEXT NOT NULL,
    friend_id         TEXT NOT NULL,
    product_refs_json TEXT NOT NULL,
    policy_refs_json  TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'PENDING',
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_order_item (
    order_id   TEXT NOT NULL REFERENCES c_order(order_id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES c_product(product_id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

CREATE TABLE IF NOT EXISTS c_companion (
    owner_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    user_nickname TEXT NOT NULL DEFAULT '',
    species    TEXT NOT NULL DEFAULT 'digital_companion',
    persona    TEXT NOT NULL DEFAULT 'warm',
    appearance TEXT NOT NULL DEFAULT '',
    level      INTEGER NOT NULL DEFAULT 1,
    exp        INTEGER NOT NULL DEFAULT 0,
    satiety    INTEGER NOT NULL DEFAULT 60,
    avatar_path      TEXT NOT NULL DEFAULT '',
    user_avatar_path TEXT NOT NULL DEFAULT '',
    diary_enabled    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_companion_memory (
    memory_id  TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL,
    kind       TEXT NOT NULL,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'explicit',
    importance INTEGER NOT NULL DEFAULT 3,
    reinforced_count INTEGER NOT NULL DEFAULT 1,
    last_reinforced_at TEXT,
    last_decayed_at TEXT,
    status     TEXT NOT NULL DEFAULT 'ACTIVE',
    pinned     INTEGER NOT NULL DEFAULT 0,
    compressed_into TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_id, kind, content)
);

CREATE INDEX IF NOT EXISTS idx_c_companion_memory_owner
    ON c_companion_memory (owner_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS c_companion_memory_digest (
    digest_id  TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL,
    period     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    content    TEXT NOT NULL,
    source_memory_ids TEXT NOT NULL DEFAULT '[]',
    importance INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_id, period, kind)
);

CREATE INDEX IF NOT EXISTS idx_c_companion_memory_digest_owner
    ON c_companion_memory_digest (owner_id, period DESC);

CREATE TABLE IF NOT EXISTS c_companion_diary (
    diary_id   TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL,
    diary_date TEXT NOT NULL,
    content    TEXT NOT NULL,
    source_message_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_id, diary_date)
);

CREATE INDEX IF NOT EXISTS idx_c_companion_diary_owner
    ON c_companion_diary (owner_id, diary_date DESC);

CREATE TABLE IF NOT EXISTS b_chat_user_profile (
    profile_id         TEXT PRIMARY KEY,
    merchant_id        TEXT NOT NULL,
    buyer_id           TEXT NOT NULL,
    version            INTEGER NOT NULL DEFAULT 1,
    profile_json       TEXT NOT NULL,
    profile_text       TEXT NOT NULL,
    confidence         REAL NOT NULL DEFAULT 0,
    source_message_count INTEGER NOT NULL DEFAULT 0,
    source_session_ids TEXT NOT NULL DEFAULT '[]',
    last_message_at    TEXT,
    extracted_at       TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (merchant_id, buyer_id)
);

CREATE INDEX IF NOT EXISTS idx_b_chat_user_profile_scope
    ON b_chat_user_profile (merchant_id, status, extracted_at DESC);

CREATE TABLE IF NOT EXISTS b_chat_user_profile_vector (
    profile_id  TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    buyer_id    TEXT NOT NULL,
    embedding   TEXT,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_b_chat_user_profile_vector_scope
    ON b_chat_user_profile_vector (merchant_id);

CREATE TABLE IF NOT EXISTS c_companion_rhythm (
    owner_id          TEXT PRIMARY KEY,
    enabled           INTEGER NOT NULL DEFAULT 0,
    timezone          TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    quiet_start       TEXT NOT NULL DEFAULT '22:00',
    quiet_end         TEXT NOT NULL DEFAULT '09:00',
    last_active_at    TEXT,
    last_checkin_at   TEXT,
    pause_until       TEXT,
    unanswered_count  INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_companion_checkin (
    checkin_id  TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    ref_id      TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    due_at      TEXT NOT NULL,
    delivered_at TEXT,
    status      TEXT NOT NULL DEFAULT 'PENDING',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_companion_checkin_owner
    ON c_companion_checkin (owner_id, status, due_at);

CREATE TABLE IF NOT EXISTS c_logistics_event (
    event_id     TEXT PRIMARY KEY,
    provider     TEXT NOT NULL DEFAULT '',
    order_id     TEXT NOT NULL,
    status       TEXT NOT NULL,
    occurred_at  TEXT,
    payload_hash TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_logistics_event_order
    ON c_logistics_event (order_id, created_at DESC);

CREATE TABLE IF NOT EXISTS c_inventory_alert (
    alert_id       TEXT PRIMARY KEY,
    merchant_id    TEXT NOT NULL,
    product_id     TEXT NOT NULL,
    sku            TEXT NOT NULL,
    sku_spec       TEXT NOT NULL DEFAULT '',
    available_qty  INTEGER NOT NULL,
    safety_stock   INTEGER NOT NULL,
    reorder_qty    INTEGER NOT NULL,
    severity       TEXT NOT NULL DEFAULT 'WARNING',
    status         TEXT NOT NULL DEFAULT 'PENDING',
    channel        TEXT NOT NULL DEFAULT 'IN_APP',
    message        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    acknowledged_at TEXT,
    acknowledged_by INTEGER,
    resolved_at    TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_c_inventory_alert_sku
    ON c_inventory_alert (merchant_id, sku);

CREATE INDEX IF NOT EXISTS idx_c_inventory_alert_queue
    ON c_inventory_alert (merchant_id, status, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS c_app_message (
    message_id  TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_after_sale (
    ticket_id      TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL REFERENCES c_order(order_id),
    buyer_id       TEXT NOT NULL,
    type           TEXT NOT NULL,
    reason         TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'OPEN',
    refund_amount  REAL,
    return_tracking_no TEXT,
    return_carrier TEXT,
    return_shipped_at TEXT,
    received_at    TEXT,
    restocked_at   TEXT,
    created_at     TEXT NOT NULL,
    resolved_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_c_app_message_owner_thread
    ON c_app_message (owner_id, thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_c_after_sale_order
    ON c_after_sale (order_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_c_after_sale_open
    ON c_after_sale (order_id) WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS c_reconciliation_run (
    run_id        TEXT PRIMARY KEY,
    trigger       TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT NOT NULL,
    ok            INTEGER NOT NULL,
    checked       INTEGER NOT NULL,
    legacy        INTEGER NOT NULL,
    issue_count   INTEGER NOT NULL,
    issues_json   TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_c_reconciliation_started
    ON c_reconciliation_run (started_at DESC);

CREATE TABLE IF NOT EXISTS c_reconciliation_alert (
    alert_id    TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    order_id    TEXT NOT NULL,
    issue       TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'WARNING',
    message     TEXT NOT NULL,
    suggestion  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    read_at     TEXT,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_c_reconciliation_alert_open
    ON c_reconciliation_alert (resolved_at, read_at, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS c_merchant_member (
    account_id  INTEGER PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'owner',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_merchant_store_friend (
    merchant_id TEXT NOT NULL,
    friend_id   TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (merchant_id, friend_id)
);

CREATE INDEX IF NOT EXISTS idx_c_merchant_store_friend_merchant
    ON c_merchant_store_friend (merchant_id);

CREATE TABLE IF NOT EXISTS c_merchant_tenant (
    merchant_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_merchant_policy (
    merchant_id              TEXT PRIMARY KEY,
    allowed_actions_json     TEXT NOT NULL DEFAULT '[]',
    compensation_max_amount  REAL NOT NULL DEFAULT 50,
    refund_max_amount        REAL NOT NULL DEFAULT 1000,
    require_note             INTEGER NOT NULL DEFAULT 0,
    updated_by               TEXT NOT NULL DEFAULT '',
    updated_at               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_tenant_provision (
    provision_id    TEXT PRIMARY KEY,
    merchant_id     TEXT NOT NULL,
    owner_account_id INTEGER NOT NULL,
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_merchant_policy_audit (
    policy_audit_id TEXT PRIMARY KEY,
    merchant_id     TEXT NOT NULL,
    changed_by      TEXT NOT NULL DEFAULT '',
    before_json     TEXT NOT NULL DEFAULT '{}',
    after_json      TEXT NOT NULL DEFAULT '{}',
    changed_at      TEXT NOT NULL,
    prev_hash       TEXT NOT NULL DEFAULT '',
    entry_hash      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS c_policy_audit_anchor (
    anchor_id        TEXT PRIMARY KEY,
    merchant_id      TEXT NOT NULL,
    checked          INTEGER NOT NULL,
    head_hash        TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    prev_anchor_hash TEXT NOT NULL DEFAULT '',
    anchor_hash      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_policy_audit_anchor_merchant
    ON c_policy_audit_anchor (merchant_id, created_at);

CREATE TRIGGER IF NOT EXISTS trg_c_policy_audit_anchor_no_update
BEFORE UPDATE ON c_policy_audit_anchor
BEGIN
    SELECT RAISE(ABORT, 'c_policy_audit_anchor is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_c_policy_audit_anchor_no_delete
BEFORE DELETE ON c_policy_audit_anchor
BEGIN
    SELECT RAISE(ABORT, 'c_policy_audit_anchor is append-only');
END;

CREATE TABLE IF NOT EXISTS c_login_attempt (
    attempt_key  TEXT PRIMARY KEY,
    window_start REAL NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS c_compensation (
    compensation_id TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL,
    buyer_id        TEXT NOT NULL,
    merchant_id     TEXT NOT NULL,
    work_item_id    TEXT NOT NULL DEFAULT '',
    amount          REAL NOT NULL,
    reason          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(order_id)
);

CREATE TABLE IF NOT EXISTS c_mention (
    mention_id  TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    token       TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    target_name TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    read_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_c_mention_owner_target
    ON c_mention (owner_id, target_id, created_at);

CREATE TABLE IF NOT EXISTS c_thread_read (
    owner_id     TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    last_read_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, thread_id)
);
"""

_SEED = (
    ("P001", "m_demo", "轻量跑鞋", "运动", 299.0, 20),
    ("P002", "m_demo", "通勤双肩包", "箱包", 199.0, 15),
    ("P003", "m_demo", "保温杯", "生活", 89.0, 50),
    ("P004", "m_demo", "蓝牙耳机", "数码", 399.0, 12),
    ("P005", "m_demo", "运动 T 恤", "运动", 129.0, 30),
    ("P006", "m_demo", "防晒衣", "户外", 159.0, 18),
)


def init() -> None:
    if _cend_pg_enabled():
        _ensure_pg_schema()
        return
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            after_sale_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(c_after_sale)").fetchall()
            }
            for name, ddl in (
                ("return_tracking_no", "TEXT"),
                ("return_carrier", "TEXT"),
                ("return_shipped_at", "TEXT"),
                ("received_at", "TEXT"),
                ("restocked_at", "TEXT"),
            ):
                if name not in after_sale_columns:
                    conn.execute(f"ALTER TABLE c_after_sale ADD COLUMN {name} {ddl}")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(c_order)").fetchall()}
            for name, ddl in (
                ("source_order_id", "TEXT"),
                ("original_amount", "REAL NOT NULL DEFAULT 0"),
                ("discount_amount", "REAL NOT NULL DEFAULT 0"),
                ("quote_id", "TEXT"),
                ("policy_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE c_order ADD COLUMN {name} {ddl}")
            count = conn.execute("SELECT COUNT(*) AS n FROM c_product").fetchone()["n"]
            if count == 0:
                conn.executemany(
                    "INSERT INTO c_product(product_id, merchant_id, title, category, price, stock) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    _SEED,
                )
            tenant_count = conn.execute("SELECT COUNT(*) AS n FROM c_merchant_tenant").fetchone()["n"]
            if tenant_count == 0:
                conn.executemany(
                    "INSERT INTO c_merchant_tenant(merchant_id, name, status, created_at) "
                    "VALUES (?, ?, 'ACTIVE', ?)",
                    (
                        ("m_gear_002", "山野户外旗舰店", _now()),
                        ("m_tea_001", "山雾茶业", _now()),
                    ),
                )
            mapping_count = conn.execute(
                "SELECT COUNT(*) AS n FROM c_merchant_store_friend"
            ).fetchone()["n"]
            if mapping_count == 0:
                conn.execute(
                    "INSERT INTO c_merchant_store_friend(merchant_id, friend_id, created_at) "
                    "VALUES (?, ?, ?)",
                    ("m_gear_002", "store_demo", _now()),
                )
            # 伙伴表轻量迁移：老库补 user_nickname 列，并把历史默认名「小伴」迁到「小鱼」。
            companion_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(c_companion)").fetchall()
            }
            if "user_nickname" not in companion_columns:
                conn.execute(
                    "ALTER TABLE c_companion ADD COLUMN user_nickname TEXT NOT NULL DEFAULT ''"
                )
            # 自定义头像迁移：旧库补 avatar_path / user_avatar_path，默认空 = 未设置头像。
            for column_name, column_ddl in (
                ("avatar_path", "TEXT NOT NULL DEFAULT ''"),
                ("user_avatar_path", "TEXT NOT NULL DEFAULT ''"),
                ("diary_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column_name not in companion_columns:
                    conn.execute(
                        f"ALTER TABLE c_companion ADD COLUMN {column_name} {column_ddl}"
                    )
            # 记忆生命周期迁移：重要性、强化、归档状态。老库只补列，不改已有数据。
            memory_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(c_companion_memory)").fetchall()
            }
            for column_name, column_ddl in (
                ("importance", "INTEGER NOT NULL DEFAULT 3"),
                ("reinforced_count", "INTEGER NOT NULL DEFAULT 1"),
                ("last_reinforced_at", "TEXT"),
                ("last_decayed_at", "TEXT"),
                ("status", "TEXT NOT NULL DEFAULT 'ACTIVE'"),
                ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                ("compressed_into", "TEXT"),
            ):
                if column_name not in memory_columns:
                    conn.execute(
                        f"ALTER TABLE c_companion_memory ADD COLUMN {column_name} {column_ddl}"
                    )
            conn.execute(
                "UPDATE c_companion SET name = ? WHERE name = '小伴' AND user_nickname = ''",
                (c_persona.DEFAULT_NAME,),
            )
            audit_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(c_merchant_policy_audit)").fetchall()
            }
            for column_name in ("prev_hash", "entry_hash"):
                if column_name not in audit_columns:
                    conn.execute(
                        f"ALTER TABLE c_merchant_policy_audit ADD COLUMN {column_name} "
                        "TEXT NOT NULL DEFAULT ''"
                    )
            conn.commit()
        finally:
            conn.close()


def get_merchant_member(account_id: int) -> dict[str, Any] | None:
    """读取账号绑定的商家租户；B 端工作台只允许访问该商家。"""
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM c_merchant_member WHERE account_id = ?",
            (int(account_id),),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def bind_merchant_member(
    account_id: int,
    merchant_id: str,
    *,
    role: str = "owner",
) -> dict[str, Any]:
    merchant_id = str(merchant_id or "").strip()
    role = str(role or "owner").strip() or "owner"
    if not merchant_id:
        raise CStoreError("INVALID_MERCHANT", "merchant_id 不能为空")
    init()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_merchant_member(account_id, merchant_id, role, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET "
            "merchant_id = excluded.merchant_id, role = excluded.role",
            (int(account_id), merchant_id, role, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    row = get_merchant_member(account_id)
    assert row is not None
    return row


def list_tenants() -> list[dict[str, Any]]:
    """租户列表（管理端），包含成员数。"""
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM c_merchant_member m "
            "WHERE m.merchant_id = t.merchant_id) AS member_count "
            "FROM c_merchant_tenant t ORDER BY t.created_at ASC, t.merchant_id ASC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_tenant(merchant_id: str) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM c_merchant_tenant WHERE merchant_id = ?", (str(merchant_id).strip(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_tenant(merchant_id: str, name: str) -> dict[str, Any]:
    merchant_id = str(merchant_id or "").strip()
    name = str(name or "").strip()
    if not merchant_id or len(merchant_id) > 64:
        raise CStoreError("INVALID_MERCHANT", "merchant_id 不能为空且不能超过 64 字")
    if not name or len(name) > 80:
        raise CStoreError("INVALID_MERCHANT_NAME", "租户名称不能为空且不能超过 80 字")
    init()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_merchant_tenant(merchant_id, name, status, created_at) "
            "VALUES (?, ?, 'ACTIVE', ?) ON CONFLICT(merchant_id) DO UPDATE SET name = excluded.name",
            (merchant_id, name, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    tenant = get_tenant(merchant_id)
    assert tenant is not None
    return tenant


POLICY_ACTIONS = (
    "CANCEL_ORDER",
    "CREATE_AFTER_SALE",
    "SHIP_ORDER",
    "COMPLETE_ORDER",
    "REFUND_AFTER_SALE",
    "RECEIVE_RETURN",
    "REJECT_AFTER_SALE",
    "ISSUE_COMPENSATION",
)


def provision_tenant(
    merchant_id: str,
    name: str,
    owner_account_id: int,
    *,
    compensation_max_amount: float = 50,
    refund_max_amount: float = 1000,
    allowed_actions: list[str] | tuple[str, ...] | None = None,
    created_by: str = "",
) -> dict[str, Any]:
    """开通租户：创建/更新租户 + 绑定 owner + 初始化动作策略。"""
    merchant_id = str(merchant_id or "").strip()
    if not merchant_id:
        raise CStoreError("INVALID_MERCHANT", "merchant_id 不能为空")
    owner_account_id = int(owner_account_id)
    if owner_account_id <= 0:
        raise CStoreError("INVALID_OWNER", "owner_account_id 不合法")
    existing = get_merchant_member(owner_account_id)
    if existing is not None and existing["merchant_id"] != merchant_id:
        raise CStoreError(
            "ACCOUNT_ALREADY_BOUND",
            f"账号已绑定商家 {existing['merchant_id']}，请先解绑",
        )
    tenant = create_tenant(merchant_id, name)
    member = bind_merchant_member(owner_account_id, merchant_id, role="owner")
    policy = upsert_merchant_policy(
        merchant_id,
        allowed_actions=list(allowed_actions or POLICY_ACTIONS),
        compensation_max_amount=compensation_max_amount,
        refund_max_amount=refund_max_amount,
        require_note=False,
        updated_by=created_by,
    )
    init()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_tenant_provision(provision_id, merchant_id, owner_account_id, "
            "created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                f"tp_{uuid.uuid4().hex[:16]}",
                merchant_id,
                owner_account_id,
                str(created_by or "")[:64],
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"tenant": tenant, "member": member, "policy": policy}


def list_tenant_provisions(merchant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_tenant_provision WHERE merchant_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (str(merchant_id or "").strip(), max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _policy_payload(row: sqlite3.Row | None, merchant_id: str) -> dict[str, Any]:
    if row is None:
        return {
            "merchant_id": merchant_id,
            "allowed_actions": list(POLICY_ACTIONS),
            "compensation_max_amount": 50.0,
            "refund_max_amount": 1000.0,
            "require_note": False,
            "updated_by": "",
            "updated_at": "",
        }
    try:
        allowed = json.loads(row["allowed_actions_json"] or "[]")
    except (TypeError, ValueError):
        allowed = []
    return {
        "merchant_id": row["merchant_id"],
        "allowed_actions": [str(item) for item in allowed if str(item) in POLICY_ACTIONS],
        "compensation_max_amount": float(row["compensation_max_amount"]),
        "refund_max_amount": float(row["refund_max_amount"]),
        "require_note": bool(row["require_note"]),
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
    }


def get_merchant_policy(merchant_id: str) -> dict[str, Any]:
    merchant_id = str(merchant_id or "").strip()
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM c_merchant_policy WHERE merchant_id = ?", (merchant_id,)
        ).fetchone()
        return _policy_payload(row, merchant_id)
    finally:
        conn.close()


def _audit_chain_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev_hash}|{canonical}".encode("utf-8")).hexdigest()


def upsert_merchant_policy(
    merchant_id: str,
    *,
    allowed_actions: list[str] | tuple[str, ...],
    compensation_max_amount: float,
    refund_max_amount: float,
    require_note: bool = False,
    updated_by: str = "",
) -> dict[str, Any]:
    merchant_id = str(merchant_id or "").strip()
    if not merchant_id:
        raise CStoreError("INVALID_MERCHANT", "merchant_id 不能为空")
    clean_actions = []
    for action in allowed_actions or ():
        action = str(action or "").strip().upper()
        if action and action not in clean_actions:
            clean_actions.append(action)
    invalid = [action for action in clean_actions if action not in POLICY_ACTIONS]
    if invalid:
        raise CStoreError("INVALID_ACTION", f"未知动作：{','.join(invalid)}")
    if not clean_actions:
        raise CStoreError("INVALID_POLICY", "至少保留一个允许动作")
    compensation = float(compensation_max_amount)
    refund = float(refund_max_amount)
    if not (0 <= compensation <= 100000):
        raise CStoreError("INVALID_POLICY", "补偿上限必须在 0~100000 元之间")
    if not (0 <= refund <= 100000):
        raise CStoreError("INVALID_POLICY", "退款上限必须在 0~100000 元之间")
    before = get_merchant_policy(merchant_id)
    after = {
        "merchant_id": merchant_id,
        "allowed_actions": clean_actions,
        "compensation_max_amount": compensation,
        "refund_max_amount": refund,
        "require_note": bool(require_note),
        "updated_by": str(updated_by or "")[:64],
    }
    changed = any(
        before.get(key) != after.get(key)
        for key in ("allowed_actions", "compensation_max_amount", "refund_max_amount", "require_note")
    )
    init()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_merchant_policy(merchant_id, allowed_actions_json, "
            "compensation_max_amount, refund_max_amount, require_note, updated_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(merchant_id) DO UPDATE SET "
            "allowed_actions_json = excluded.allowed_actions_json, "
            "compensation_max_amount = excluded.compensation_max_amount, "
            "refund_max_amount = excluded.refund_max_amount, "
            "require_note = excluded.require_note, updated_by = excluded.updated_by, "
            "updated_at = excluded.updated_at",
            (
                merchant_id,
                json.dumps(clean_actions, ensure_ascii=False),
                compensation,
                refund,
                1 if require_note else 0,
                str(updated_by or "")[:64],
                _now(),
            ),
        )
        if changed:
            changed_at = _now()
            audit_id = f"pau_{uuid.uuid4().hex[:16]}"
            last = conn.execute(
                "SELECT entry_hash FROM c_merchant_policy_audit "
                "WHERE merchant_id = ? AND entry_hash != '' "
                "ORDER BY changed_at DESC, policy_audit_id DESC LIMIT 1",
                (merchant_id,),
            ).fetchone()
            prev_hash = str(last["entry_hash"]) if last else ""
            payload = {
                "policy_audit_id": audit_id,
                "merchant_id": merchant_id,
                "changed_by": str(updated_by or "")[:64],
                "before": before,
                "after": after,
                "changed_at": changed_at,
            }
            entry_hash = _audit_chain_hash(prev_hash, payload)
            conn.execute(
                "INSERT INTO c_merchant_policy_audit(policy_audit_id, merchant_id, changed_by, "
                "before_json, after_json, changed_at, prev_hash, entry_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_id,
                    merchant_id,
                    str(updated_by or "")[:64],
                    json.dumps(before, ensure_ascii=False),
                    json.dumps(after, ensure_ascii=False),
                    changed_at,
                    prev_hash,
                    entry_hash,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return get_merchant_policy(merchant_id)


def _audit_time_bound(value: str, *, end: bool = False) -> str:
    text = str(value or "").strip().replace(" ", "T")
    if len(text) == 10:
        return text + ("T23:59:59.999999" if end else "T00:00:00")
    return text


def query_policy_audit(
    merchant_id: str,
    limit: int = 20,
    offset: int = 0,
    *,
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    merchant_id = str(merchant_id or "").strip()
    where = ["merchant_id = ?"]
    params: list[Any] = [merchant_id]
    if date_from:
        if _cend_pg_enabled():
            where.append("(changed_at)::timestamptz >= ?::timestamptz")
        else:
            where.append("datetime(changed_at) >= datetime(?)")
        params.append(_audit_time_bound(date_from))
    if date_to:
        if _cend_pg_enabled():
            where.append("(changed_at)::timestamptz <= ?::timestamptz")
        else:
            where.append("datetime(changed_at) <= datetime(?)")
        params.append(_audit_time_bound(date_to, end=True))
    clause = " AND ".join(where)
    init()
    conn = _connect()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM c_merchant_policy_audit WHERE {clause}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM c_merchant_policy_audit WHERE {clause} "
            "ORDER BY changed_at DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(int(limit), 5000)), max(0, int(offset))),
        ).fetchall()
        items = [
            {
                "policy_audit_id": row["policy_audit_id"],
                "merchant_id": row["merchant_id"],
                "changed_by": row["changed_by"],
                "before": json.loads(row["before_json"] or "{}"),
                "after": json.loads(row["after_json"] or "{}"),
                "changed_at": row["changed_at"],
                "prev_hash": row["prev_hash"] or "",
                "entry_hash": row["entry_hash"] or "",
            }
            for row in rows
        ]
        return {"items": items, "total": int(total), "limit": limit, "offset": offset}
    finally:
        conn.close()


def anchor_policy_audit(merchant_id: str) -> dict[str, Any]:
    """把当前审计链头写入只追加锚点表，用于检测删除尾部/截断。"""
    merchant_id = str(merchant_id or "").strip()
    chain = verify_policy_audit_chain(merchant_id)
    if not chain.get("ok"):
        raise CStoreError("AUDIT_CHAIN_BROKEN", "策略审计链校验失败，拒绝写入锚点")
    init()
    conn = _connect()
    try:
        last = conn.execute(
            "SELECT anchor_hash FROM c_policy_audit_anchor WHERE merchant_id = ? "
            "ORDER BY created_at DESC, anchor_id DESC LIMIT 1",
            (merchant_id,),
        ).fetchone()
        prev_hash = str(last["anchor_hash"]) if last else ""
        created_at = _now()
        anchor_id = f"paa_{uuid.uuid4().hex[:16]}"
        payload = {
            "anchor_id": anchor_id,
            "merchant_id": merchant_id,
            "checked": int(chain.get("checked") or 0),
            "head_hash": str(chain.get("head_hash") or ""),
            "created_at": created_at,
        }
        anchor_hash = _audit_chain_hash(prev_hash, payload)
        conn.execute(
            "INSERT INTO c_policy_audit_anchor(anchor_id, merchant_id, checked, head_hash, "
            "created_at, prev_anchor_hash, anchor_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                anchor_id,
                merchant_id,
                payload["checked"],
                payload["head_hash"],
                created_at,
                prev_hash,
                anchor_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "anchor_id": anchor_id,
        "merchant_id": merchant_id,
        "checked": payload["checked"],
        "head_hash": payload["head_hash"],
        "anchor_hash": anchor_hash,
    }


def verify_policy_audit_anchor(merchant_id: str) -> dict[str, Any]:
    """校验锚点自身链，并检查当前审计链是否覆盖锚点前缀。"""
    merchant_id = str(merchant_id or "").strip()
    init()
    conn = _connect()
    try:
        anchors = conn.execute(
            "SELECT * FROM c_policy_audit_anchor WHERE merchant_id = ? "
            "ORDER BY created_at ASC, anchor_id ASC",
            (merchant_id,),
        ).fetchall()
        entries = conn.execute(
            "SELECT entry_hash FROM c_merchant_policy_audit "
            "WHERE merchant_id = ? AND entry_hash != '' "
            "ORDER BY changed_at ASC, policy_audit_id ASC",
            (merchant_id,),
        ).fetchall()
        prev_anchor_hash = ""
        for anchor in anchors:
            payload = {
                "anchor_id": anchor["anchor_id"],
                "merchant_id": anchor["merchant_id"],
                "checked": int(anchor["checked"]),
                "head_hash": anchor["head_hash"],
                "created_at": anchor["created_at"],
            }
            expected = _audit_chain_hash(prev_anchor_hash, payload)
            if anchor["prev_anchor_hash"] != prev_anchor_hash or anchor["anchor_hash"] != expected:
                return {"ok": False, "anchors": len(anchors), "reason": "ANCHOR_CHAIN_BROKEN"}
            checked = int(anchor["checked"])
            if len(entries) < checked:
                return {"ok": False, "anchors": len(anchors), "reason": "AUDIT_TRUNCATED"}
            if checked > 0 and entries[checked - 1]["entry_hash"] != anchor["head_hash"]:
                return {"ok": False, "anchors": len(anchors), "reason": "ANCHOR_MISMATCH"}
            prev_anchor_hash = expected
        return {
            "ok": True,
            "anchors": len(anchors),
            "checked": len(entries),
            "head_hash": prev_anchor_hash,
        }
    finally:
        conn.close()


def list_policy_audit(merchant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return query_policy_audit(merchant_id, limit=limit)["items"]


def verify_policy_audit_chain(merchant_id: str) -> dict[str, Any]:
    """校验策略审计哈希链；只校验启用链式哈希后的记录。"""
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_merchant_policy_audit "
            "WHERE merchant_id = ? AND entry_hash != '' "
            "ORDER BY changed_at ASC, policy_audit_id ASC",
            (str(merchant_id or "").strip(),),
        ).fetchall()
        prev_hash = ""
        for row in rows:
            payload = {
                "policy_audit_id": row["policy_audit_id"],
                "merchant_id": row["merchant_id"],
                "changed_by": row["changed_by"],
                "before": json.loads(row["before_json"] or "{}"),
                "after": json.loads(row["after_json"] or "{}"),
                "changed_at": row["changed_at"],
            }
            expected = _audit_chain_hash(prev_hash, payload)
            if row["prev_hash"] != prev_hash or row["entry_hash"] != expected:
                return {
                    "ok": False,
                    "merchant_id": merchant_id,
                    "checked": len(rows),
                    "broken_at": row["policy_audit_id"],
                    "reason": "HASH_MISMATCH",
                }
            prev_hash = expected
        return {
            "ok": True,
            "merchant_id": merchant_id,
            "checked": len(rows),
            "head_hash": prev_hash,
        }
    finally:
        conn.close()


def check_action_policy(
    merchant_id: str,
    action_type: str,
    *,
    amount: float | None = None,
    refund_amount: float | None = None,
) -> tuple[bool, str]:
    """执行前策略校验；返回 (allowed, code)。"""
    policy = get_merchant_policy(merchant_id)
    action_type = str(action_type or "").strip().upper()
    if action_type not in policy["allowed_actions"]:
        return False, "ACTION_NOT_ALLOWED_BY_POLICY"
    if action_type == "ISSUE_COMPENSATION" and amount is not None:
        if amount <= 0 or amount > policy["compensation_max_amount"]:
            return False, "COMPENSATION_EXCEEDS_POLICY"
    if action_type == "REFUND_AFTER_SALE" and refund_amount is not None:
        if refund_amount > policy["refund_max_amount"]:
            return False, "REFUND_EXCEEDS_POLICY"
    return True, ""


def list_merchant_members(merchant_id: str) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_merchant_member WHERE merchant_id = ? ORDER BY created_at ASC",
            (str(merchant_id).strip(),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def unbind_merchant_member(account_id: int) -> bool:
    init()
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM c_merchant_member WHERE account_id = ?", (int(account_id),)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def create_compensation(
    *,
    order_id: str,
    buyer_id: str,
    merchant_id: str,
    amount: float,
    reason: str,
    work_item_id: str = "",
) -> dict[str, Any]:
    """记录一笔模拟补偿（优惠券/现金补偿），一个订单只能有一笔。"""
    amount = float(amount or 0)
    reason = str(reason or "").strip()
    if amount <= 0 or amount > 1000:
        raise CStoreError("INVALID_COMPENSATION_AMOUNT", "补偿金额必须在 0~1000 元之间")
    if not reason or len(reason) > 300:
        raise CStoreError("INVALID_COMPENSATION_REASON", "补偿原因不能为空且不能超过 300 字")
    order = get_order(order_id)
    if order is None:
        raise CStoreError("ORDER_NOT_FOUND", "订单不存在")
    if order["buyer_id"] != buyer_id:
        raise CStoreError("ORDER_FORBIDDEN", "订单不属于当前买家")
    if get_merchant_repository().get_order(order_id, merchant_id=merchant_id) is None:
        raise CStoreError("ORDER_FORBIDDEN", "订单不属于当前商家")
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT 1 FROM c_compensation WHERE order_id = ?", (order_id,)
        ).fetchone():
            raise CStoreError("COMPENSATION_EXISTS", "该订单已经发放过补偿")
        compensation_id = f"cmp_{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT INTO c_compensation(compensation_id, order_id, buyer_id, merchant_id, "
            "work_item_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                compensation_id,
                order_id,
                buyer_id,
                merchant_id,
                work_item_id,
                amount,
                reason,
                _now(),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_compensation(order_id) or {}


def get_compensation(order_id: str) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM c_compensation WHERE order_id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_compensations(merchant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    init()
    where = "WHERE merchant_id = ?" if merchant_id else ""
    params: list[Any] = [merchant_id] if merchant_id else []
    params.append(max(1, min(int(limit), 200)))
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_compensation {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_products(category: str | None = None, keyword: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    init()
    where = ["status = 'ACTIVE'"]
    params: list[Any] = []
    if category:
        where.append("category = ?")
        params.append(category)
    if keyword:
        where.append("(title LIKE ? OR category LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    params.append(max(1, min(int(limit), 50)))
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_product WHERE {' AND '.join(where)} ORDER BY price ASC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot(items: list[dict[str, Any]]) -> str:
    return json.dumps(items, ensure_ascii=False, sort_keys=True)


def _validate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        raise CStoreError("EMPTY_ITEMS", "订单至少需要一个商品")
    merged: dict[str, int] = {}
    for item in items:
        product_id = str(item.get("product_id") or "").strip()
        try:
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError):
            raise CStoreError("INVALID_QUANTITY", "商品数量必须是正整数") from None
        if not product_id or quantity <= 0:
            raise CStoreError("INVALID_QUANTITY", "商品 ID 和数量必须有效")
        merged[product_id] = merged.get(product_id, 0) + quantity
    return [{"product_id": pid, "quantity": qty} for pid, qty in merged.items()]


def create_quote(
    buyer_id: str,
    friend_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    """把店宠结构化报价引用落库，供后续订单审计。"""
    quote_id = str(metadata.get("quote_id") or "").strip()
    if not quote_id:
        return None
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO c_quote(quote_id, buyer_id, friend_id, product_refs_json, "
            "policy_refs_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                quote_id,
                buyer_id,
                friend_id,
                json.dumps(metadata.get("product_refs") or [], ensure_ascii=False),
                json.dumps(metadata.get("policy_refs") or [], ensure_ascii=False),
                _now(),
            ),
        )
        conn.commit()
        return get_quote(quote_id, buyer_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_quote(quote_id: str, buyer_id: str | None = None) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM c_quote WHERE quote_id = ?", (quote_id,)).fetchone()
        if row is None:
            return None
        if buyer_id is not None and row["buyer_id"] != buyer_id:
            raise CStoreError("QUOTE_FORBIDDEN", "不能访问其他用户的报价")
        return {
            "quote_id": row["quote_id"],
            "buyer_id": row["buyer_id"],
            "friend_id": row["friend_id"],
            "product_refs": json.loads(row["product_refs_json"] or "[]"),
            "policy_refs": json.loads(row["policy_refs_json"] or "[]"),
            "status": row["status"],
            "created_at": row["created_at"],
        }
    finally:
        conn.close()


def _quote_items(conn: sqlite3.Connection, quote_id: str, buyer_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    row = conn.execute("SELECT * FROM c_quote WHERE quote_id = ?", (quote_id,)).fetchone()
    if row is None:
        raise CStoreError("QUOTE_NOT_FOUND", "报价不存在")
    if row["buyer_id"] != buyer_id:
        raise CStoreError("QUOTE_FORBIDDEN", "不能使用其他用户的报价")
    if row["status"] != "PENDING":
        raise CStoreError("QUOTE_NOT_PENDING", "报价已使用或已失效")
    products = json.loads(row["product_refs_json"] or "[]")
    policies = json.loads(row["policy_refs_json"] or "[]")
    items = [
        {"product_id": str(item["product_id"]), "quantity": int(item.get("quantity") or 1)}
        for item in products
        if item.get("product_id")
    ]
    if not items:
        raise CStoreError("QUOTE_NO_PRODUCTS", "报价没有可购买商品")
    policy_ids = [str(item.get("policy_id")) for item in policies if item.get("policy_id")]
    return items, policy_ids


def _quote_discount(original: float, policy_ids: list[str]) -> float:
    """只应用已配置、确定性的平台活动；C 伙伴/店宠不能自行发明优惠。"""
    if "platform_full_reduce" in policy_ids:
        if original >= 599:
            return 80.0
        if original >= 299:
            return 30.0
    return 0.0


def _merchant_error(exc: MerchantError) -> CStoreError:
    code = getattr(exc, "code", "MERCHANT_ERROR")
    mapped = {
        "MERCHANT_STOCK": "INSUFFICIENT_STOCK",
        "MERCHANT_NOT_FOUND": "PRODUCT_NOT_FOUND",
        "MERCHANT_EXPIRED": "MERCHANT_EXPIRED",
        "MERCHANT_CONFLICT": "MERCHANT_CONFLICT",
    }.get(code, "MERCHANT_UNAVAILABLE")
    return CStoreError(mapped, getattr(exc, "message", str(exc)))


def _reserve_merchant_stock(
    draft_id: str,
    buyer_id: str,
    products: list[dict[str, Any]],
) -> None:
    """在商家库存域预占；失败时抛结构化 CStoreError，由调用方回滚 C 草稿。"""
    try:
        get_merchant_write_repository().reserve_inventory(
            _MERCHANT_ID,
            draft_id,
            [
                {"product_id": item["product_id"], "quantity": item["quantity"]}
                for item in products
            ],
            ttl_seconds=900,
            buyer_id=_merchant_buyer_id(buyer_id),
        )
    except MerchantError as exc:
        raise _merchant_error(exc) from exc


def _release_merchant_reservation(draft_id: str) -> None:
    """取消草稿时尽力释放；已提交/已过期的预占不阻塞 C 端取消。"""
    try:
        get_merchant_write_repository().release_reservation(_MERCHANT_ID, draft_id)
    except MerchantError:
        pass


def prepare_order(
    buyer_id: str,
    items: list[dict[str, Any]],
    *,
    quote_id: str | None = None,
) -> dict[str, Any]:
    """生成待确认订单草稿；不扣 C 端库存，同时预占商家库存。"""
    init()
    conn = _connect()
    reservation_created = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        policy_ids: list[str] = []
        if quote_id:
            normalized, policy_ids = _quote_items(conn, quote_id, buyer_id)
        else:
            normalized = _validate_items(items)

        products: list[dict[str, Any]] = []
        original = 0.0
        for item in normalized:
            row = conn.execute(
                "SELECT * FROM c_product WHERE product_id = ? AND status = 'ACTIVE'",
                (item["product_id"],),
            ).fetchone()
            if row is None:
                raise CStoreError("PRODUCT_NOT_FOUND", f"商品不存在或已下架：{item['product_id']}")
            if row["stock"] < item["quantity"]:
                raise CStoreError("INSUFFICIENT_STOCK", f"库存不足：{row['title']}")
            unit_price = float(row["price"])
            original += unit_price * item["quantity"]
            products.append({
                "product_id": row["product_id"],
                "title": row["title"],
                "quantity": item["quantity"],
                "unit_price": unit_price,
            })

        discount = _quote_discount(original, policy_ids)
        total = max(0.0, original - discount)
        order_id = f"draft_{uuid.uuid4().hex[:16]}"
        token = secrets.token_urlsafe(24)
        snapshot = _snapshot(products)

        # C 端草稿和商家预占使用同一个 draft_id：确认/取消时可精确找回预占。
        _reserve_merchant_stock(order_id, buyer_id, products)
        reservation_created = True

        conn.execute(
            "INSERT INTO c_order(order_id, buyer_id, status, total_amount, original_amount, "
            "discount_amount, quote_id, policy_ids_json, confirmation_hash, snapshot_json, created_at) "
            "VALUES (?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                buyer_id,
                round(total, 2),
                round(original, 2),
                round(discount, 2),
                quote_id,
                json.dumps(policy_ids, ensure_ascii=False),
                _sha256(token),
                snapshot,
                _now(),
            ),
        )
        conn.executemany(
            "INSERT INTO c_order_item(order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            [(order_id, p["product_id"], p["quantity"], p["unit_price"]) for p in products],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        if reservation_created:
            _release_merchant_reservation(order_id)
        raise
    finally:
        conn.close()

    return {
        "order_id": order_id,
        "status": "DRAFT",
        "buyer_id": buyer_id,
        "items": products,
        "total_amount": round(total, 2),
        "original_amount": round(original, 2),
        "discount_amount": round(discount, 2),
        "quote_id": quote_id,
        "policy_ids": policy_ids,
        "confirmation_token": token,
        "confirmation_version": 1,
        "merchant_reservation_id": order_id,
        "message": "请确认订单内容后再提交；确认前商家库存已预占，C 端库存暂不扣减。",
    }


def confirm_order(
    buyer_id: str,
    draft_id: str,
    confirmation_token: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """确认草稿并创建正式模拟订单；按 request_id 幂等。"""
    init()
    if not draft_id or not confirmation_token:
        raise CStoreError("INVALID_CONFIRMATION", "缺少订单或确认凭证")
    if not request_id:
        request_id = f"req_c_{uuid.uuid4().hex[:16]}"

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM c_order WHERE idempotency_key = ?",
            (request_id,),
        ).fetchone()
        if existing is not None:
            if existing["buyer_id"] != buyer_id or existing["source_order_id"] != draft_id:
                raise CStoreError("IDEMPOTENCY_CONFLICT", "request_id 已用于其他订单")
            return _order_payload(conn, existing)

        draft = conn.execute(
            "SELECT * FROM c_order WHERE order_id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise CStoreError("ORDER_NOT_FOUND", "订单草稿不存在")
        if draft["buyer_id"] != buyer_id:
            raise CStoreError("ORDER_FORBIDDEN", "不能确认其他用户的订单")
        if draft["status"] != "DRAFT":
            raise CStoreError("ORDER_NOT_DRAFT", "订单已经处理，不能重复确认")
        if draft["confirmation_hash"] != _sha256(confirmation_token):
            raise CStoreError("INVALID_CONFIRMATION", "确认凭证无效")

        product_rows = conn.execute(
            "SELECT * FROM c_product WHERE product_id IN "
            "(SELECT product_id FROM c_order_item WHERE order_id = ?)",
            (draft_id,),
        ).fetchall()
        current = {row["product_id"]: row for row in product_rows}
        expected = json.loads(draft["snapshot_json"])
        expected_by_id = {item["product_id"]: item for item in expected}

        for item in expected:
            row = current.get(item["product_id"])
            if row is None or row["status"] != "ACTIVE":
                raise CStoreError("ORDER_CHANGED", "订单商品已下架，请重新准备订单")
            if float(row["price"]) != float(item["unit_price"]):
                raise CStoreError("ORDER_CHANGED", "订单价格已变化，请重新准备并确认")
            if row["stock"] < item["quantity"]:
                raise CStoreError("INSUFFICIENT_STOCK", f"库存不足：{row['title']}")

        order_id = "order_" + uuid.uuid4().hex[:16]
        merchant_total = round(float(draft["original_amount"] or draft["total_amount"]), 2)
        try:
            writer = get_merchant_write_repository()
            writer.create_order(
                _MERCHANT_ID,
                order_id,
                _merchant_buyer_id(buyer_id),
                [
                    {
                        "product_id": item["product_id"],
                        "quantity": item["quantity"],
                        "unit_price": item["unit_price"],
                    }
                    for item in expected
                ],
                str(merchant_total),
                source_ref=draft_id,
            )
            writer.commit_reservation(_MERCHANT_ID, draft_id, order_id=order_id)
        except MerchantError as exc:
            raise _merchant_error(exc) from exc

        for item in expected:
            conn.execute(
                "UPDATE c_product SET stock = stock - ? WHERE product_id = ?",
                (item["quantity"], item["product_id"]),
            )

        conn.execute(
            "INSERT INTO c_order(order_id, buyer_id, status, total_amount, original_amount, "
            "discount_amount, quote_id, policy_ids_json, snapshot_json, idempotency_key, "
            "source_order_id, created_at, confirmed_at) "
            "VALUES (?, ?, 'CONFIRMED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                buyer_id,
                draft["total_amount"],
                draft["original_amount"] or draft["total_amount"],
                draft["discount_amount"] or 0,
                draft["quote_id"],
                draft["policy_ids_json"] or "[]",
                draft["snapshot_json"],
                request_id,
                draft_id,
                _now(),
                _now(),
            ),
        )
        conn.executemany(
            "INSERT INTO c_order_item(order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            [(order_id, item["product_id"], item["quantity"], item["unit_price"]) for item in expected],
        )
        # 草稿只标记终态，不重复占用 idempotency_key（唯一约束在正式订单上）。
        conn.execute(
            "UPDATE c_order SET status = 'CONFIRMED' WHERE order_id = ?",
            (draft_id,),
        )
        if draft["quote_id"]:
            conn.execute(
                "UPDATE c_quote SET status = 'CONSUMED' WHERE quote_id = ?",
                (draft["quote_id"],),
            )
        _reward_companion_conn(conn, buyer_id)
        _schedule_order_followup_conn(conn, buyer_id, order_id)
        conn.commit()
        order = conn.execute("SELECT * FROM c_order WHERE order_id = ?", (order_id,)).fetchone()
        return _order_payload(conn, order)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_confirmed_order(
    buyer_id: str,
    order_id: str,
    *,
    request_id: str | None = None,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    """取消已确认订单：商家模拟退款/恢复商家库存，再恢复 C 库存并标记 CANCELLED。"""
    init()
    row = get_order(order_id)
    if row is None:
        raise CStoreError("ORDER_NOT_FOUND", "订单不存在")
    if row["buyer_id"] != buyer_id:
        raise CStoreError("ORDER_FORBIDDEN", "不能取消其他用户的订单")
    if row["status"] == "CANCELLED":
        return row
    if row["status"] != "CONFIRMED":
        raise CStoreError("ORDER_NOT_CANCELLABLE", "只有已确认订单可以取消")
    if not row.get("merchant_order_id"):
        raise CStoreError("MERCHANT_ORDER_NOT_FOUND", "旧平台订单没有商家订单，无法执行商家退款")

    try:
        get_merchant_write_repository().cancel_order(
            merchant_id or _MERCHANT_ID,
            order_id,
            request_id=request_id,
        )
    except MerchantError as exc:
        raise _merchant_error(exc) from exc

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE c_order SET status = 'CANCELLED' WHERE order_id = ? AND buyer_id = ?",
            (order_id, buyer_id),
        )
        items = conn.execute(
            "SELECT product_id, quantity FROM c_order_item WHERE order_id = ?",
            (order_id,),
        ).fetchall()
        for item in items:
            conn.execute(
                "UPDATE c_product SET stock = stock + ? WHERE product_id = ?",
                (item["quantity"], item["product_id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    cancelled = get_order(order_id)
    return cancelled or row


def create_after_sale(
    buyer_id: str,
    order_id: str,
    *,
    sale_type: str,
    reason: str,
) -> dict[str, Any]:
    """创建发货后售后工单；只允许 REFUND_ONLY / RETURN_REFUND。"""
    sale_type = str(sale_type or "").strip().upper()
    reason = str(reason or "").strip()
    if sale_type not in {"REFUND_ONLY", "RETURN_REFUND"}:
        raise CStoreError("INVALID_AFTER_SALE_TYPE", "售后类型不合法")
    if not reason or len(reason) > 500:
        raise CStoreError("INVALID_AFTER_SALE_REASON", "售后原因不能为空且不能超过 500 字")
    order = get_order(order_id)
    if order is None:
        raise CStoreError("ORDER_NOT_FOUND", "订单不存在")
    if order["buyer_id"] != buyer_id:
        raise CStoreError("ORDER_FORBIDDEN", "不能为其他用户的订单申请售后")
    if order["status"] != "CONFIRMED" or order.get("merchant_status") not in {"SHIPPED", "COMPLETED"}:
        raise CStoreError("AFTER_SALE_NOT_ALLOWED", "只有已发货或已完成的订单可以申请售后")
    if order.get("after_sale") and order["after_sale"]["status"] in {
        "OPEN",
        "RETURN_PENDING",
        "RETURN_SHIPPED",
        "APPROVED",
    }:
        raise CStoreError("AFTER_SALE_EXISTS", "该订单已有处理中或已通过的售后")

    ticket_id = f"as_{uuid.uuid4().hex[:16]}"
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO c_after_sale(ticket_id, order_id, buyer_id, type, reason, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'OPEN', ?)",
            (ticket_id, order_id, buyer_id, sale_type, reason, _now()),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise CStoreError("AFTER_SALE_EXISTS", "该订单已有未处理的售后申请") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_after_sale(ticket_id, buyer_id)


def get_after_sale(ticket_id: str, buyer_id: str | None = None) -> dict[str, Any]:
    init()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM c_after_sale WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise CStoreError("AFTER_SALE_NOT_FOUND", "售后工单不存在")
        if buyer_id is not None and row["buyer_id"] != buyer_id:
            raise CStoreError("AFTER_SALE_FORBIDDEN", "不能访问其他用户的售后")
        return _after_sale_payload(row)
    finally:
        conn.close()


def list_after_sales(
    buyer_id: str | None = None,
    *,
    order_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    init()
    where = ["1 = 1"]
    params: list[Any] = []
    if buyer_id is not None:
        where.append("buyer_id = ?")
        params.append(buyer_id)
    if order_id is not None:
        where.append("order_id = ?")
        params.append(order_id)
    params.append(max(1, min(int(limit), 200)))
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_after_sale WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_after_sale_payload(row) for row in rows]
    finally:
        conn.close()


def resolve_after_sale(
    ticket_id: str,
    *,
    approved: bool,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    """管理员审批售后：通过时走商家退款并把 C 订单标记 REFUNDED。"""
    init()
    conn = _connect()
    try:
        ticket = conn.execute(
            "SELECT * FROM c_after_sale WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if ticket is None:
            raise CStoreError("AFTER_SALE_NOT_FOUND", "售后工单不存在")
        if ticket["status"] != "OPEN":
            return _after_sale_payload(ticket)
        order = conn.execute(
            "SELECT * FROM c_order WHERE order_id = ?", (ticket["order_id"],)
        ).fetchone()
        if order is None:
            raise CStoreError("ORDER_NOT_FOUND", "订单不存在")
    finally:
        conn.close()

    if not approved:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE c_after_sale SET status = 'REJECTED', resolved_at = ? "
                "WHERE ticket_id = ? AND status = 'OPEN'",
                (_now(), ticket_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return get_after_sale(ticket_id)

    if ticket["type"] == "RETURN_REFUND":
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE c_after_sale SET status = 'RETURN_PENDING' "
                "WHERE ticket_id = ? AND status = 'OPEN'",
                (ticket_id,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return get_after_sale(ticket_id)

    try:
        merchant_order = get_merchant_write_repository().refund_order(
            merchant_id or _MERCHANT_ID,
            order["order_id"],
            request_id=f"after_sale_{ticket_id}",
        )
    except MerchantError as exc:
        raise _merchant_error(exc) from exc

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE c_after_sale SET status = 'APPROVED', refund_amount = ?, resolved_at = ? "
            "WHERE ticket_id = ? AND status = 'OPEN'",
            (float(merchant_order.refund_amount or 0), _now(), ticket_id),
        )
        conn.execute(
            "UPDATE c_order SET status = 'REFUNDED' WHERE order_id = ?",
            (order["order_id"],),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_after_sale(ticket_id)


def submit_return_shipment(
    buyer_id: str,
    ticket_id: str,
    *,
    tracking_no: str,
    carrier: str | None = None,
) -> dict[str, Any]:
    """用户提交退货物流：仅 RETURN_PENDING 的退货退款工单可提交。"""
    tracking_no = str(tracking_no or "").strip()
    carrier = str(carrier or "").strip()
    if not tracking_no or len(tracking_no) > 64:
        raise CStoreError("RETURN_SHIPMENT_INVALID", "退回运单号不能为空且不能超过 64 字")
    if len(carrier) > 64:
        raise CStoreError("RETURN_SHIPMENT_INVALID", "承运商不能超过 64 字")
    ticket = get_after_sale(ticket_id, buyer_id)
    if ticket["type"] != "RETURN_REFUND":
        raise CStoreError("AFTER_SALE_NOT_RETURNABLE", "该售后不是退货退款，无需寄回")
    if ticket["status"] == "RETURN_SHIPPED":
        return ticket
    if ticket["status"] != "RETURN_PENDING":
        raise CStoreError("AFTER_SALE_NOT_RETURNABLE", "当前售后状态不能提交退回物流")

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE c_after_sale SET status = 'RETURN_SHIPPED', return_tracking_no = ?, "
            "return_carrier = ?, return_shipped_at = ? WHERE ticket_id = ? AND status = 'RETURN_PENDING'",
            (tracking_no, carrier or None, _now(), ticket_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_after_sale(ticket_id, buyer_id)


def receive_after_sale(
    ticket_id: str,
    *,
    accepted: bool,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    """商家验收入库：通过时先恢复商家库存再退款，并恢复 C 库存。"""
    init()
    conn = _connect()
    try:
        ticket = conn.execute("SELECT * FROM c_after_sale WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            raise CStoreError("AFTER_SALE_NOT_FOUND", "售后工单不存在")
        if ticket["type"] != "RETURN_REFUND":
            raise CStoreError("AFTER_SALE_NOT_RETURNABLE", "该售后不是退货退款，无需验收入库")
        if ticket["status"] == "APPROVED":
            return _after_sale_payload(ticket)
        if ticket["status"] != "RETURN_SHIPPED":
            raise CStoreError("AFTER_SALE_NOT_RETURNABLE", "退货物流尚未寄回，不能验收")
        order = conn.execute("SELECT * FROM c_order WHERE order_id = ?", (ticket["order_id"],)).fetchone()
        if order is None:
            raise CStoreError("ORDER_NOT_FOUND", "订单不存在")
    finally:
        conn.close()

    if not accepted:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE c_after_sale SET status = 'REJECTED', received_at = ?, resolved_at = ? "
                "WHERE ticket_id = ? AND status = 'RETURN_SHIPPED'",
                (_now(), _now(), ticket_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return get_after_sale(ticket_id)

    try:
        merchant_order = get_merchant_write_repository().receive_return(
            merchant_id or _MERCHANT_ID,
            order["order_id"],
            request_id=f"return_{ticket_id}",
        )
        merchant_order = get_merchant_write_repository().refund_order(
            merchant_id or _MERCHANT_ID,
            order["order_id"],
            request_id=f"after_sale_{ticket_id}",
        )
    except MerchantError as exc:
        raise _merchant_error(exc) from exc

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        received_at = _now()
        conn.execute(
            "UPDATE c_after_sale SET status = 'APPROVED', refund_amount = ?, received_at = ?, "
            "restocked_at = ?, resolved_at = ? WHERE ticket_id = ? AND status = 'RETURN_SHIPPED'",
            (
                float(merchant_order.refund_amount or 0),
                received_at,
                received_at,
                received_at,
                ticket_id,
            ),
        )
        conn.execute("UPDATE c_order SET status = 'REFUNDED' WHERE order_id = ?", (order["order_id"],))
        items = conn.execute(
            "SELECT product_id, quantity FROM c_order_item WHERE order_id = ?",
            (order["order_id"],),
        ).fetchall()
        for item in items:
            conn.execute(
                "UPDATE c_product SET stock = stock + ? WHERE product_id = ?",
                (item["quantity"], item["product_id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_after_sale(ticket_id)


def _after_sale_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "ticket_id": row["ticket_id"],
        "order_id": row["order_id"],
        "buyer_id": row["buyer_id"],
        "type": row["type"],
        "reason": row["reason"],
        "status": row["status"],
        "refund_amount": float(row["refund_amount"]) if row["refund_amount"] is not None else None,
        "return_tracking_no": row["return_tracking_no"],
        "return_carrier": row["return_carrier"],
        "return_shipped_at": row["return_shipped_at"],
        "received_at": row["received_at"],
        "restocked_at": row["restocked_at"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def _order_payload(conn: sqlite3.Connection, order: sqlite3.Row) -> dict[str, Any]:
    items = conn.execute(
        "SELECT product_id, quantity, unit_price FROM c_order_item WHERE order_id = ?",
        (order["order_id"],),
    ).fetchall()
    titles = {
        row["product_id"]: row["title"]
        for row in conn.execute(
            "SELECT product_id, title FROM c_product WHERE product_id IN "
            "(SELECT product_id FROM c_order_item WHERE order_id = ?)",
            (order["order_id"],),
        ).fetchall()
    }
    merchant_order = None
    try:
        merchant_order = get_merchant_repository().get_order(
            order["order_id"],
            merchant_id=_MERCHANT_ID,
            buyer_id=_merchant_buyer_id(order["buyer_id"]),
        )
    except MerchantError:
        merchant_order = None
    timeline: list[dict[str, Any]] = []
    status_at = None
    if merchant_order is not None:
        timeline = [
            {"status": "CREATED", "at": merchant_order.created_at},
        ]
        for status, at in (
            ("PAID", merchant_order.paid_at),
            ("SHIPPED", merchant_order.shipped_at),
            ("COMPLETED", merchant_order.completed_at),
        ):
            if at:
                timeline.append({"status": status, "at": at})
        if merchant_order.status == "CANCELLED":
            timeline.append({"status": "CANCELLED", "at": merchant_order.cancelled_at or ""})
        status_at = next(
            (item["at"] for item in reversed(timeline) if item["at"]),
            None,
        )
    after_sale_row = conn.execute(
        "SELECT * FROM c_after_sale WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
        (order["order_id"],),
    ).fetchone()
    after_sale = _after_sale_payload(after_sale_row) if after_sale_row is not None else None
    can_after_sale = bool(
        order["status"] == "CONFIRMED"
        and merchant_order is not None
        and merchant_order.status in {"SHIPPED", "COMPLETED"}
        and (after_sale is None or after_sale["status"] not in {
            "OPEN",
            "RETURN_PENDING",
            "RETURN_SHIPPED",
            "APPROVED",
        })
    )
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "buyer_id": order["buyer_id"],
        "total_amount": float(order["total_amount"]),
        "original_amount": float(order["original_amount"] or order["total_amount"]),
        "discount_amount": float(order["discount_amount"] or 0),
        "quote_id": order["quote_id"],
        "policy_ids": json.loads(order["policy_ids_json"] or "[]"),
        "items": [
            {
                "product_id": item["product_id"],
                "title": titles.get(item["product_id"], ""),
                "quantity": item["quantity"],
                "unit_price": float(item["unit_price"]),
            }
            for item in items
        ],
        "idempotency_key": order["idempotency_key"],
        "source_order_id": order["source_order_id"],
        "created_at": order["created_at"],
        "confirmed_at": order["confirmed_at"],
        "merchant_order_id": merchant_order.order_id if merchant_order else None,
        "merchant_status": merchant_order.status if merchant_order else None,
        "merchant_source": "merchant_v1" if merchant_order else None,
        "merchant_tracking_no": merchant_order.tracking_no if merchant_order else None,
        "merchant_carrier": merchant_order.carrier if merchant_order else None,
        "merchant_status_at": status_at,
        "merchant_timeline": timeline,
        "merchant_cancelled_at": merchant_order.cancelled_at if merchant_order else None,
        "merchant_refund_amount": (
            float(merchant_order.refund_amount)
            if merchant_order is not None and merchant_order.refund_amount is not None
            else None
        ),
        "merchant_refunded_at": merchant_order.refunded_at if merchant_order else None,
        "can_cancel": bool(
            merchant_order is not None
            and order["status"] == "CONFIRMED"
            and merchant_order.status in {"CREATED", "PAID"}
        ),
        "can_after_sale": can_after_sale,
        "after_sale": after_sale,
    }


def list_orders(buyer_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """买家已确认/已取消订单，用于订单页展示与审计查询。"""
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_order WHERE buyer_id = ? AND status IN ('CONFIRMED', 'CANCELLED', 'REFUNDED') "
            "AND order_id LIKE 'order_%' ORDER BY confirmed_at DESC LIMIT ?",
            (buyer_id, max(1, min(int(limit), 200))),
        ).fetchall()
        return [_order_payload(conn, row) for row in rows]
    finally:
        conn.close()


def reconcile_orders(limit: int = 200) -> dict[str, Any]:
    """核对 C 订单与商家订单：缺失、状态、原始金额。旧平台订单单独计数。"""
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_order WHERE order_id LIKE 'order_%' "
            "ORDER BY confirmed_at DESC, order_id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        checked = 0
        legacy = 0
        issues: list[dict[str, Any]] = []
        repo = get_merchant_repository()
        for row in rows:
            payload = _order_payload(conn, row)
            merchant_order_id = payload.get("merchant_order_id")
            if not merchant_order_id:
                legacy += 1
                continue
            checked += 1
            merchant_order = repo.get_order(
                merchant_order_id,
                merchant_id=_MERCHANT_ID,
                buyer_id=_merchant_buyer_id(row["buyer_id"]),
            )
            if merchant_order is None:
                issues.append({
                    "order_id": row["order_id"],
                    "issue": "MERCHANT_ORDER_MISSING",
                })
                continue
            c_status = str(row["status"]).upper()
            m_status = str(merchant_order.status).upper()
            if c_status == "CONFIRMED" and m_status == "CANCELLED":
                issues.append({
                    "order_id": row["order_id"],
                    "issue": "STATUS_DIVERGENCE",
                    "c_status": c_status,
                    "merchant_status": m_status,
                })
            elif c_status == "CANCELLED" and m_status != "CANCELLED":
                issues.append({
                    "order_id": row["order_id"],
                    "issue": "STATUS_DIVERGENCE",
                    "c_status": c_status,
                    "merchant_status": m_status,
                })
            elif c_status == "REFUNDED" and m_status != "REFUNDED":
                issues.append({
                    "order_id": row["order_id"],
                    "issue": "STATUS_DIVERGENCE",
                    "c_status": c_status,
                    "merchant_status": m_status,
                })
            if abs(float(row["original_amount"]) - float(merchant_order.total_amount)) > 0.01:
                issues.append({
                    "order_id": row["order_id"],
                    "issue": "AMOUNT_DIVERGENCE",
                    "c_amount": float(row["original_amount"]),
                    "merchant_amount": float(merchant_order.total_amount),
                })
        return {
            "checked": checked,
            "legacy": legacy,
            "issues": issues,
            "ok": not issues,
        }
    finally:
        conn.close()


def _alert_content(issue: dict[str, Any]) -> tuple[str, str, str]:
    """返回 (severity, message, suggestion)。只给建议，不自动改订单。"""
    order_id = str(issue.get("order_id") or "")
    kind = str(issue.get("issue") or "UNKNOWN")
    if kind == "MERCHANT_ORDER_MISSING":
        return (
            "CRITICAL",
            f"商家订单缺失：{order_id}",
            "到商家后台/OMS 核对订单是否存在，必要时人工补单或取消 C 订单；不要直接改库。",
        )
    if kind == "STATUS_DIVERGENCE":
        c_status = issue.get("c_status") or "?"
        m_status = issue.get("merchant_status") or "?"
        return (
            "WARNING",
            f"状态不一致：C={c_status} / 商家={m_status}（{order_id}）",
            "人工确认以哪一侧为准；取消/退款必须走受控接口，避免二次退款。",
        )
    if kind == "AMOUNT_DIVERGENCE":
        c_amount = issue.get("c_amount")
        m_amount = issue.get("merchant_amount")
        return (
            "WARNING",
            f"金额不一致：C={c_amount} / 商家={m_amount}（{order_id}）",
            "人工核对原始金额与成交金额，禁止直接改库；确认后再走补差/退款流程。",
        )
    return ("WARNING", f"对账问题：{kind}（{order_id}）", "人工核查该订单。")


def _alert_id(order_id: str, issue: str) -> str:
    key = f"{order_id}|{issue}".encode("utf-8")
    return f"al_{hashlib.sha1(key).hexdigest()[:20]}"


def _sync_reconciliation_alerts(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    issues: list[dict[str, Any]],
    now: str,
) -> int:
    """按 (order_id, issue) 去重；未再出现的问题自动标记 resolved。"""
    keys: list[str] = []
    for issue in issues:
        order_id = str(issue.get("order_id") or "")
        kind = str(issue.get("issue") or "UNKNOWN")
        alert_id = _alert_id(order_id, kind)
        keys.append(alert_id)
        severity, message, suggestion = _alert_content(issue)
        conn.execute(
            "INSERT INTO c_reconciliation_alert(alert_id, run_id, order_id, issue, severity, "
            "message, suggestion, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(alert_id) DO UPDATE SET run_id = excluded.run_id, "
            "message = excluded.message, suggestion = excluded.suggestion, "
            "last_seen_at = excluded.last_seen_at, read_at = NULL, resolved_at = NULL",
            (alert_id, run_id, order_id, kind, severity, message, suggestion, now, now),
        )
    if keys:
        placeholders = ",".join("?" for _ in keys)
        conn.execute(
            f"UPDATE c_reconciliation_alert SET resolved_at = ? "
            f"WHERE resolved_at IS NULL AND alert_id NOT IN ({placeholders})",
            (now, *keys),
        )
    else:
        conn.execute(
            "UPDATE c_reconciliation_alert SET resolved_at = ? WHERE resolved_at IS NULL",
            (now,),
        )
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM c_reconciliation_alert WHERE resolved_at IS NULL"
        ).fetchone()["n"]
    )


def run_reconciliation(trigger: str = "MANUAL", limit: int = 200) -> dict[str, Any]:
    """执行一次对账并留痕；不自动修改任何订单。"""
    trigger = str(trigger or "MANUAL").strip().upper()[:32] or "MANUAL"
    started_at = _now()
    report = reconcile_orders(limit=limit)
    finished_at = _now()
    run_id = f"rec_{uuid.uuid4().hex[:16]}"
    issues = report.get("issues") or []
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO c_reconciliation_run(run_id, trigger, started_at, finished_at, ok, "
            "checked, legacy, issue_count, issues_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                trigger,
                started_at,
                finished_at,
                1 if report.get("ok") else 0,
                int(report.get("checked") or 0),
                int(report.get("legacy") or 0),
                len(issues),
                json.dumps(issues, ensure_ascii=False),
            ),
        )
        open_alert_count = _sync_reconciliation_alerts(
            conn, run_id=run_id, issues=issues, now=finished_at
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    webhook_result: dict[str, Any] = {"sent": False, "reason": "NO_ALERTS"}
    if issues:
        try:
            from rag_demo.c_end import alerts as alert_notifier

            alert_rows = list_reconciliation_alerts(run_id=run_id, limit=200)
            webhook_result = alert_notifier.deliver_reconciliation_alerts(
                run_id=run_id,
                trigger=trigger,
                checked=int(report.get("checked") or 0),
                legacy=int(report.get("legacy") or 0),
                issues=issues,
                alerts=alert_rows,
            )
        except Exception:  # noqa: BLE001 - 外部通道失败不影响对账结果
            webhook_result = {"sent": False, "reason": "DELIVERY_ERROR"}
    return {
        "run_id": run_id,
        "trigger": trigger,
        "started_at": started_at,
        "finished_at": finished_at,
        "ok": bool(report.get("ok")),
        "checked": int(report.get("checked") or 0),
        "legacy": int(report.get("legacy") or 0),
        "issue_count": len(issues),
        "alert_count": open_alert_count,
        "issues": issues,
        "webhook": webhook_result,
    }


def list_reconciliation_runs(limit: int = 20) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_reconciliation_run ORDER BY started_at DESC, run_id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "trigger": row["trigger"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "ok": bool(row["ok"]),
                "checked": int(row["checked"]),
                "legacy": int(row["legacy"]),
                "issue_count": int(row["issue_count"]),
                "issues": json.loads(row["issues_json"] or "[]"),
            }
            for row in rows
        ]
    finally:
        conn.close()


def list_reconciliation_alerts(
    *,
    unread_only: bool = False,
    limit: int = 50,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    init()
    where = "resolved_at IS NULL"
    params: list[Any] = []
    if unread_only:
        where += " AND read_at IS NULL"
    if run_id:
        where += " AND run_id = ?"
        params.append(str(run_id))
    params.append(max(1, min(int(limit), 200)))
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_reconciliation_alert WHERE {where} "
            "ORDER BY last_seen_at DESC, alert_id DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "alert_id": row["alert_id"],
                "run_id": row["run_id"],
                "order_id": row["order_id"],
                "issue": row["issue"],
                "severity": row["severity"],
                "message": row["message"],
                "suggestion": row["suggestion"],
                "created_at": row["created_at"],
                "last_seen_at": row["last_seen_at"],
                "read_at": row["read_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def unread_reconciliation_alert_count() -> int:
    init()
    conn = _connect()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM c_reconciliation_alert "
                "WHERE resolved_at IS NULL AND read_at IS NULL"
            ).fetchone()["n"]
        )
    finally:
        conn.close()


def mark_reconciliation_alerts_read() -> int:
    init()
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE c_reconciliation_alert SET read_at = ? "
            "WHERE resolved_at IS NULL AND read_at IS NULL",
            (_now(),),
        )
        conn.commit()
        return int(cursor.rowcount)
    finally:
        conn.close()


def cancel_order_draft(buyer_id: str, draft_id: str) -> dict[str, Any]:
    """取消草稿；如果草稿绑定了报价，则把报价释放回 PENDING。"""
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM c_order WHERE order_id = ?", (draft_id,)).fetchone()
        if row is None:
            raise CStoreError("ORDER_NOT_FOUND", "订单不存在")
        if row["buyer_id"] != buyer_id:
            raise CStoreError("ORDER_FORBIDDEN", "不能操作其他用户的订单")
        if row["status"] != "DRAFT":
            raise CStoreError("ORDER_NOT_DRAFT", "只有草稿可以取消")
        conn.execute("UPDATE c_order SET status = 'CANCELLED' WHERE order_id = ?", (draft_id,))
        if row["quote_id"]:
            conn.execute(
                "UPDATE c_quote SET status = 'PENDING' WHERE quote_id = ? AND status = 'PENDING'",
                (row["quote_id"],),
            )
        conn.commit()
        _release_merchant_reservation(draft_id)
        return {"order_id": draft_id, "status": "CANCELLED", "quote_id": row["quote_id"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_quote(quote_id: str, buyer_id: str) -> dict[str, Any]:
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM c_quote WHERE quote_id = ?", (quote_id,)).fetchone()
        if row is None:
            raise CStoreError("QUOTE_NOT_FOUND", "报价不存在")
        if row["buyer_id"] != buyer_id:
            raise CStoreError("QUOTE_FORBIDDEN", "不能操作其他用户的报价")
        if row["status"] != "PENDING":
            raise CStoreError("QUOTE_NOT_PENDING", "报价已使用或已失效")
        conn.execute("UPDATE c_quote SET status = 'CANCELLED' WHERE quote_id = ?", (quote_id,))
        conn.commit()
        return {"quote_id": quote_id, "status": "CANCELLED"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _audit_time(value: str | None, *, end: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 10:
        return f"{text}T{'23:59:59' if end else '00:00:00'}"
    return text


def _audit_order_where(
    *,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[str], list[Any]]:
    """管理端订单审计的 WHERE 片段与参数（列表 / count / CSV 共用同一口径）。"""
    where = ["status = 'CONFIRMED'", "order_id LIKE 'order_%'"]
    params: list[Any] = []
    if buyer_id:
        where.append("buyer_id = ?")
        params.append(str(buyer_id).strip())
    if status:
        where.append(
            "quote_id IS NOT NULL AND quote_id IN "
            "(SELECT quote_id FROM c_quote WHERE status = ?)"
        )
        params.append(str(status).strip().upper())
    start = _audit_time(date_from)
    end = _audit_time(date_to, end=True)
    if start:
        where.append("confirmed_at >= ?")
        params.append(start)
    if end:
        where.append("confirmed_at <= ?")
        params.append(end)
    return where, params


def _audit_quote_where(
    *,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[str], list[Any]]:
    """管理端报价审计的 WHERE 片段与参数（列表 / count 共用同一口径）。"""
    where = ["1 = 1"]
    params: list[Any] = []
    if buyer_id:
        where.append("buyer_id = ?")
        params.append(str(buyer_id).strip())
    if status:
        where.append("status = ?")
        params.append(str(status).strip().upper())
    start = _audit_time(date_from)
    end = _audit_time(date_to, end=True)
    if start:
        where.append("created_at >= ?")
        params.append(start)
    if end:
        where.append("created_at <= ?")
        params.append(end)
    return where, params


def _audit_page(limit: int, offset: int) -> tuple[int, int]:
    """limit 钳制在 1..200（与既有口径一致），offset 不能为负。"""
    return max(1, min(int(limit), 200)), max(0, int(offset))


def list_all_orders(
    limit: int = 50,
    *,
    offset: int = 0,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """管理端审计：所有买家的已确认订单，支持买家/报价状态/时间过滤与分页。

    `status` 是**订单关联报价**的状态（不是订单自身状态）：通过
    `c_order.quote_id → c_quote.status` 关联过滤。status 非空时，
    没有 quote_id 的直购订单不返回——它们没有可匹配的报价状态。
    `offset` 按同一排序键翻页；`confirmed_at` 相同用 order_id 兜底，保证不重不漏。
    """
    init()
    where, params = _audit_order_where(
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    limit_value, offset_value = _audit_page(limit, offset)
    params.extend([limit_value, offset_value])
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_order WHERE {' AND '.join(where)} "
            "ORDER BY confirmed_at DESC, order_id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [_order_payload(conn, row) for row in rows]
    finally:
        conn.close()


def count_all_orders(
    *,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """管理端审计：与 `list_all_orders` 同筛选口径的订单总数（用于分页）。"""
    init()
    where, params = _audit_order_where(
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM c_order WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def _quote_audit_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        products = json.loads(row["product_refs_json"] or "[]")
        policies = json.loads(row["policy_refs_json"] or "[]")
    except (TypeError, ValueError):
        products, policies = [], []
    return {
        "quote_id": row["quote_id"],
        "buyer_id": row["buyer_id"],
        "friend_id": row["friend_id"],
        "status": row["status"],
        "product_refs": products,
        "policy_refs": policies,
        "created_at": row["created_at"],
    }


def list_all_quotes(
    limit: int = 50,
    *,
    offset: int = 0,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """管理端审计：所有买家报价及其状态，支持买家/状态/时间过滤与分页。

    `offset` 按同一排序键翻页；`created_at` 相同用 quote_id 兜底，保证不重不漏。
    """
    init()
    where, params = _audit_quote_where(
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    limit_value, offset_value = _audit_page(limit, offset)
    params.extend([limit_value, offset_value])
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_quote WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC, quote_id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [_quote_audit_payload(row) for row in rows]
    finally:
        conn.close()


def count_all_quotes(
    *,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """管理端审计：与 `list_all_quotes` 同筛选口径的报价总数（用于分页）。"""
    init()
    where, params = _audit_quote_where(
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM c_quote WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


AUDIT_ORDER_CSV_FIELDS = (
    "order_id",
    "buyer_id",
    "total_amount",
    "original_amount",
    "discount_amount",
    "quote_id",
    "policy_ids",
    "confirmed_at",
)

_CSV_BOM = "\ufeff"


def _csv_money(value: Any) -> str:
    """金额统一两位小数；空值按 0 处理，避免 Excel 里出现 269.0 这种列格式不一致。"""
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def export_audit_orders_csv(
    limit: int = 50,
    *,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """管理端 C 端审计订单 CSV（文本，首字符是 UTF-8 BOM）。

    与 `/api/c/admin/audit` 保持同一筛选口径：
    - `buyer_id / date_from / date_to / limit` 复用 `list_all_orders`；
    - `status` 按订单关联的报价状态过滤（同列表行为），无 quote_id 的订单在
      status 非空时不导出，保证“导出的”和“看到的”订单一致（同样的排序、截断和状态关联）；
    - CSV 导出**不带 offset**，始终导出当前筛选下最近 `limit` 条（列表分页只是展示层）。

    Returns:
        str: 带 BOM 的 CSV 文本（RFC 4180 换行），调用方按 UTF-8 编码后作为附件下发。
    """
    orders = list_all_orders(
        limit=limit,
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    buffer = io.StringIO()
    buffer.write(_CSV_BOM)
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(AUDIT_ORDER_CSV_FIELDS)
    for order in orders:
        writer.writerow(
            [
                order.get("order_id") or "",
                order.get("buyer_id") or "",
                _csv_money(order.get("total_amount")),
                _csv_money(order.get("original_amount")),
                _csv_money(order.get("discount_amount")),
                order.get("quote_id") or "",
                ";".join(str(policy) for policy in order.get("policy_ids") or []),
                order.get("confirmed_at") or "",
            ]
        )
    return buffer.getvalue()


def _companion_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "owner_id": row["owner_id"],
        "name": row["name"],
        "user_nickname": row["user_nickname"],
        "species": row["species"],
        "persona": row["persona"],
        "appearance": row["appearance"],
        "level": int(row["level"]),
        "exp": int(row["exp"]),
        "satiety": int(row["satiety"]),
        "avatar_url": _avatar_url(row["avatar_path"], "companion"),
        "user_avatar_url": _avatar_url(row["user_avatar_path"], "user"),
        "diary_enabled": bool(row["diary_enabled"]) if "diary_enabled" in row.keys() else False,
        "updated_at": row["updated_at"],
    }


def _ensure_companion(conn: sqlite3.Connection, owner_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM c_companion WHERE owner_id = ?", (owner_id,)).fetchone()
    if row is not None:
        return row
    conn.execute(
        "INSERT INTO c_companion(owner_id, name, user_nickname, species, persona, appearance, updated_at) "
        "VALUES (?, ?, '', 'digital_companion', 'warm', '', ?)",
        (owner_id, c_persona.DEFAULT_NAME, _now()),
    )
    return conn.execute("SELECT * FROM c_companion WHERE owner_id = ?", (owner_id,)).fetchone()


def get_companion(owner_id: str) -> dict[str, Any]:
    """获取/初始化伙伴；species 是抽象字段，不硬编码为鱼。"""
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_companion(conn, owner_id)
        conn.commit()
        return _companion_payload(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_companion(
    owner_id: str,
    *,
    name: str | None = None,
    user_nickname: str | None = None,
    species: str | None = None,
    persona: str | None = None,
    appearance: str | None = None,
) -> dict[str, Any]:
    """更新伙伴表现层字段；不改变 Agent 权限。

    name / user_nickname 走 persona.validate_name 的同一套规则：
    1–12 字，只允许中文/英文/数字/下划线，禁止"主人/客服/官方"等身份误导词。
    """
    fields: list[tuple[str, str]] = []
    if name is not None:
        ok, reason = c_persona.validate_name(name)
        if not ok:
            raise CStoreError("INVALID_COMPANION_NAME", reason)
        fields.append(("name", str(name).strip()))
    if user_nickname is not None:
        nickname = str(user_nickname).strip()
        if nickname:
            ok, reason = c_persona.validate_name(nickname)
            if not ok:
                raise CStoreError("INVALID_USER_NICKNAME", reason)
        # 空字符串表示"就叫你"，是合法状态，不是错误。
        fields.append(("user_nickname", nickname))
    for key, value in (("species", species), ("persona", persona), ("appearance", appearance)):
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            raise CStoreError("INVALID_COMPANION", f"{key} 不能为空")
        if len(text) > 60:
            raise CStoreError("INVALID_COMPANION", f"{key} 太长")
        fields.append((key, text))
    if not fields:
        return get_companion(owner_id)

    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_companion(conn, owner_id)
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        conn.execute(
            f"UPDATE c_companion SET {assignments}, updated_at = ? WHERE owner_id = ?",
            [value for _, value in fields] + [_now(), owner_id],
        )
        conn.commit()
        row = conn.execute("SELECT * FROM c_companion WHERE owner_id = ?", (owner_id,)).fetchone()
        return _companion_payload(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


MEMORY_KINDS = ("preference", "boundary", "fact", "event")
MEMORY_ACTIVE_LIMIT = 20
MEMORY_DIGEST_LIMIT = 10
MEMORY_DECAY_DAYS = 90
_MEMORY_PII_RE = re.compile(
    r"\b1[3-9]\d{9}\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\b\d{17}[\dXx]\b|\b\d{16,19}\b"
)
_MEMORY_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"我(?:更|最)?喜欢([^，。！？\n]{1,40})"), "preference", "喜欢"),
    (re.compile(r"我不喜欢([^，。！？\n]{1,40})"), "preference", "不喜欢"),
    (re.compile(r"我(?:穿|用)([0-9A-Za-z\u4e00-\u9fff]{1,12}码)"), "preference", "尺码"),
    (re.compile(r"我(?:的)?预算(?:是|为)?\s*([0-9]{2,7})\s*元"), "preference", "预算"),
    (re.compile(r"(?:不要|别)(?:再)?(?:给我)?推荐([^，。！？\n]{1,30})"), "boundary", "不推荐"),
    (re.compile(r"我对([^，。！？\n]{1,20})过敏"), "boundary", "对"),
)


def _clean_memory_content(value: str) -> str:
    return value.strip().strip("，,。.!！?？；;：: \t")[:80]


def extract_memories(message: str) -> list[dict[str, str]]:
    """从用户明确自述中抽取少量长期记忆；规则优先，不调用 LLM。"""
    text = str(message or "").strip()
    if not text or len(text) > 300 or _MEMORY_PII_RE.search(text):
        return []
    # 疑问句/回忆问句不是用户在陈述偏好，不能写进长期记忆。
    if any(mark in text for mark in ("吗", "？", "?", "什么", "哪些", "哪款")):
        return []
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pattern, kind, prefix in _MEMORY_PATTERNS:
        for match in pattern.finditer(text):
            raw = _clean_memory_content(match.group(1))
            if not raw:
                continue
            if prefix == "喜欢":
                content = f"喜欢{raw}"
            elif prefix == "不喜欢":
                content = f"不喜欢{raw}"
            elif prefix == "尺码":
                content = f"尺码 {raw}"
            elif prefix == "预算":
                content = f"预算 {raw} 元"
            elif prefix == "不推荐":
                content = f"不要推荐{raw}"
            elif prefix == "对":
                content = f"对{raw}过敏"
            else:
                content = f"{prefix}{raw}"
            key = (kind, content)
            if key in seen:
                continue
            seen.add(key)
            found.append({"kind": kind, "content": content})
    return found


def _memory_importance(kind: str, content: str) -> int:
    """确定性重要性；安全/过敏边界 5 分，预算/尺码 4 分，其余 3 分。"""
    text = str(content or "")
    if kind == "boundary":
        if any(word in text for word in ("过敏", "安全", "忌口", "不能用", "疾病", "医生")):
            return 5
        return 4
    if any(word in text for word in ("预算", "尺码", "码")):
        return 4
    if "不喜欢" in text:
        return 3
    return 3


def save_memories(owner_id: str, message: str, *, source: str = "extracted") -> list[dict[str, Any]]:
    """保存明确记忆；重复内容只强化，不重复插入。"""
    items = extract_memories(message)
    if not items:
        return []
    init()
    now = _now()
    added: list[dict[str, Any]] = []
    conn = _connect()
    try:
        for item in items:
            importance = _memory_importance(item["kind"], item["content"])
            exists = conn.execute(
                "SELECT memory_id, importance, reinforced_count FROM c_companion_memory "
                "WHERE owner_id = ? AND kind = ? AND content = ?",
                (owner_id, item["kind"], item["content"]),
            ).fetchone()
            if exists is not None:
                conn.execute(
                    "UPDATE c_companion_memory SET reinforced_count = reinforced_count + 1, "
                    "importance = ?, last_reinforced_at = ?, status = 'ACTIVE', updated_at = ? "
                    "WHERE memory_id = ?",
                    (max(int(exists["importance"] or 3), importance), now, now, exists["memory_id"]),
                )
                continue
            memory_id = f"mem_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO c_companion_memory(memory_id, owner_id, kind, content, source, "
                "importance, reinforced_count, last_reinforced_at, status, pinned, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'ACTIVE', 0, ?, ?)",
                (memory_id, owner_id, item["kind"], item["content"], source, importance, now, now, now),
            )
            added.append({
                "memory_id": memory_id, **item, "source": source,
                "importance": importance, "created_at": now,
            })
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return added


def list_memories(owner_id: str, limit: int = 20) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT memory_id, kind, content, source, importance, reinforced_count, pinned, "
            "last_reinforced_at, created_at FROM c_companion_memory "
            "WHERE owner_id = ? AND status = 'ACTIVE' ORDER BY pinned DESC, importance DESC, "
            "created_at DESC LIMIT ?",
            (owner_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_memory(owner_id: str, memory_id: str) -> bool:
    init()
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM c_companion_memory WHERE owner_id = ? AND memory_id = ?",
            (owner_id, str(memory_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_memories(owner_id: str) -> int:
    init()
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM c_companion_memory WHERE owner_id = ?", (owner_id,))
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def list_memory_digests(owner_id: str, limit: int = 10) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT digest_id, owner_id, period, kind, content, source_memory_ids, importance, "
            "created_at, updated_at FROM c_companion_memory_digest WHERE owner_id = ? "
            "ORDER BY period DESC, importance DESC LIMIT ?",
            (owner_id, max(1, min(int(limit), 50))),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["source_memory_ids"] = json.loads(item.get("source_memory_ids") or "[]")
            except (TypeError, ValueError):
                item["source_memory_ids"] = []
            result.append(item)
        return result
    finally:
        conn.close()


def upsert_memory_digest(
    owner_id: str,
    *,
    period: str,
    kind: str,
    content: str,
    source_memory_ids: list[str],
    importance: int = 3,
) -> dict[str, Any]:
    init()
    now = _now()
    digest_id = "dig_" + hashlib.sha256(f"{owner_id}|{period}|{kind}".encode("utf-8")).hexdigest()[:20]
    source_json = json.dumps(sorted(set(str(x) for x in source_memory_ids)), ensure_ascii=False)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_companion_memory_digest(digest_id, owner_id, period, kind, content, "
            "source_memory_ids, importance, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(digest_id) DO UPDATE SET content = excluded.content, "
            "source_memory_ids = excluded.source_memory_ids, importance = excluded.importance, "
            "updated_at = excluded.updated_at",
            (digest_id, owner_id, period, kind, content[:600], source_json, int(importance), now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM c_companion_memory_digest WHERE digest_id = ?", (digest_id,)
        ).fetchone()
        return dict(row) if row is not None else {}
    finally:
        conn.close()


def archive_memories(owner_id: str, memory_ids: list[str], *, digest_id: str) -> int:
    ids = [str(item) for item in memory_ids if str(item).strip()]
    if not ids:
        return 0
    init()
    placeholders = ",".join("?" for _ in ids)
    conn = _connect()
    try:
        cursor = conn.execute(
            f"UPDATE c_companion_memory SET status = 'ARCHIVED', compressed_into = ?, updated_at = ? "
            f"WHERE owner_id = ? AND status = 'ACTIVE' AND pinned = 0 AND importance < 5 "
            f"AND memory_id IN ({placeholders})",
            (digest_id, _now(), owner_id, *ids),
        )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def decay_memories(owner_id: str, *, now: datetime | None = None, days: int = MEMORY_DECAY_DAYS) -> int:
    """长期未强化的记忆降 1 分；5 分和置顶永不自动降级。"""
    init()
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(days=days)).isoformat()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT memory_id, importance, last_reinforced_at, created_at, last_decayed_at "
            "FROM c_companion_memory WHERE owner_id = ? AND status = 'ACTIVE' "
            "AND pinned = 0 AND importance < 5",
            (owner_id,),
        ).fetchall()
        changed = 0
        for row in rows:
            last_seen = row["last_reinforced_at"] or row["created_at"] or ""
            if last_seen >= cutoff:
                continue
            if row["last_decayed_at"] and row["last_decayed_at"] >= (current - timedelta(days=1)).isoformat():
                continue
            new_importance = max(1, int(row["importance"] or 3) - 1)
            conn.execute(
                "UPDATE c_companion_memory SET importance = ?, last_decayed_at = ?, updated_at = ? "
                "WHERE memory_id = ?",
                (new_importance, current.isoformat(), current.isoformat(), row["memory_id"]),
            )
            changed += 1
        conn.commit()
        return changed
    finally:
        conn.close()


def merge_memory_digests(owner_id: str, limit: int = MEMORY_DIGEST_LIMIT) -> int:
    """压缩摘要超过上限时，把最旧的几条并进一条摘要；保留来源 id。"""
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_companion_memory_digest WHERE owner_id = ? "
            "ORDER BY period ASC, importance ASC, created_at ASC",
            (owner_id,),
        ).fetchall()
        if len(rows) <= limit:
            return 0
        extras = rows[: len(rows) - limit]
        keep = rows[len(rows) - limit]
        contents = [str(keep["content"])]
        source_ids: list[str] = []
        for row in [keep, *extras]:
            try:
                source_ids.extend(json.loads(row["source_memory_ids"] or "[]"))
            except (TypeError, ValueError):
                pass
            if row is not keep:
                content = str(row["content"] or "").strip()
                if content:
                    contents.append(content)
        now = _now()
        conn.execute(
            "UPDATE c_companion_memory_digest SET content = ?, source_memory_ids = ?, updated_at = ? "
            "WHERE digest_id = ?",
            ("；".join(contents)[:600], json.dumps(sorted(set(source_ids)), ensure_ascii=False), now, keep["digest_id"]),
        )
        conn.executemany(
            "DELETE FROM c_companion_memory_digest WHERE digest_id = ?",
            [(row["digest_id"],) for row in extras],
        )
        conn.commit()
        return len(extras)
    finally:
        conn.close()


def get_diary_enabled(owner_id: str) -> bool:
    return bool(get_companion(owner_id).get("diary_enabled"))


def set_diary_enabled(owner_id: str, enabled: bool) -> dict[str, Any]:
    get_companion(owner_id)
    conn = _connect()
    try:
        conn.execute(
            "UPDATE c_companion SET diary_enabled = ?, updated_at = ? WHERE owner_id = ?",
            (1 if enabled else 0, _now(), owner_id),
        )
        conn.commit()
        return get_companion(owner_id)
    finally:
        conn.close()


def get_diary(owner_id: str, diary_date: str) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM c_companion_diary WHERE owner_id = ? AND diary_date = ?",
            (owner_id, diary_date),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def save_diary(
    owner_id: str,
    *,
    diary_date: str,
    content: str,
    source_message_count: int = 0,
) -> dict[str, Any]:
    init()
    now = _now()
    diary_id = f"diary_{uuid.uuid4().hex[:20]}"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_companion_diary(diary_id, owner_id, diary_date, content, "
            "source_message_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(owner_id, diary_date) DO UPDATE SET content = excluded.content, "
            "source_message_count = excluded.source_message_count, updated_at = excluded.updated_at",
            (diary_id, owner_id, diary_date, content[:1000], int(source_message_count), now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM c_companion_diary WHERE owner_id = ? AND diary_date = ?",
            (owner_id, diary_date),
        ).fetchone()
        return dict(row) if row is not None else {}
    finally:
        conn.close()


def list_diaries(owner_id: str, limit: int = 30) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT diary_id, diary_date, content, source_message_count, created_at, updated_at "
            "FROM c_companion_diary WHERE owner_id = ? ORDER BY diary_date DESC LIMIT ?",
            (owner_id, max(1, min(int(limit), 100))),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_app_messages_between(
    owner_id: str,
    start_iso: str,
    end_iso: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_app_message WHERE owner_id = ? AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at ASC LIMIT ?",
            (owner_id, start_iso, end_iso, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_message_owner_ids_between(start_iso: str, end_iso: str) -> list[str]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT owner_id FROM c_app_message WHERE created_at >= ? AND created_at < ? "
            "ORDER BY owner_id ASC",
            (start_iso, end_iso),
        ).fetchall()
        return [str(row["owner_id"]) for row in rows]
    finally:
        conn.close()


_RHYTHM_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
RHYTHM_TIMEZONE_DEFAULT = "Asia/Shanghai"
CHECKIN_ORDER_FOLLOWUP = "order_followup"
CHECKIN_COMEBACK = "comeback"


def _rhythm_payload(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data.get("enabled"))
    data["unanswered_count"] = int(data.get("unanswered_count") or 0)
    return data


def _ensure_rhythm_conn(conn: sqlite3.Connection, owner_id: str) -> Any:
    row = conn.execute(
        "SELECT * FROM c_companion_rhythm WHERE owner_id = ?", (owner_id,)
    ).fetchone()
    if row is not None:
        return row
    now = _now()
    try:
        conn.execute(
            "INSERT INTO c_companion_rhythm(owner_id, enabled, timezone, quiet_start, quiet_end, "
            "created_at, updated_at) VALUES (?, 0, ?, '22:00', '09:00', ?, ?)",
            (owner_id, RHYTHM_TIMEZONE_DEFAULT, now, now),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 - 并发初始化时由唯一键兜底
        conn.rollback()
    return conn.execute(
        "SELECT * FROM c_companion_rhythm WHERE owner_id = ?", (owner_id,)
    ).fetchone()


def get_rhythm(owner_id: str) -> dict[str, Any]:
    init()
    conn = _connect()
    try:
        row = _ensure_rhythm_conn(conn, owner_id)
        return _rhythm_payload(row)
    finally:
        conn.close()


def update_rhythm(
    owner_id: str,
    *,
    enabled: bool | None = None,
    quiet_start: str | None = None,
    quiet_end: str | None = None,
    pause_hours: int | None = None,
) -> dict[str, Any]:
    for value in (quiet_start, quiet_end):
        if value is not None and not _RHYTHM_TIME_RE.fullmatch(value):
            raise CStoreError("INVALID_QUIET_HOURS", "免打扰时间必须是 HH:MM")
    fields: list[tuple[str, Any]] = []
    if enabled is not None:
        fields.append(("enabled", 1 if enabled else 0))
        if enabled:
            fields.append(("pause_until", None))
    if quiet_start is not None:
        fields.append(("quiet_start", quiet_start))
    if quiet_end is not None:
        fields.append(("quiet_end", quiet_end))
    if pause_hours is not None:
        hours = max(0, min(int(pause_hours), 24 * 30))
        pause_until = (
            (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
            if hours
            else None
        )
        fields.append(("pause_until", pause_until))
    init()
    conn = _connect()
    try:
        _ensure_rhythm_conn(conn, owner_id)
        if fields:
            fields.append(("updated_at", _now()))
            assignments = ", ".join(f"{key} = ?" for key, _ in fields)
            conn.execute(
                f"UPDATE c_companion_rhythm SET {assignments} WHERE owner_id = ?",
                [value for _, value in fields] + [owner_id],
            )
            conn.commit()
        row = conn.execute(
            "SELECT * FROM c_companion_rhythm WHERE owner_id = ?", (owner_id,)
        ).fetchone()
        return _rhythm_payload(row)
    finally:
        conn.close()


def _schedule_order_followup_conn(
    conn: sqlite3.Connection,
    owner_id: str,
    order_id: str,
    *,
    due_hours: int = 48,
) -> None:
    exists = conn.execute(
        "SELECT checkin_id FROM c_companion_checkin WHERE owner_id = ? AND kind = ? AND ref_id = ?",
        (owner_id, CHECKIN_ORDER_FOLLOWUP, order_id),
    ).fetchone()
    if exists is not None:
        return
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO c_companion_checkin(checkin_id, owner_id, kind, ref_id, content, due_at, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)",
        (
            f"chk_{uuid.uuid4().hex[:20]}", owner_id, CHECKIN_ORDER_FOLLOWUP, order_id,
            "上次那单到手了吗？用着如果有不合适的地方，直接跟我说。",
            (now + timedelta(hours=max(1, due_hours))).isoformat(),
            now.isoformat(), now.isoformat(),
        ),
    )


def schedule_order_followup(
    owner_id: str,
    order_id: str,
    *,
    due_hours: int = 48,
) -> dict[str, Any] | None:
    """订单确认后安排一次购后回访；是否真正投递由 rhythm 开关决定。"""
    init()
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT * FROM c_companion_checkin WHERE owner_id = ? AND kind = ? AND ref_id = ?",
            (owner_id, CHECKIN_ORDER_FOLLOWUP, order_id),
        ).fetchone()
        if exists is not None:
            return dict(exists)
        now = datetime.now(timezone.utc)
        checkin = {
            "checkin_id": f"chk_{uuid.uuid4().hex[:20]}",
            "owner_id": owner_id,
            "kind": CHECKIN_ORDER_FOLLOWUP,
            "ref_id": order_id,
            "content": "上次那单到手了吗？用着如果有不合适的地方，直接跟我说。",
            "due_at": (now + timedelta(hours=max(1, due_hours))).isoformat(),
            "status": "PENDING",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        conn.execute(
            "INSERT INTO c_companion_checkin(checkin_id, owner_id, kind, ref_id, content, due_at, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                checkin["checkin_id"], owner_id, checkin["kind"], order_id,
                checkin["content"], checkin["due_at"], checkin["status"],
                checkin["created_at"], checkin["updated_at"],
            ),
        )
        conn.commit()
        return checkin
    finally:
        conn.close()


def _local_zone(rhythm: dict[str, Any]) -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(str(rhythm.get("timezone") or RHYTHM_TIMEZONE_DEFAULT))
    except Exception:  # noqa: BLE001 - Windows 缺少 tzdata 时退化为 UTC+8
        return timezone(timedelta(hours=8))


def _local_hour(rhythm: dict[str, Any], now: datetime) -> int:
    return now.astimezone(_local_zone(rhythm)).hour


def _is_quiet(rhythm: dict[str, Any], now: datetime) -> bool:
    start = str(rhythm.get("quiet_start") or "22:00")
    end = str(rhythm.get("quiet_end") or "09:00")
    hour = _local_hour(rhythm, now)
    start_hour = int(start[:2])
    end_hour = int(end[:2])
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _merchant_order_state(owner_id: str, order_id: str) -> tuple[str | None, str | None]:
    """读取商家订单状态与签收时间；读取失败按未知处理，不误发回访。"""
    try:
        order = get_merchant_repository().get_order(
            order_id,
            merchant_id=_MERCHANT_ID,
            buyer_id=_merchant_buyer_id(owner_id),
        )
    except Exception:  # noqa: BLE001 - 商家侧不可用时宁可暂缓回访
        return None, None
    if order is None:
        return None, None
    return str(getattr(order, "status", "") or ""), getattr(order, "completed_at", None)


def _delivered_count(conn: sqlite3.Connection, owner_id: str, since: datetime) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM c_companion_checkin "
        "WHERE owner_id = ? AND status = 'DELIVERED' AND delivered_at >= ?",
        (owner_id, since.isoformat()),
    ).fetchone()
    return int(row["n"] if row is not None else 0)


def claim_due_checkin(owner_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    """领取一条到期回访；默认关闭、免打扰、频率限制均在服务端兜底。"""
    init()
    current = now or datetime.now(timezone.utc)
    conn = _connect()
    try:
        rhythm_row = _ensure_rhythm_conn(conn, owner_id)
        rhythm = _rhythm_payload(rhythm_row)
        pause_until = rhythm.get("pause_until")
        if pause_until:
            try:
                if datetime.fromisoformat(str(pause_until)) > current:
                    return None
            except ValueError:
                pass
        if not rhythm["enabled"]:
            conn.execute(
                "UPDATE c_companion_rhythm SET last_active_at = ?, updated_at = ? WHERE owner_id = ?",
                (current.isoformat(), current.isoformat(), owner_id),
            )
            conn.commit()
            return None
        if _is_quiet(rhythm, current):
            return None
        if _delivered_count(conn, owner_id, current - timedelta(days=7)) >= 3:
            return None
        last_checkin = rhythm.get("last_checkin_at")
        if last_checkin:
            try:
                last_dt = datetime.fromisoformat(str(last_checkin))
                zone = _local_zone(rhythm)
                if last_dt.astimezone(zone).date() == current.astimezone(zone).date():
                    return None
            except ValueError:
                pass

        due_rows = conn.execute(
            "SELECT * FROM c_companion_checkin WHERE owner_id = ? AND status = 'PENDING' "
            "AND due_at <= ? ORDER BY due_at ASC LIMIT 10",
            (owner_id, current.isoformat()),
        ).fetchall()
        for row in due_rows:
            created_at = datetime.fromisoformat(str(row["created_at"]))
            if (current - created_at).days > 30:
                conn.execute(
                    "UPDATE c_companion_checkin SET status = 'SKIPPED', updated_at = ? WHERE checkin_id = ?",
                    (current.isoformat(), row["checkin_id"]),
                )
                continue
            if row["kind"] == CHECKIN_ORDER_FOLLOWUP:
                order = conn.execute(
                    "SELECT status FROM c_order WHERE order_id = ? AND buyer_id = ?",
                    (row["ref_id"], owner_id),
                ).fetchone()
                if order is None or str(order["status"]).upper() not in {"CONFIRMED", "COMPLETED"}:
                    conn.execute(
                        "UPDATE c_companion_checkin SET status = 'SKIPPED', updated_at = ? WHERE checkin_id = ?",
                        (current.isoformat(), row["checkin_id"]),
                    )
                    continue
                merchant_status, completed_at = _merchant_order_state(owner_id, str(row["ref_id"]))
                if merchant_status in {"CANCELLED", "REFUNDED"}:
                    conn.execute(
                        "UPDATE c_companion_checkin SET status = 'SKIPPED', updated_at = ? WHERE checkin_id = ?",
                        (current.isoformat(), row["checkin_id"]),
                    )
                    continue
                if merchant_status != "COMPLETED" or not completed_at:
                    # 未签收不投递；保留 PENDING，等用户下次打开 App 再检查。
                    continue
                signed_at = datetime.fromisoformat(str(completed_at))
                sign_due = signed_at + timedelta(hours=24)
                if current < sign_due:
                    conn.execute(
                        "UPDATE c_companion_checkin SET due_at = ?, updated_at = ? WHERE checkin_id = ?",
                        (sign_due.isoformat(), current.isoformat(), row["checkin_id"]),
                    )
                    continue
                if current > signed_at + timedelta(days=14):
                    conn.execute(
                        "UPDATE c_companion_checkin SET status = 'SKIPPED', updated_at = ? WHERE checkin_id = ?",
                        (current.isoformat(), row["checkin_id"]),
                    )
                    continue
            else:
                due_at = datetime.fromisoformat(str(row["due_at"]))
                if (current - due_at).days > 14:
                    conn.execute(
                        "UPDATE c_companion_checkin SET status = 'SKIPPED', updated_at = ? WHERE checkin_id = ?",
                        (current.isoformat(), row["checkin_id"]),
                    )
                    continue
            content = str(row["content"] or "").strip()
            if not content:
                content = "最近还好吗？不用急着买东西，想聊两句也行。"
            conn.execute(
                "UPDATE c_companion_checkin SET status = 'DELIVERED', delivered_at = ?, updated_at = ? "
                "WHERE checkin_id = ? AND status = 'PENDING'",
                (current.isoformat(), current.isoformat(), row["checkin_id"]),
            )
            conn.execute(
                "UPDATE c_companion_rhythm SET last_active_at = ?, last_checkin_at = ?, updated_at = ? WHERE owner_id = ?",
                (current.isoformat(), current.isoformat(), current.isoformat(), owner_id),
            )
            conn.commit()
            return {
                "checkin_id": row["checkin_id"],
                "kind": row["kind"],
                "ref_id": row["ref_id"],
                "content": c_persona.guard(content, tier="L2").text,
            }

        previous_active = rhythm.get("last_active_at")
        if previous_active:
            try:
                idle_days = (current - datetime.fromisoformat(str(previous_active))).days
            except ValueError:
                idle_days = 0
            if idle_days >= 7:
                recent_comeback = conn.execute(
                    "SELECT 1 FROM c_companion_checkin WHERE owner_id = ? AND kind = ? "
                    "AND status = 'DELIVERED' AND delivered_at >= ? LIMIT 1",
                    (owner_id, CHECKIN_COMEBACK, (current - timedelta(days=14)).isoformat()),
                ).fetchone()
                if recent_comeback is None:
                    checkin_id = f"chk_{uuid.uuid4().hex[:20]}"
                    content = "好些天没见你了。最近还好吗？不用急着买东西，想聊两句也行。"
                    conn.execute(
                        "INSERT INTO c_companion_checkin(checkin_id, owner_id, kind, ref_id, content, due_at, "
                        "delivered_at, status, created_at, updated_at) VALUES (?, ?, ?, '', ?, ?, ?, 'DELIVERED', ?, ?)",
                        (
                            checkin_id, owner_id, CHECKIN_COMEBACK, content,
                            current.isoformat(), current.isoformat(),
                            current.isoformat(), current.isoformat(),
                        ),
                    )
                    conn.execute(
                        "UPDATE c_companion_rhythm SET last_active_at = ?, last_checkin_at = ?, updated_at = ? WHERE owner_id = ?",
                        (current.isoformat(), current.isoformat(), current.isoformat(), owner_id),
                    )
                    conn.commit()
                    return {
                        "checkin_id": checkin_id,
                        "kind": CHECKIN_COMEBACK,
                        "ref_id": "",
                        "content": c_persona.guard(content, tier="L2").text,
                    }
        conn.execute(
            "UPDATE c_companion_rhythm SET last_active_at = ?, updated_at = ? WHERE owner_id = ?",
            (current.isoformat(), current.isoformat(), owner_id),
        )
        conn.commit()
        return None
    finally:
        conn.close()


def get_c_order_buyer(order_id: str) -> str | None:
    """物流回调只知道订单号，这里反查 C 端买家。"""
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT buyer_id FROM c_order WHERE order_id = ? LIMIT 1", (order_id,)
        ).fetchone()
        return str(row["buyer_id"]) if row is not None else None
    finally:
        conn.close()


def get_logistics_event(event_id: str) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM c_logistics_event WHERE event_id = ?", (str(event_id),)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def record_logistics_event(
    *,
    event_id: str,
    provider: str,
    order_id: str,
    status: str,
    occurred_at: str | None,
    payload_hash: str,
) -> bool:
    """记录已签收事件；重复 event_id 返回 False，保证回调幂等。"""
    init()
    if get_logistics_event(event_id) is not None:
        return False
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_logistics_event(event_id, provider, order_id, status, occurred_at, payload_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, provider[:40], order_id, status, occurred_at, payload_hash, _now()),
        )
        conn.commit()
        return True
    except Exception:  # noqa: BLE001 - 并发重复事件由主键兜底
        conn.rollback()
        return False
    finally:
        conn.close()


def _record_mentions(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    thread_id: str,
    message_id: str,
    text: str,
    created_at: str,
) -> None:
    for mention in mentions.extract_mentions(text):
        conn.execute(
            "INSERT OR IGNORE INTO c_mention(mention_id, owner_id, thread_id, message_id, token, "
            "target_id, target_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"mn_{uuid.uuid4().hex[:20]}",
                owner_id,
                thread_id,
                message_id,
                mention["token"],
                mention["target_id"],
                mention["name"],
                created_at,
            ),
        )


def save_app_message(
    owner_id: str,
    thread_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """持久化 C 端 App 会话消息；只存消息，不执行任何订单动作。"""
    thread = str(thread_id or "").strip()
    if not thread or len(thread) > 64:
        raise CStoreError("INVALID_THREAD", "会话 ID 不合法")
    if role not in {"user", "companion", "assistant", "system"}:
        raise CStoreError("INVALID_ROLE", "消息角色不合法")
    text = str(content or "").strip()
    if not text:
        raise CStoreError("EMPTY_MESSAGE", "消息不能为空")
    if len(text) > 2000:
        raise CStoreError("MESSAGE_TOO_LONG", "消息不能超过 2000 字")
    meta = mentions.attach_metadata(metadata, text)
    init()
    message_id = f"appmsg_{uuid.uuid4().hex[:20]}"
    created_at = _next_message_time()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO c_app_message(message_id, owner_id, thread_id, role, content, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, owner_id, thread, role, text, json.dumps(meta, ensure_ascii=False), created_at),
        )
        _record_mentions(
            conn,
            owner_id=owner_id,
            thread_id=thread,
            message_id=message_id,
            text=text,
            created_at=created_at,
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "message_id": message_id,
        "thread_id": thread,
        "role": role,
        "content": text,
        "metadata": meta,
        "created_at": created_at,
    }


def list_app_messages(
    owner_id: str,
    thread_id: str,
    limit: int = 50,
    before: str | None = None,
) -> list[dict[str, Any]]:
    """返回最近 N 条（按时间正序）；before 用于加载更早一页。"""
    init()
    conn = _connect()
    try:
        params: list[Any] = [owner_id, str(thread_id)]
        where = "owner_id = ? AND thread_id = ?"
        if before:
            where += " AND created_at < ?"
            params.append(str(before))
        params.append(max(1, min(int(limit), 200)))
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM c_app_message WHERE "
            f"{where} ORDER BY created_at DESC LIMIT ?) ORDER BY created_at ASC",
            params,
        ).fetchall()
        result = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            result.append({
                "message_id": row["message_id"],
                "thread_id": row["thread_id"],
                "role": row["role"],
                "content": row["content"],
                "metadata": metadata,
                "created_at": row["created_at"],
            })
        return result
    finally:
        conn.close()


def clear_app_messages(owner_id: str, thread_id: str) -> int:
    init()
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM c_app_message WHERE owner_id = ? AND thread_id = ?",
            (owner_id, str(thread_id)),
        )
        conn.execute(
            "DELETE FROM c_mention WHERE owner_id = ? AND thread_id = ?",
            (owner_id, str(thread_id)),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _ensure_thread_read(conn: sqlite3.Connection, owner_id: str, thread_id: str) -> str:
    row = conn.execute(
        "SELECT last_read_at FROM c_thread_read WHERE owner_id = ? AND thread_id = ?",
        (owner_id, thread_id),
    ).fetchone()
    if row is not None:
        return row["last_read_at"]
    now = _now()
    conn.execute(
        "INSERT OR IGNORE INTO c_thread_read(owner_id, thread_id, last_read_at) VALUES (?, ?, ?)",
        (owner_id, thread_id, now),
    )
    return now


def get_thread_unread(owner_id: str) -> dict[str, int]:
    """返回各会话（含群）未读数；首次访问把当前历史视为已读。"""
    init()
    # social.init 确保 c_message/c_friend 存在；该函数可能在只初始化 store 的测试里单独调用。
    from rag_demo.c_end import social

    social.init()
    conn = _connect()
    try:
        threads: dict[str, int] = {"companion": 0, "store_demo": 0, "friend_demo": 0}
        group_ids: list[str] = []
        try:
            group_ids = [
                row["group_id"]
                for row in conn.execute(
                    "SELECT group_id FROM c_group WHERE owner_id = ?", (owner_id,)
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            group_ids = []
        for group_id in group_ids:
            threads[group_id] = 0
        conn.execute("BEGIN IMMEDIATE")
        for thread_id in threads:
            last_read = _ensure_thread_read(conn, owner_id, thread_id)
            if thread_id == "companion":
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM c_app_message WHERE owner_id = ? AND thread_id = ? "
                    "AND role != 'user' AND created_at > ?",
                    (owner_id, thread_id, last_read),
                ).fetchone()["n"]
            elif thread_id in group_ids:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM c_group_message WHERE owner_id = ? AND group_id = ? "
                    "AND sender_id != ? AND created_at > ?",
                    (owner_id, thread_id, owner_id, last_read),
                ).fetchone()["n"]
            else:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM c_message WHERE owner_id = ? AND friend_id = ? "
                    "AND sender_id != ? AND created_at > ?",
                    (owner_id, thread_id, owner_id, last_read),
                ).fetchone()["n"]
            threads[thread_id] = int(count)
        conn.commit()
        return threads
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_thread_read(owner_id: str, thread_id: str) -> dict[str, Any]:
    thread = str(thread_id or "").strip()
    init()
    conn = _connect()
    try:
        if thread not in {"companion", "store_demo", "friend_demo"}:
            try:
                group_row = conn.execute(
                    "SELECT 1 FROM c_group WHERE owner_id = ? AND group_id = ?",
                    (owner_id, thread),
                ).fetchone()
            except sqlite3.OperationalError:
                group_row = None
            if group_row is None:
                raise CStoreError("INVALID_THREAD", "会话 ID 不合法")
        conn.execute("BEGIN IMMEDIATE")
        now = _now()
        conn.execute(
            "INSERT INTO c_thread_read(owner_id, thread_id, last_read_at) VALUES (?, ?, ?) "
            "ON CONFLICT(owner_id, thread_id) DO UPDATE SET last_read_at = excluded.last_read_at",
            (owner_id, thread, now),
        )
        # 进入会话即视为读掉该会话里的 @ 提及。
        conn.execute(
            "UPDATE c_mention SET read_at = ? WHERE owner_id = ? AND thread_id = ? AND read_at IS NULL",
            (now, owner_id, thread),
        )
        conn.commit()
        return {"thread_id": thread, "read_at": now}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_mentions(owner_id: str, *, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        where = "owner_id = ?"
        params: list[Any] = [owner_id]
        if unread_only:
            where += " AND read_at IS NULL"
        params.append(max(1, min(int(limit), 100)))
        rows = conn.execute(
            f"SELECT * FROM c_mention WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "mention_id": row["mention_id"],
                "thread_id": row["thread_id"],
                "message_id": row["message_id"],
                "token": row["token"],
                "target_id": row["target_id"],
                "target_name": row["target_name"],
                "created_at": row["created_at"],
                "read_at": row["read_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def unread_mention_count(owner_id: str) -> int:
    init()
    conn = _connect()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM c_mention WHERE owner_id = ? AND target_id = 'me' "
                "AND read_at IS NULL",
                (owner_id,),
            ).fetchone()["n"]
        )
    finally:
        conn.close()


def mark_all_mentions_read(owner_id: str) -> int:
    init()
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE c_mention SET read_at = ? WHERE owner_id = ? AND read_at IS NULL",
            (_now(), owner_id),
        )
        conn.commit()
        return int(cursor.rowcount)
    finally:
        conn.close()


def _reward_companion_conn(conn: sqlite3.Connection, owner_id: str, *, exp: int = 10, satiety: int = 5) -> None:
    row = _ensure_companion(conn, owner_id)
    new_exp = int(row["exp"]) + max(0, int(exp))
    new_satiety = min(100, int(row["satiety"]) + max(0, int(satiety)))
    new_level = 1 + new_exp // 100
    conn.execute(
        "UPDATE c_companion SET exp = ?, satiety = ?, level = ?, updated_at = ? WHERE owner_id = ?",
        (new_exp, new_satiety, new_level, _now(), owner_id),
    )


def reward_companion(owner_id: str, *, exp: int = 10, satiety: int = 5) -> dict[str, Any]:
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _reward_companion_conn(conn, owner_id, exp=exp, satiety=satiety)
        conn.commit()
        row = conn.execute("SELECT * FROM c_companion WHERE owner_id = ?", (owner_id,)).fetchone()
        return _companion_payload(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order(order_id: str) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        order = conn.execute("SELECT * FROM c_order WHERE order_id = ?", (order_id,)).fetchone()
        return _order_payload(conn, order) if order is not None else None
    finally:
        conn.close()
# ---------------------------------------------------------------------------
# B 端库存告警事件（站内待发送队列）
# ---------------------------------------------------------------------------

def _inventory_alert_id(merchant_id: str, sku: str) -> str:
    raw = f"{merchant_id}|{sku}".encode("utf-8")
    return "inv_" + hashlib.sha256(raw).hexdigest()[:24]


def list_merchant_ids() -> list[str]:
    """已绑定账号的商家 ID；供低库存扫描脚本遍历。"""
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT merchant_id FROM c_merchant_member ORDER BY merchant_id ASC"
        ).fetchall()
        return [str(row["merchant_id"]) for row in rows]
    finally:
        conn.close()


def sync_inventory_alerts(
    merchant_id: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """把当前低库存 SKU 同步进告警队列；已处理保留，恢复后自动 RESOLVED。"""
    merchant_id = str(merchant_id or "").strip()
    if not merchant_id:
        raise ValueError("merchant_id required")
    init()
    now = _now()
    conn = _connect()
    try:
        existing_rows = conn.execute(
            "SELECT * FROM c_inventory_alert WHERE merchant_id = ?", (merchant_id,)
        ).fetchall()
        existing = {str(row["sku"]): dict(row) for row in existing_rows}
        current_skus: list[str] = []
        created = 0
        updated = 0
        for item in items:
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue
            current_skus.append(sku)
            title = str(item.get("product_title") or item.get("title") or item.get("product_id") or "商品")
            spec = str(item.get("spec") or "")
            available = int(item.get("available_qty") or 0)
            safety = int(item.get("safety_stock") or 0)
            reorder = int(item.get("reorder_qty") or 0)
            message = f"{title}{(' / ' + spec) if spec else ''} 可售 {available}，低于安全库存 {safety}，建议补货 {reorder} 件。"
            alert_id = _inventory_alert_id(merchant_id, sku)
            exists = sku in existing
            if exists:
                updated += 1
            else:
                created += 1
            conn.execute(
                "INSERT INTO c_inventory_alert(alert_id, merchant_id, product_id, sku, sku_spec, "
                "available_qty, safety_stock, reorder_qty, severity, status, channel, message, "
                "created_at, last_seen_at, resolved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'WARNING', 'PENDING', 'IN_APP', ?, ?, ?, NULL) "
                "ON CONFLICT(alert_id) DO UPDATE SET "
                "product_id = excluded.product_id, sku_spec = excluded.sku_spec, "
                "available_qty = excluded.available_qty, safety_stock = excluded.safety_stock, "
                "reorder_qty = excluded.reorder_qty, message = excluded.message, "
                "last_seen_at = excluded.last_seen_at, resolved_at = NULL, "
                "status = CASE WHEN c_inventory_alert.status = 'RESOLVED' THEN 'PENDING' ELSE c_inventory_alert.status END, "
                "acknowledged_at = CASE WHEN c_inventory_alert.status = 'RESOLVED' THEN NULL ELSE c_inventory_alert.acknowledged_at END, "
                "acknowledged_by = CASE WHEN c_inventory_alert.status = 'RESOLVED' THEN NULL ELSE c_inventory_alert.acknowledged_by END",
                (
                    alert_id, merchant_id, str(item.get("product_id") or ""), sku, spec,
                    available, safety, reorder, message, now, now,
                ),
            )
        resolved = 0
        if current_skus:
            placeholders = ",".join("?" for _ in current_skus)
            cursor = conn.execute(
                f"UPDATE c_inventory_alert SET status = 'RESOLVED', resolved_at = ? "
                f"WHERE merchant_id = ? AND status != 'RESOLVED' AND sku NOT IN ({placeholders})",
                (now, merchant_id, *current_skus),
            )
        else:
            cursor = conn.execute(
                "UPDATE c_inventory_alert SET status = 'RESOLVED', resolved_at = ? "
                "WHERE merchant_id = ? AND status != 'RESOLVED'",
                (now, merchant_id),
            )
        resolved = int(cursor.rowcount or 0)
        conn.commit()
        pending = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM c_inventory_alert "
                "WHERE merchant_id = ? AND status = 'PENDING'",
                (merchant_id,),
            ).fetchone()["n"]
        )
        return {
            "merchant_id": merchant_id,
            "created": created,
            "updated": updated,
            "resolved": resolved,
            "pending": pending,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_inventory_alerts(
    merchant_id: str,
    *,
    status: str | None = "PENDING",
    limit: int = 100,
) -> list[dict[str, Any]]:
    init()
    limit = max(1, min(int(limit or 100), 500))
    where = "merchant_id = ?"
    params: list[Any] = [str(merchant_id or "").strip()]
    if status:
        where += " AND status = ?"
        params.append(str(status).upper())
    params.append(limit)
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM c_inventory_alert WHERE {where} "
            "ORDER BY CASE status WHEN 'PENDING' THEN 0 ELSE 1 END, last_seen_at DESC, sku ASC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def ack_inventory_alert(merchant_id: str, alert_id: str, account_id: int) -> dict[str, Any] | None:
    init()
    now = _now()
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE c_inventory_alert SET status = 'ACKED', acknowledged_at = ?, acknowledged_by = ? "
            "WHERE alert_id = ? AND merchant_id = ? AND status = 'PENDING'",
            (now, int(account_id), str(alert_id), str(merchant_id)),
        )
        conn.commit()
        if int(cursor.rowcount or 0) == 0:
            return None
        row = conn.execute(
            "SELECT * FROM c_inventory_alert WHERE alert_id = ? AND merchant_id = ?",
            (str(alert_id), str(merchant_id)),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()

def mark_inventory_alerts_sent(merchant_id: str, alert_ids: list[str]) -> int:
    """推送成功后标记 SENT；acknowledged_at 记录发送时间（系统操作，by=0）。"""
    ids = [str(item).strip() for item in alert_ids if str(item).strip()]
    if not ids:
        return 0
    init()
    now = _now()
    placeholders = ",".join("?" for _ in ids)
    conn = _connect()
    try:
        cursor = conn.execute(
            f"UPDATE c_inventory_alert SET status = 'SENT', acknowledged_at = ?, acknowledged_by = 0 "
            f"WHERE merchant_id = ? AND status = 'PENDING' AND alert_id IN ({placeholders})",
            (now, str(merchant_id or "").strip(), *ids),
        )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()
# ---------------------------------------------------------------------------
# B 端会话用户画像（C 买家 ↔ 商家店宠/客服）
# ---------------------------------------------------------------------------

def _chat_profile_payload(row: Any) -> dict[str, Any]:
    data = dict(row)
    try:
        data["profile"] = json.loads(data.get("profile_json") or "{}")
    except (TypeError, ValueError):
        data["profile"] = {}
    try:
        data["source_session_ids"] = json.loads(data.get("source_session_ids") or "[]")
    except (TypeError, ValueError):
        data["source_session_ids"] = []
    data.pop("profile_json", None)
    return data


def upsert_chat_user_profile(
    merchant_id: str,
    buyer_id: str,
    *,
    profile: dict[str, Any],
    profile_text: str,
    confidence: float = 0.0,
    source_message_count: int = 0,
    source_session_ids: list[str] | None = None,
    last_message_at: str | None = None,
    embedding: list[float] | None = None,
) -> dict[str, Any]:
    """按 merchant + buyer 写最新画像；版本号自增，向量幂等 upsert。"""
    init()
    now = _now()
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT profile_id, version FROM b_chat_user_profile WHERE merchant_id = ? AND buyer_id = ?",
            (merchant_id, buyer_id),
        ).fetchone()
        source_json = json.dumps(source_session_ids or [], ensure_ascii=False)
        if existing is None:
            profile_id = f"chatprofile_{uuid.uuid4().hex[:20]}"
            version = 1
            conn.execute(
                "INSERT INTO b_chat_user_profile(profile_id, merchant_id, buyer_id, version, "
                "profile_json, profile_text, confidence, source_message_count, source_session_ids, "
                "last_message_at, extracted_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)",
                (
                    profile_id, merchant_id, buyer_id, version,
                    json.dumps(profile, ensure_ascii=False), profile_text[:2000],
                    float(confidence or 0), int(source_message_count or 0), source_json,
                    last_message_at, now, now, now,
                ),
            )
        else:
            profile_id = str(existing["profile_id"])
            version = int(existing["version"] or 1) + 1
            conn.execute(
                "UPDATE b_chat_user_profile SET version = ?, profile_json = ?, profile_text = ?, "
                "confidence = ?, source_message_count = ?, source_session_ids = ?, "
                "last_message_at = ?, extracted_at = ?, status = 'ACTIVE', updated_at = ? "
                "WHERE profile_id = ?",
                (
                    version, json.dumps(profile, ensure_ascii=False), profile_text[:2000],
                    float(confidence or 0), int(source_message_count or 0), source_json,
                    last_message_at, now, now, profile_id,
                ),
            )
        if embedding is not None:
            vector_text = json.dumps([float(x) for x in embedding])
            if _cend_pg_enabled():
                conn.execute(
                    "INSERT INTO b_chat_user_profile_vector(profile_id, merchant_id, buyer_id, embedding, updated_at) "
                    "VALUES (?, ?, ?, ?::vector, ?) ON CONFLICT(profile_id) DO UPDATE SET "
                    "embedding = excluded.embedding, merchant_id = excluded.merchant_id, "
                    "buyer_id = excluded.buyer_id, updated_at = excluded.updated_at",
                    (profile_id, merchant_id, buyer_id, vector_text, now),
                )
            else:
                conn.execute(
                    "INSERT INTO b_chat_user_profile_vector(profile_id, merchant_id, buyer_id, embedding, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(profile_id) DO UPDATE SET "
                    "embedding = excluded.embedding, updated_at = excluded.updated_at",
                    (profile_id, merchant_id, buyer_id, vector_text, now),
                )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM b_chat_user_profile WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        return _chat_profile_payload(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_chat_user_profile(merchant_id: str, buyer_id: str) -> dict[str, Any] | None:
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM b_chat_user_profile WHERE merchant_id = ? AND buyer_id = ? AND status = 'ACTIVE'",
            (merchant_id, buyer_id),
        ).fetchone()
        return _chat_profile_payload(row) if row is not None else None
    finally:
        conn.close()


def has_chat_user_profile_vector(profile_id: str) -> bool:
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT profile_id FROM b_chat_user_profile_vector WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def list_chat_user_profiles(merchant_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    init()
    where = "status = 'ACTIVE'"
    params: list[Any] = []
    if merchant_id:
        where += " AND merchant_id = ?"
        params.append(merchant_id)
    params.append(max(1, min(int(limit), 500)))
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM b_chat_user_profile WHERE {where} ORDER BY extracted_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [_chat_profile_payload(row) for row in rows]
    finally:
        conn.close()


def delete_chat_user_profile(merchant_id: str, buyer_id: str) -> bool:
    init()
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE b_chat_user_profile SET status = 'DELETED', updated_at = ? "
            "WHERE merchant_id = ? AND buyer_id = ? AND status = 'ACTIVE'",
            (_now(), merchant_id, buyer_id),
        )
        conn.execute(
            "DELETE FROM b_chat_user_profile_vector WHERE merchant_id = ? AND buyer_id = ?",
            (merchant_id, buyer_id),
        )
        conn.commit()
        return int(cursor.rowcount or 0) > 0
    finally:
        conn.close()


def search_chat_user_profiles(
    merchant_id: str,
    query_text: str,
    query_embedding: list[float] | None,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """当前商家内语义检索；SQLite 退回文本匹配。"""
    init()
    limit = max(1, min(int(limit), 50))
    conn = _connect()
    try:
        if _cend_pg_enabled() and query_embedding:
            rows = conn.execute(
                "SELECT p.*, (v.embedding <=> ?::vector) AS distance "
                "FROM b_chat_user_profile p JOIN b_chat_user_profile_vector v ON v.profile_id = p.profile_id "
                "WHERE p.merchant_id = ? AND p.status = 'ACTIVE' AND v.embedding IS NOT NULL "
                "ORDER BY distance ASC LIMIT ?",
                (json.dumps([float(x) for x in query_embedding]), merchant_id, limit),
            ).fetchall()
        else:
            keyword = str(query_text or "").strip()
            if keyword:
                rows = conn.execute(
                    "SELECT * FROM b_chat_user_profile WHERE merchant_id = ? AND status = 'ACTIVE' "
                    "AND (profile_text LIKE ? OR profile_json LIKE ?) ORDER BY extracted_at DESC LIMIT ?",
                    (merchant_id, f"%{keyword[:80]}%", f"%{keyword[:80]}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM b_chat_user_profile WHERE merchant_id = ? AND status = 'ACTIVE' "
                    "ORDER BY extracted_at DESC LIMIT ?",
                    (merchant_id, limit),
                ).fetchall()
        result = []
        for row in rows:
            item = _chat_profile_payload(row)
            if "distance" in item:
                item["distance"] = float(item["distance"])
            result.append(item)
        return result
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# 商家店宠会话映射：一个商家可以有一个店宠 friend_id
# ---------------------------------------------------------------------------

def list_store_friend_mappings() -> list[dict[str, Any]]:
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT f.friend_id, f.merchant_id, t.name AS merchant_name "
            "FROM c_merchant_store_friend f "
            "LEFT JOIN c_merchant_tenant t ON t.merchant_id = f.merchant_id "
            "ORDER BY f.merchant_id, f.friend_id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def merchant_for_store_friend(friend_id: str) -> str | None:
    init()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT merchant_id FROM c_merchant_store_friend WHERE friend_id = ?",
            (str(friend_id),),
        ).fetchone()
        return str(row["merchant_id"]) if row is not None else None
    finally:
        conn.close()


def bind_store_friend(merchant_id: str, friend_id: str) -> dict[str, Any]:
    """绑定店宠会话到商家；friend_id 全局唯一。"""
    init()
    now = _now()
    conn = _connect()
    try:
        tenant = conn.execute(
            "SELECT merchant_id FROM c_merchant_tenant WHERE merchant_id = ?",
            (str(merchant_id),),
        ).fetchone()
        if tenant is None:
            raise CStoreError("MERCHANT_NOT_FOUND", "商家不存在")
        existing = conn.execute(
            "SELECT merchant_id FROM c_merchant_store_friend WHERE friend_id = ?",
            (str(friend_id),),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO c_merchant_store_friend(merchant_id, friend_id, created_at) "
                "VALUES (?, ?, ?)",
                (str(merchant_id), str(friend_id), now),
            )
        else:
            conn.execute(
                "UPDATE c_merchant_store_friend SET merchant_id = ? WHERE friend_id = ?",
                (str(merchant_id), str(friend_id)),
            )
        conn.commit()
        return {"merchant_id": str(merchant_id), "friend_id": str(friend_id)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

