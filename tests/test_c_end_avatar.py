# -*- coding: utf-8 -*-
"""C 端自定义头像：存储校验、owner 隔离、HTTP 接口与旧库迁移。

覆盖需求（task-41）：
- 上传成功（PNG / JPEG / WebP）；
- 类型 / 大小 / 伪造内容拒绝；
- 文件名与相对路径由服务端生成，路径不可由用户控制；
- 跨用户不能读他人头像；
- 恢复默认头像（前端回退首字）；
- 旧 SQLite 库自动补 avatar_path / user_avatar_path 列。
"""
from __future__ import annotations

import base64
import re
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_demo import auth
from rag_demo.api.c_end import router
from rag_demo.c_end import store

# 1x1 真实图片字节（只用于存储/接口测试，服务端不解码图片内容）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)
WEBP_1PX = base64.b64decode(
    "UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAwA0JaQAA3AA/vuUAAA="
)

AVATAR_PATH_RE = re.compile(r"^[0-9a-f]{16}/(companion|user)_[0-9a-f]{32}\.(png|jpg|webp)$")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setenv("QIANKE_C_END_AVATAR_DIR", str(tmp_path / "avatars"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    monkeypatch.setattr(store, "_AVATAR_ROOT", None)
    store.init()
    return store


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setenv("QIANKE_C_END_AVATAR_DIR", str(tmp_path / "avatars"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    monkeypatch.setattr(store, "_AVATAR_ROOT", None)
    store.init()

    app = FastAPI()
    app.include_router(router)
    holder: dict = {"account": {"id": 1, "username": "buyer_a", "status": auth.STATUS_ACTIVE}}

    def fake_current_account():
        return holder["account"]

    monkeypatch.setattr(auth, "current_account", fake_current_account)
    return TestClient(app), holder, tmp_path


def _avatar_files(tmp_path):
    root = tmp_path / "avatars"
    if not root.exists():
        return []
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


def _db_path(c_store):
    return c_store._db_path()


def _db_row(c_store, owner_id):
    conn = sqlite3.connect(str(_db_path(c_store)))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM c_companion WHERE owner_id = ?", (owner_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _use_account(holder, account_id):
    holder["account"] = {
        "id": account_id,
        "username": f"buyer_{account_id}",
        "status": auth.STATUS_ACTIVE,
    }


# ---------------------------------------------------------------------------
# 存储层：上传 / 校验 / 恢复默认
# ---------------------------------------------------------------------------


def test_upload_png_saves_controlled_path_and_serves_bytes(c_store, tmp_path):
    result = c_store.save_companion_avatar("buyer_1", "companion", PNG_1PX, "image/png")

    assert result["avatar_url"].startswith("/api/c/companion/avatar/companion?v=")
    assert result["user_avatar_url"] == ""
    assert result["uploaded_avatar"]["kind"] == "companion"
    assert result["uploaded_avatar"]["content_type"] == "image/png"
    assert result["uploaded_avatar"]["bytes"] == len(PNG_1PX)

    files = _avatar_files(tmp_path)
    assert len(files) == 1
    assert AVATAR_PATH_RE.fullmatch(files[0]), files[0]
    assert (tmp_path / "avatars" / files[0]).read_bytes() == PNG_1PX
    assert _db_row(c_store, "buyer_1")["avatar_path"] == files[0]

    found = c_store.get_companion_avatar("buyer_1", "companion")
    assert found is not None
    assert found[0] == PNG_1PX
    assert found[1] == "image/png"

    # 目录 token 由 owner_id 摘要得到，不包含原始 owner_id
    assert "buyer_1" not in files[0]


def test_upload_supports_jpeg_and_webp(c_store, tmp_path):
    jpeg = c_store.save_companion_avatar("buyer_1", "companion", JPEG_1PX, "image/jpeg")
    webp = c_store.save_companion_avatar("buyer_1", "user", WEBP_1PX, "image/webp")

    assert jpeg["avatar_url"]
    assert webp["user_avatar_url"]
    # companion / user 两种头像互不覆盖
    assert webp["avatar_url"] == jpeg["avatar_url"]
    files = _avatar_files(tmp_path)
    assert any(name.endswith(".jpg") for name in files)
    assert any(name.endswith(".webp") for name in files)

    user_found = c_store.get_companion_avatar("buyer_1", "user")
    assert user_found is not None and user_found[0] == WEBP_1PX
    assert user_found[1] == "image/webp"


def test_reject_unsupported_mime(c_store, tmp_path):
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.save_companion_avatar("buyer_1", "companion", PNG_1PX, "image/gif")
    assert exc.value.code == "INVALID_AVATAR_TYPE"
    assert _avatar_files(tmp_path) == []
    assert _db_row(c_store, "buyer_1") is None or _db_row(c_store, "buyer_1")["avatar_path"] == ""


def test_reject_spoofed_image_content(c_store, tmp_path):
    # 声明 PNG，内容却是 JPEG：必须按内容魔数拒绝，不能只看 MIME
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.save_companion_avatar("buyer_1", "companion", JPEG_1PX, "image/png")
    assert exc.value.code == "INVALID_AVATAR_CONTENT"
    assert _avatar_files(tmp_path) == []


def test_reject_oversized_and_accept_exact_limit(c_store, tmp_path):
    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * store.AVATAR_MAX_BYTES
    assert len(oversized) > store.AVATAR_MAX_BYTES
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.save_companion_avatar("buyer_1", "companion", oversized, "image/png")
    assert exc.value.code == "AVATAR_TOO_LARGE"
    assert _avatar_files(tmp_path) == []

    exact = PNG_1PX + b"\x00" * (store.AVATAR_MAX_BYTES - len(PNG_1PX))
    assert len(exact) == store.AVATAR_MAX_BYTES
    saved = c_store.save_companion_avatar("buyer_1", "companion", exact, "image/png")
    assert saved["avatar_url"]
    assert len(_avatar_files(tmp_path)) == 1


def test_upload_replaces_old_file(c_store, tmp_path):
    first = c_store.save_companion_avatar("buyer_1", "companion", PNG_1PX, "image/png")
    first_file = _db_row(c_store, "buyer_1")["avatar_path"]
    second = c_store.save_companion_avatar("buyer_1", "companion", WEBP_1PX, "image/webp")
    second_file = _db_row(c_store, "buyer_1")["avatar_path"]

    assert first["avatar_url"] != second["avatar_url"]
    assert first_file != second_file
    files = _avatar_files(tmp_path)
    assert second_file in files
    assert first_file not in files


def test_restore_default_removes_file_and_url(c_store, tmp_path):
    c_store.save_companion_avatar("buyer_1", "companion", PNG_1PX, "image/png")
    assert _avatar_files(tmp_path)

    cleared = c_store.clear_companion_avatar("buyer_1", "companion")
    assert cleared["avatar_url"] == ""
    assert _avatar_files(tmp_path) == []
    assert c_store.get_companion_avatar("buyer_1", "companion") is None

    # 重复恢复默认是幂等的，不报错
    again = c_store.clear_companion_avatar("buyer_1", "companion")
    assert again["avatar_url"] == ""


def test_invalid_kind_is_rejected(c_store):
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.save_companion_avatar("buyer_1", "face", PNG_1PX, "image/png")
    assert exc.value.code == "INVALID_AVATAR_KIND"


def test_avatar_path_from_db_cannot_escape_root(c_store, tmp_path):
    c_store.get_companion("buyer_1")  # 初始化 c_companion 行
    conn = sqlite3.connect(str(_db_path(c_store)))
    try:
        for evil in ("../outside.png", "/etc/passwd", "other/../escape.png"):
            conn.execute(
                "UPDATE c_companion SET avatar_path = ? WHERE owner_id = ?",
                (evil, "buyer_1"),
            )
            conn.commit()
            with pytest.raises(c_store.CStoreError) as exc:
                c_store.get_companion_avatar("buyer_1", "companion")
            assert exc.value.code == "AVATAR_NOT_FOUND"
        # 非唯一文件名的合法目录结构也不接受
        conn.execute(
            "UPDATE c_companion SET avatar_path = ? WHERE owner_id = ?",
            (f"{'a' * 16}/companion_not-uuid.png", "buyer_1"),
        )
        conn.commit()
        with pytest.raises(c_store.CStoreError) as exc:
            c_store.get_companion_avatar("buyer_1", "companion")
        assert exc.value.code == "AVATAR_NOT_FOUND"
    finally:
        conn.close()
    assert _avatar_files(tmp_path) == []


# ---------------------------------------------------------------------------
# 存储层：owner 隔离 / 旧库迁移
# ---------------------------------------------------------------------------


def test_owner_avatars_are_isolated(c_store, tmp_path):
    c_store.save_companion_avatar("buyer_1", "companion", PNG_1PX, "image/png")
    assert c_store.get_companion_avatar("buyer_2", "companion") is None
    assert c_store.get_companion("buyer_2")["avatar_url"] == ""

    other_png = PNG_1PX + b"different"
    c_store.save_companion_avatar("buyer_2", "companion", other_png, "image/png")
    buyer_1 = c_store.get_companion_avatar("buyer_1", "companion")
    buyer_2 = c_store.get_companion_avatar("buyer_2", "companion")
    assert buyer_1 is not None and buyer_1[0] == PNG_1PX
    assert buyer_2 is not None and buyer_2[0] == other_png

    files = _avatar_files(tmp_path)
    assert len({name.split("/")[0] for name in files}) == 2


def test_old_database_migrates_avatar_columns(tmp_path, monkeypatch):
    old_db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(old_db))
    try:
        conn.execute(
            """
            CREATE TABLE c_companion (
                owner_id   TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                user_nickname TEXT NOT NULL DEFAULT '',
                species    TEXT NOT NULL DEFAULT 'digital_companion',
                persona    TEXT NOT NULL DEFAULT 'warm',
                appearance TEXT NOT NULL DEFAULT '',
                level      INTEGER NOT NULL DEFAULT 1,
                exp        INTEGER NOT NULL DEFAULT 0,
                satiety    INTEGER NOT NULL DEFAULT 60,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO c_companion(owner_id, name, user_nickname, updated_at) "
            "VALUES ('buyer_old', '小鱼', '', '2026-10-29T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("QIANKE_C_END_DB", str(old_db))
    monkeypatch.setenv("QIANKE_C_END_AVATAR_DIR", str(tmp_path / "avatars"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    monkeypatch.setattr(store, "_AVATAR_ROOT", None)

    store.init()
    columns = {
        row[1]
        for row in sqlite3.connect(str(old_db)).execute("PRAGMA table_info(c_companion)")
    }
    assert {"avatar_path", "user_avatar_path"} <= columns

    companion = store.get_companion("buyer_old")
    assert companion["name"] == "小鱼"
    assert companion["avatar_url"] == ""
    assert companion["user_avatar_url"] == ""

    saved = store.save_companion_avatar("buyer_old", "companion", PNG_1PX, "image/png")
    assert saved["avatar_url"]


# ---------------------------------------------------------------------------
# HTTP 接口
# ---------------------------------------------------------------------------


def test_http_upload_read_and_companion_payload(api):
    client, _holder, _tmp = api
    response = client.post(
        "/api/c/companion/avatar/companion",
        files={"file": ("avatar.png", PNG_1PX, "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["avatar_url"].startswith("/api/c/companion/avatar/companion?v=")
    assert payload["uploaded_avatar"]["bytes"] == len(PNG_1PX)

    avatar = client.get("/api/c/companion/avatar/companion")
    assert avatar.status_code == 200
    assert avatar.headers["content-type"] == "image/png"
    assert avatar.content == PNG_1PX
    assert "max-age" in avatar.headers.get("cache-control", "")

    companion = client.get("/api/c/companion")
    assert companion.status_code == 200
    assert companion.json()["avatar_url"] == payload["avatar_url"]
    assert companion.json()["user_avatar_url"] == ""


def test_http_user_and_companion_avatars_are_separate(api):
    client, _holder, _tmp = api
    client.post(
        "/api/c/companion/avatar/user",
        files={"file": ("me.webp", WEBP_1PX, "image/webp")},
    )
    companion = client.get("/api/c/companion").json()
    assert companion["user_avatar_url"].startswith("/api/c/companion/avatar/user?v=")
    assert companion["avatar_url"] == ""
    assert client.get("/api/c/companion/avatar/user").content == WEBP_1PX
    assert client.get("/api/c/companion/avatar/companion").status_code == 404


def test_http_cross_user_cannot_read_avatar(api):
    client, holder, _tmp = api
    _use_account(holder, 1)
    client.post(
        "/api/c/companion/avatar/companion",
        files={"file": ("avatar.png", PNG_1PX, "image/png")},
    )
    assert client.get("/api/c/companion/avatar/companion").status_code == 200

    _use_account(holder, 2)
    assert client.get("/api/c/companion/avatar/companion").status_code == 404
    assert client.get("/api/c/companion").json()["avatar_url"] == ""
    assert client.delete("/api/c/companion/avatar/companion").json()["avatar_url"] == ""

    # 买家 1 的头像不受买家 2 操作影响
    _use_account(holder, 1)
    assert client.get("/api/c/companion/avatar/companion").content == PNG_1PX


def test_http_restore_default(api):
    client, _holder, _tmp = api
    client.post(
        "/api/c/companion/avatar/companion",
        files={"file": ("avatar.png", PNG_1PX, "image/png")},
    )
    response = client.delete("/api/c/companion/avatar/companion")
    assert response.status_code == 200
    assert response.json()["avatar_url"] == ""
    assert client.get("/api/c/companion/avatar/companion").status_code == 404


def test_http_rejects_bad_type_size_and_kind(api):
    client, _holder, _tmp = api
    gif = client.post(
        "/api/c/companion/avatar/companion",
        files={"file": ("a.gif", b"GIF89a", "image/gif")},
    )
    assert gif.status_code == 400
    assert gif.json()["detail"]["code"] == "INVALID_AVATAR_TYPE"

    spoofed = client.post(
        "/api/c/companion/avatar/companion",
        files={"file": ("a.png", JPEG_1PX, "image/png")},
    )
    assert spoofed.status_code == 400
    assert spoofed.json()["detail"]["code"] == "INVALID_AVATAR_CONTENT"

    too_large = client.post(
        "/api/c/companion/avatar/companion",
        files={
            "file": (
                "big.png",
                b"\x89PNG\r\n\x1a\n" + b"0" * store.AVATAR_MAX_BYTES,
                "image/png",
            )
        },
    )
    assert too_large.status_code == 413
    assert too_large.json()["detail"]["code"] == "AVATAR_TOO_LARGE"

    bad_kind = client.post(
        "/api/c/companion/avatar/face",
        files={"file": ("a.png", PNG_1PX, "image/png")},
    )
    assert bad_kind.status_code == 400
    assert bad_kind.json()["detail"]["code"] == "INVALID_AVATAR_KIND"
    assert client.get("/api/c/companion").json()["avatar_url"] == ""


def test_http_requires_login(api):
    client, holder, _tmp = api
    holder["account"] = None

    assert client.get("/api/c/companion/avatar/companion").status_code == 401
    assert client.post(
        "/api/c/companion/avatar/companion",
        files={"file": ("a.png", PNG_1PX, "image/png")},
    ).status_code == 401
    assert client.delete("/api/c/companion/avatar/companion").status_code == 401
