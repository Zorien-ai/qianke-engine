# -*- coding: utf-8 -*-
"""中英文切换资源的基本完整性检查。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "src"
STATIC = ROOT / "src" / "rag_demo" / "api" / "static"


def test_ui_dictionary_covers_core_shell_labels():
    data = json.loads((WEB / "i18n-en.json").read_text(encoding="utf-8"))
    for key in ("工作台", "对话", "知识库", "员工管理", "离线评测", "退出登录", "数据状态"):
        assert data.get(key), f"缺少翻译: {key}"


def test_login_dictionary_covers_auth_labels():
    data = json.loads((STATIC / "login-en.json").read_text(encoding="utf-8"))
    for key in ("登录", "注册", "账号", "密码", "千客引擎"):
        assert data.get(key), f"缺少登录页翻译: {key}"


def test_default_locale_is_chinese_and_toggle_is_persisted():
    source = (WEB / "i18n.js").read_text(encoding="utf-8")
    assert 'locale = ref("zh")' in source
    assert 'localStorage.setItem(LOCALE_KEY' in source
    assert "toggleLocale" in source
