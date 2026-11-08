"""修改密码：旧密码校验、强度校验与会话吊销。"""
from __future__ import annotations

import uuid

import pytest

from rag_demo import auth

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("psycopg2"), reason="psycopg2 未安装"
)


def _pg_available() -> bool:
    try:
        auth._get_pool()
        return True
    except Exception:  # noqa: BLE001
        return False


if not _pg_available():
    pytestmark = pytest.mark.skip(reason="PostgreSQL 不可用")


def test_change_password_validates_and_revokes_sessions():
    username = f"cpw_{uuid.uuid4().hex[:10]}"
    user = auth.create_user(username, "OldPass123!", auth.ACCOUNT_ENTERPRISE, display_name="改密测试")
    try:
        token = auth.create_session(user["id"])
        assert auth.resolve_session(token) is not None

        with pytest.raises(ValueError):
            auth.change_password(user["id"], "wrong-password", "NewStrong123!")
        with pytest.raises(ValueError):
            auth.change_password(user["id"], "OldPass123!", "short")

        auth.change_password(user["id"], "OldPass123!", "NewStrong123!")
        updated = auth.find_user(username)
        assert updated is not None
        assert auth.verify_password("NewStrong123!", updated["password_hash"])
        assert not auth.verify_password("OldPass123!", updated["password_hash"])
        assert auth.resolve_session(token) is None
    finally:
        with auth._cursor() as cur:
            cur.execute("DELETE FROM app_user WHERE username = %s", (username,))
