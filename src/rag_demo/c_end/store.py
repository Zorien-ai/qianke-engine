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


def _connect() -> sqlite3.Connection:
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
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS c_app_message (
    message_id  TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_app_message_owner_thread
    ON c_app_message (owner_id, thread_id, created_at);
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
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
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
            ):
                if column_name not in companion_columns:
                    conn.execute(
                        f"ALTER TABLE c_companion ADD COLUMN {column_name} {column_ddl}"
                    )
            conn.execute(
                "UPDATE c_companion SET name = ? WHERE name = '小伴' AND user_nickname = ''",
                (c_persona.DEFAULT_NAME,),
            )
            conn.commit()
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
            _MERCHANT_ID,
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
    }


def list_orders(buyer_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """买家已确认/已取消订单，用于订单页展示与审计查询。"""
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_order WHERE buyer_id = ? AND status IN ('CONFIRMED', 'CANCELLED') "
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
    meta = metadata or {}
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
        conn.commit()
        return cursor.rowcount
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
