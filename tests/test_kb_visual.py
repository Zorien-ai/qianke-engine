# -*- coding: utf-8 -*-
"""知识库可视化接口的纯逻辑：姓名脱敏、doc_id、分页边界。"""
from rag_demo.api import kb


def test_mask_profile_name_never_returns_full_name():
    text = "用户U1024（张三）：28岁女，上海人，钻石会员。"
    masked = kb.mask_profile_name(text)
    assert masked == "张**"
    assert "张三" not in (masked or "")


def test_mask_profile_name_missing_or_single_char():
    assert kb.mask_profile_name("没有姓名") is None
    assert kb.mask_profile_name("用户U1（张）") == "张**"


def test_doc_id_is_stable_and_url_safe():
    one = kb.doc_id_for("运营SOP.md")
    assert one == kb.doc_id_for("运营SOP.md")
    assert one != kb.doc_id_for("美妆指南.md")
    assert len(one) == 16
    assert all(c.isalnum() for c in one)


def test_normalize_page_clamps_size_and_page():
    assert kb.normalize_page(0, 0) == (1, 20)
    assert kb.normalize_page(2, 20) == (2, 20)
    assert kb.normalize_page(1, 999) == (1, 50)
