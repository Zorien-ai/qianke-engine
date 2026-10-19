# -*- coding: utf-8 -*-
"""营销文案数字护栏：文档没有的金额/折扣/有效期必须被拦截。"""
from rag_demo import marketing


def _docs(text: str, source: str = "black_card_sop.md"):
    return [{"source": source, "text": text}]


def test_extract_facts_reads_coupon_and_validity():
    facts = marketing.extract_facts(
        _docs("黑卡召回：100 元无门槛券，有效期 7 天，每月最多 1 次。\n普通：50 元券。")
    )
    tokens = {f["token"] for f in facts}
    assert {"100元", "50元", "7天"}.issubset(tokens)
    assert all(f["source"] == "black_card_sop.md" for f in facts)


def test_validate_variants_rejects_document_external_amount():
    facts = marketing.extract_facts(_docs("黑卡召回：100 元无门槛券，有效期 7 天。"))
    valid, rejected = marketing.validate_variants(
        [
            {"style": "warm", "sms": "尊贵的黑卡会员，送您100元无门槛券，7天内有效。", "basis": "SOP"},
            {"style": "urgent", "sms": "尊贵的黑卡会员，送您200元无门槛券，3天内有效。", "basis": "编造"},
        ],
        facts,
        "尊贵的黑卡会员",
    )
    assert len(valid) == 1
    assert valid[0]["sms"].startswith("尊贵的黑卡会员")
    assert len(rejected) == 1
    assert "200元" in rejected[0]["bad_tokens"]
    assert "3天" in rejected[0]["bad_tokens"]


def test_validate_variants_rejects_all_numbers_when_docs_have_no_offer():
    valid, rejected = marketing.validate_variants(
        [{"style": "warm", "sms": "尊贵的黑卡会员，送您100元券。", "basis": ""}],
        [],
        "尊贵的黑卡会员",
    )
    assert valid == []
    assert rejected and "100元" in rejected[0]["bad_tokens"]


def test_fallback_contains_three_styles_and_no_hard_numbers():
    # 直接调用内部兜底逻辑，确保降级时不会偷偷写金额
    fallback = marketing._fallback_variants("尊贵的黑卡会员", ["美妆"])
    assert [v["style"] for v in fallback] == ["warm", "urgent", "exclusive"]
    joined = " ".join(v["sms"] for v in fallback)
    assert "元" not in joined
    assert "折" not in joined
    assert "尊贵的黑卡会员" in joined
