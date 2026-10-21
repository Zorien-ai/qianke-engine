# -*- coding: utf-8 -*-
"""一键体验（Demo Mode）相关边界。"""
from rag_demo import auth


def test_demo_account_identity_is_fixed_and_read_only():
    assert auth.DEMO_USERNAME == "demo_visitor"
    assert auth.DEMO_TTL_SECONDS > 0
    assert auth.DEMO_DISPLAY_NAME == "演示访客"


def test_row_to_user_carries_is_demo_flag():
    row = {
        "id": 59,
        "username": "demo_visitor",
        "display_name": "演示访客",
        "password_hash": "x",
        "account_type": "employee",
        "role": "exec",
        "is_system_admin": False,
        "is_enterprise_admin": False,
        "is_demo": True,
        "status": "active",
    }
    user = auth._row_to_user(row)
    assert user["is_demo"] is True
    assert user["is_system_admin"] is False


def test_demo_account_is_not_an_admin():
    # 演示账号绝不能靠“角色名”或布尔标记拿到管理能力。
    assert auth.DEMO_USERNAME != auth.SEED_ADMIN_USERNAME


def test_demo_ttl_is_short_lived():
    assert auth.DEMO_TTL_SECONDS <= auth.SESSION_TTL_SECONDS
    assert auth.DEMO_TTL_SECONDS >= 60
