#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : auth.py
@Function: 账号 / 企业 / 会话（M3）——登录态的唯一真源

为什么单独一个模块
------------------
权限（permissions.py）回答的是「这个身份能看到什么」；本模块回答的是
「这个请求**是谁**」。两者必须分开：权限可以按等级配置，身份不能配置。

存哪、为什么
------------
用 SQLite（`var/app.db`，stdlib 的 `sqlite3`，无新依赖）而不是 PostgreSQL：

- 账号是**跨数据集**的：它必须在任何数据集库被重建/清空时都不受影响，
  而 demo 库同时是评测基线，user/企业库随时可能被 TRUNCATE；
- 登录判定在**每个请求**的入口，走网络数据库会把一次 401 变成一次 IO；
- 数据量极小（账号 + 会话），SQLite 单文件足够，备份就是拷一个文件。

⚠ 单进程内 SQLite 连接用 `check_same_thread=False` + 模块锁串行化。
  多进程（uvicorn --workers）下 SQLite 自身保证写锁，账号量级不会成为瓶颈。

账号类型
--------
- **企业账号**（`account_type=enterprise`）：注册 → 系统管理员审核 →
  创建企业、分配企业库（`vec_db_ent_<id>`）、生成邀请码，账号本身成为企业管理员；
- **员工账号**（`account_type=employee`）：注册时必须填所属企业的邀请码，
  归属该企业；审核通过后由企业管理员/系统管理员分配角色；
- **系统管理员**：初始种子账号（`admin`），可审核企业与员工、改全局权限。

企业是**数据隔离的单位**：同一企业的员工共享同一个库，企业之间互不可见。
这也是「数据库按企业账号划分」的落地方式——不是按人，是按企业。

审核与状态
----------
`status`：`pending`（待审核，能登录但没有任何能力）/ `active` / `disabled`。
待审核的人**能登录**是有意的：登录后能看到「等待审核」，比「密码对了却登不进」
少一类"我密码是不是错了"的误判。没有能力由 permissions 的 L0 保证。
"""
import contextvars
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("RAG_AUTH_DB") or os.path.join(_BASE_DIR, "var", "app.db")

# ---------- 开关（都留了环境变量，方便离线回归/部署时覆盖） ----------
# 关闭后回到 M2 的"请求头自报身份"，仅用于离线脚本；默认开启登录态
AUTH_ENABLED = os.environ.get("RAG_AUTH_ENABLED", "1") != "0"
# 逃生开关：登录态开启时，是否仍接受 X-Role / X-User（默认拒绝）
ALLOW_HEADER_AUTH = os.environ.get("RAG_ALLOW_HEADER_AUTH", "0") == "1"
SESSION_COOKIE = "rag_session"
SEED_ADMIN_USERNAME = os.environ.get("RAG_ADMIN_USER", "admin")
SEED_ADMIN_PASSWORD = os.environ.get("RAG_ADMIN_PASSWORD", "admin123")

ACCOUNT_ENTERPRISE = "enterprise"
ACCOUNT_EMPLOYEE = "employee"
ACCOUNT_TYPES = (ACCOUNT_ENTERPRISE, ACCOUNT_EMPLOYEE)
ACCOUNT_TYPE_LABELS = {
    ACCOUNT_ENTERPRISE: "企业",
    ACCOUNT_EMPLOYEE: "员工",
}

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_LABELS = {
    STATUS_PENDING: "待审核",
    STATUS_ACTIVE: "正常",
    STATUS_DISABLED: "已停用",
}

# PBKDF2 参数：20 万次在单机上约 60~100ms，登录频率下完全可接受。
# 迭代次数写进哈希串里，将来调高不用迁移旧密码（按存的那份校验）。
_PBKDF2_ITER = 200_000
_HASH_PREFIX = "pbkdf2_sha256"

# 会话有效期：7 天。演示环境不该让人每次重启服务就重新登录。
SESSION_TTL_SECONDS = 7 * 24 * 3600

_LOCK = threading.RLock()
_conn: sqlite3.Connection | None = None

# 当前请求的账号（由 API 中间件设置）。用 contextvar 而不是全局变量：
# 并发请求各看各的，不会出现"A 的账号被 B 用到"。
_current_account: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "rag_current_account", default=None
)


def set_current_account(account: dict[str, Any] | None):
    _current_account.set(account)


def current_account() -> dict[str, Any] | None:
    """当前请求已登录的账号（未登录为 None）。向导侧据此决定企业库与归属。"""
    return _current_account.get()


# ==================== 建库 ====================


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS enterprise (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    invite_code   TEXT NOT NULL UNIQUE,
    dataset       TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_user (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT NOT NULL UNIQUE,
    display_name        TEXT NOT NULL DEFAULT '',
    password_hash       TEXT NOT NULL,
    account_type        TEXT NOT NULL,
    role                TEXT NOT NULL DEFAULT 'cs',
    enterprise_id       INTEGER,
    is_system_admin     INTEGER NOT NULL DEFAULT 0,
    is_enterprise_admin INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TEXT NOT NULL,
    reviewed_at         TEXT,
    reviewed_by         TEXT,
    last_login_at       TEXT
);

CREATE TABLE IF NOT EXISTS session (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

-- 上传批次属于哪个企业：上传、构建、查询三处都要校验，
-- 否则拿到别人的 upload_id 就能读/构建/查询别人的数据。
CREATE TABLE IF NOT EXISTS upload_owner (
    upload_id     TEXT PRIMARY KEY,
    enterprise_id INTEGER,
    user_id       INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def _db() -> sqlite3.Connection:
    """进程内单连接 + 锁串行化（见模块注释）"""
    global _conn
    with _LOCK:
        if _conn is None:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(_SCHEMA)
            _conn.commit()
        return _conn


def _row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["is_system_admin"] = bool(data.get("is_system_admin"))
    data["is_enterprise_admin"] = bool(data.get("is_enterprise_admin"))
    data["status_label"] = STATUS_LABELS.get(data.get("status"), data.get("status"))
    data["account_type_label"] = ACCOUNT_TYPE_LABELS.get(
        data.get("account_type"), data.get("account_type")
    )
    return data


def init(seed_username: str, seed_password: str) -> None:
    """
    初始化表 + 种子系统管理员（幂等）

    只在"一个账号都没有"时创建种子账号：否则每次重启都会把一个已知密码的
    admin 塞回去，等于给系统留后门。
    """
    with _LOCK:
        conn = _db()
        cur = conn.execute("SELECT COUNT(*) AS n FROM app_user")
        if cur.fetchone()["n"] > 0:
            return
        if len(seed_password) < 6:
            raise ValueError("种子管理员密码至少 6 位")
        conn.execute(
            """INSERT INTO app_user
               (username, display_name, password_hash, account_type, role,
                is_system_admin, status, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                seed_username.strip().lower(),
                "系统管理员",
                hash_password(seed_password),
                ACCOUNT_EMPLOYEE,
                "admin",
                STATUS_ACTIVE,
                _now(),
            ),
        )
        conn.commit()
        logger.warning(
            "已创建初始系统管理员 %s（密码来自 RAG_ADMIN_PASSWORD，默认 admin123），"
            "请在正式使用前修改", seed_username,
        )


# ==================== 密码 ====================


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return f"{_HASH_PREFIX}${_PBKDF2_ITER}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """定长比较，避免"逐字节比较耗时"泄露密码前缀"""
    try:
        prefix, iter_s, salt_hex, digest_hex = stored.split("$")
        if prefix != _HASH_PREFIX:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iter_s)
        )
        return hmac.compare_digest(actual, expected)
    except Exception:  # noqa: BLE001 存坏了就当验证失败，不放行
        return False


# ==================== 账号 ====================


def find_user(username: str) -> dict[str, Any] | None:
    with _LOCK:
        row = _db().execute(
            "SELECT * FROM app_user WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
        return _row_to_user(row)


def find_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _LOCK:
        row = _db().execute("SELECT * FROM app_user WHERE id = ?", (int(user_id),)).fetchone()
        return _row_to_user(row)


def list_users(enterprise_id: int | None = None) -> list[dict[str, Any]]:
    """`enterprise_id=None` = 全部（仅系统管理员调用）"""
    with _LOCK:
        conn = _db()
        if enterprise_id is None:
            rows = conn.execute(
                "SELECT * FROM app_user ORDER BY status = 'pending' DESC, id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM app_user WHERE enterprise_id = ? "
                "ORDER BY status = 'pending' DESC, id ASC",
                (int(enterprise_id),),
            ).fetchall()
        return [_row_to_user(r) for r in rows]


def create_user(
    username: str,
    password: str,
    account_type: str,
    display_name: str = "",
    invite_code: str | None = None,
) -> dict[str, Any]:
    """
    注册：一律落 `pending`，角色先给最低档（审核时才分配）

    校验放这里而不是只在前端：前端挡的是手滑，后端挡的才是越权/脏数据。
    """
    username = (username or "").strip().lower()
    if not username or len(username) < 3 or len(username) > 32:
        raise ValueError("用户名需为 3~32 个字符")
    if not all(c.isalnum() or c in "_-." for c in username):
        raise ValueError("用户名只能包含字母、数字、下划线、连字符和点")
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")
    if account_type not in ACCOUNT_TYPES:
        raise ValueError("账号类型只能是 企业 / 员工")

    enterprise_id = None
    if account_type == ACCOUNT_EMPLOYEE:
        if not invite_code:
            raise ValueError("员工账号需要填写企业邀请码")
        ent = find_enterprise_by_code(invite_code)
        if ent is None:
            raise ValueError("企业邀请码无效")
        enterprise_id = ent["id"]
    elif invite_code:
        raise ValueError("企业账号不需要邀请码（审核通过后会生成）")

    with _LOCK:
        conn = _db()
        if conn.execute("SELECT 1 FROM app_user WHERE username = ?", (username,)).fetchone():
            raise ValueError("用户名已被占用")
        conn.execute(
            """INSERT INTO app_user
               (username, display_name, password_hash, account_type, role,
                enterprise_id, status, created_at)
               VALUES (?, ?, ?, ?, 'cs', ?, ?, ?)""",
            (
                username,
                (display_name or username).strip()[:64],
                hash_password(password),
                account_type,
                enterprise_id,
                STATUS_PENDING,
                _now(),
            ),
        )
        conn.commit()
    user = find_user(username)
    assert user is not None
    logger.info("新注册（待审核）: %s 类型=%s 企业=%s", username, account_type, enterprise_id)
    return user


def authenticate(username: str, password: str) -> dict[str, Any]:
    """校验用户名密码；失败一律抛同一句话，不区分"用户不存在/密码错" """
    user = find_user(username)
    if user is None or not verify_password(password, user["password_hash"]):
        raise ValueError("用户名或密码不正确")
    if user["status"] == STATUS_DISABLED:
        raise ValueError("该账号已停用，请联系管理员")
    with _LOCK:
        conn = _db()
        conn.execute("UPDATE app_user SET last_login_at = ? WHERE id = ?", (_now(), user["id"]))
        conn.commit()
    return user


def approve(user_id: int, role: str, actor: str) -> dict[str, Any]:
    """
    审核通过：企业账号会顺带创建企业、企业库与邀请码

    「先审核、后建库」：建库要连维护库执行 CREATE DATABASE，属于重操作，
    不该挂在一次点击上等几秒；这里只登记数据集名（DATASETS 注册），
    真正的库在第一次构建时创建（见 db/provision.py）。
    """
    from rag_demo import permissions

    if role not in permissions.ROLES or role == permissions.ROLE_GUEST:
        raise ValueError(f"角色非法: {role}")

    user = find_user_by_id(user_id)
    if user is None:
        raise ValueError("账号不存在")
    if user["status"] == STATUS_ACTIVE:
        return user

    enterprise = None
    if user["account_type"] == ACCOUNT_ENTERPRISE and not user["enterprise_id"]:
        enterprise = _create_enterprise(user)

    with _LOCK:
        conn = _db()
        conn.execute(
            """UPDATE app_user
               SET status = ?, role = ?, reviewed_at = ?, reviewed_by = ?,
                   enterprise_id = COALESCE(?, enterprise_id),
                   is_enterprise_admin = CASE WHEN ? = 'enterprise' THEN 1 ELSE is_enterprise_admin END
               WHERE id = ?""",
            (
                STATUS_ACTIVE,
                role,
                _now(),
                actor,
                enterprise["id"] if enterprise else None,
                user["account_type"],
                user["id"],
            ),
        )
        conn.commit()
    updated = find_user_by_id(user_id)
    assert updated is not None
    logger.info("账号审核通过: %s role=%s by %s", updated["username"], role, actor)
    return updated


def set_role(user_id: int, role: str, actor: str) -> dict[str, Any]:
    from rag_demo import permissions

    if role not in permissions.ROLES or role == permissions.ROLE_GUEST:
        raise ValueError(f"角色非法: {role}")
    with _LOCK:
        conn = _db()
        if conn.execute("SELECT 1 FROM app_user WHERE id = ?", (int(user_id),)).fetchone() is None:
            raise ValueError("账号不存在")
        conn.execute("UPDATE app_user SET role = ? WHERE id = ?", (role, int(user_id)))
        conn.commit()
    logger.info("账号改角色: id=%s role=%s by %s", user_id, role, actor)
    return find_user_by_id(user_id)  # type: ignore[return-value]


def set_status(user_id: int, status: str, actor: str) -> dict[str, Any]:
    if status not in (STATUS_ACTIVE, STATUS_DISABLED):
        raise ValueError("状态只能是 active / disabled")
    with _LOCK:
        conn = _db()
        conn.execute(
            "UPDATE app_user SET status = ?, reviewed_at = ?, reviewed_by = ? WHERE id = ?",
            (status, _now(), actor, int(user_id)),
        )
        conn.commit()
    logger.info("账号状态: id=%s -> %s by %s", user_id, status, actor)
    return find_user_by_id(user_id)  # type: ignore[return-value]


# ==================== 企业 ====================


def _new_invite_code() -> str:
    # 去掉容易读错的字符（0/O/1/I），企业管理员多半是手抄给同事的
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _create_enterprise(user: dict[str, Any]) -> dict[str, Any]:
    name = (user.get("display_name") or user["username"]).strip()[:64]
    with _LOCK:
        conn = _db()
        # 同名企业加后缀，避免注册时因重名卡住（企业名不像用户名需要全局唯一）
        base, n = name, 1
        while conn.execute("SELECT 1 FROM enterprise WHERE name = ?", (name,)).fetchone():
            n += 1
            name = f"{base}-{n}"
        cur = conn.execute(
            "INSERT INTO enterprise (name, invite_code, dataset, created_at) VALUES (?, ?, ?, ?)",
            (name, _new_invite_code(), "pending", _now()),
        )
        ent_id = int(cur.lastrowid)
        dataset = f"ent_{ent_id}"
        conn.execute(
            "UPDATE enterprise SET dataset = ?, owner_user_id = ? WHERE id = ?",
            (dataset, user["id"], ent_id),
        )
        conn.commit()
    ent = find_enterprise(ent_id)
    assert ent is not None
    logger.info("已创建企业: %s (dataset=%s)", ent["name"], ent["dataset"])
    return ent


def find_enterprise(enterprise_id: int) -> dict[str, Any] | None:
    with _LOCK:
        row = _db().execute(
            "SELECT * FROM enterprise WHERE id = ?", (int(enterprise_id),)
        ).fetchone()
        return dict(row) if row else None


def find_enterprise_by_code(code: str) -> dict[str, Any] | None:
    with _LOCK:
        row = _db().execute(
            "SELECT * FROM enterprise WHERE invite_code = ?", ((code or "").strip().upper(),)
        ).fetchone()
        return dict(row) if row else None


def list_enterprises() -> list[dict[str, Any]]:
    with _LOCK:
        rows = _db().execute("SELECT * FROM enterprise ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def enterprise_of(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user or not user.get("enterprise_id"):
        return None
    return find_enterprise(int(user["enterprise_id"]))


# ==================== 会话 ====================


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    """
    发一个会话令牌（Cookie 里存原文，库里只存 sha256）

    只存哈希的原因：库文件被拷走时，令牌不能直接拿来登录。
    """
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _LOCK:
        conn = _db()
        # 顺手清掉过期会话：没有定时任务，就在登录这个低频动作里做
        conn.execute("DELETE FROM session WHERE expires_at < ?", (_now(),))
        conn.execute(
            "INSERT INTO session (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                _token_hash(token),
                int(user_id),
                _now(),
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now + SESSION_TTL_SECONDS)),
            ),
        )
        conn.commit()
    return token


def resolve_session(token: str | None) -> dict[str, Any] | None:
    """令牌 → 账号（附带企业信息）；过期/停用/不存在都返回 None"""
    if not token:
        return None
    with _LOCK:
        conn = _db()
        row = conn.execute(
            """SELECT u.* FROM session s JOIN app_user u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at >= ?""",
            (_token_hash(token), _now()),
        ).fetchone()
        if row is None:
            return None
        user = _row_to_user(row)
        if user is None or user["status"] == STATUS_DISABLED:
            return None
        ent = None
        if user.get("enterprise_id"):
            ent_row = conn.execute(
                "SELECT * FROM enterprise WHERE id = ?", (user["enterprise_id"],)
            ).fetchone()
            ent = dict(ent_row) if ent_row else None
        user["enterprise"] = ent
        user["dataset"] = ent["dataset"] if ent else None
        return user


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _LOCK:
        conn = _db()
        conn.execute("DELETE FROM session WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()


def purge_expired_sessions() -> int:
    with _LOCK:
        conn = _db()
        cur = conn.execute("DELETE FROM session WHERE expires_at < ?", (_now(),))
        conn.commit()
        return cur.rowcount


# ==================== 上传归属 ====================


def bind_upload(upload_id: str, user: dict[str, Any]) -> None:
    with _LOCK:
        conn = _db()
        conn.execute(
            "INSERT OR REPLACE INTO upload_owner (upload_id, enterprise_id, user_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (upload_id, user.get("enterprise_id"), user["id"], _now()),
        )
        conn.commit()


def upload_owner(upload_id: str) -> dict[str, Any] | None:
    with _LOCK:
        row = _db().execute(
            "SELECT * FROM upload_owner WHERE upload_id = ?", (upload_id,)
        ).fetchone()
        return dict(row) if row else None


def unbind_upload(upload_id: str) -> None:
    with _LOCK:
        conn = _db()
        conn.execute("DELETE FROM upload_owner WHERE upload_id = ?", (upload_id,))
        conn.commit()


def can_access_upload(user: dict[str, Any] | None, upload_id: str) -> bool:
    """
    谁能用这批上传：同企业的人 + 系统管理员

    没有归属记录（M2 之前的历史批次）只有系统管理员能碰：
    否则任何人都能猜/捡到一个旧 id 去构建别人的数据。
    """
    if user is None:
        return False
    if user.get("is_system_admin"):
        return True
    owner = upload_owner(upload_id)
    if owner is None:
        return False
    return owner.get("enterprise_id") is not None and owner["enterprise_id"] == user.get("enterprise_id")
