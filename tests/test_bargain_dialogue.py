"""B 店宠 LLM 话术层：结构化输出、安全校验、模板回退。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rag_demo.c_end import bargain_dialogue


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))


def _offers():
    return [
        {
            "offer_id": "offer_auto",
            "payable": 188.1,
            "merchant_discount": 9.9,
            "approval_required": False,
        },
        {
            "offer_id": "offer_approval",
            "payable": 180.0,
            "merchant_discount": 18.0,
            "approval_required": True,
        },
    ]


def _generate(payload, *, monkeypatch, mode="hybrid"):
    monkeypatch.setenv("QIANKE_BARGAIN_DIALOGUE_MODE", mode)
    fallback = {
        "offer_id": "offer_approval",
        "payable": 180.0,
        "merchant_discount": 18.0,
        "approval_required": True,
    }
    return bargain_dialogue.generate_store_reply(
        store_name="山岚茶事",
        pet_name="山岚茶事店宠",
        items=[{"title": "明前龙井", "spec": "100g/罐", "quantity": 1, "price": 198.0}],
        list_total=198.0,
        platform_discount=0.0,
        target_price=180.0,
        current_offer={"offer_id": "offer_auto", "payable": 188.1},
        allowed_offers=_offers(),
        history=[],
        user_message="180 能卖吗",
        fallback_reply="这个价需要店长确认。",
        fallback_offer=fallback,
        llm=FakeLLM(payload),
    )


def test_llm_reply_valid_and_offer_selected(monkeypatch):
    result = _generate(
        {
            "reply_text": "180 我可以帮你申请，但得店长点头，要不要我提交？",
            "chosen_offer_id": "offer_approval",
            "stance": "OFFER",
        },
        monkeypatch=monkeypatch,
    )
    assert result.source == "llm"
    assert result.offer_id == "offer_approval"
    assert "店长" in result.text


def test_invalid_offer_falls_back(monkeypatch):
    result = _generate(
        {
            "reply_text": "可以。",
            "chosen_offer_id": "offer_invented",
            "stance": "OFFER",
        },
        monkeypatch=monkeypatch,
    )
    assert result.source == "fallback"
    assert result.offer_id == "offer_approval"
    assert result.reason == "invalid_offer"


def test_hallucinated_price_falls_back(monkeypatch):
    result = _generate(
        {
            "reply_text": "150 元也可以。",
            "chosen_offer_id": "offer_approval",
            "stance": "OFFER",
        },
        monkeypatch=monkeypatch,
    )
    assert result.source == "fallback"
    assert result.reason == "invalid_price_claim"


def test_forbidden_floor_term_falls_back(monkeypatch):
    result = _generate(
        {
            "reply_text": "这已经是底价了。",
            "chosen_offer_id": "offer_approval",
            "stance": "OFFER",
        },
        monkeypatch=monkeypatch,
    )
    assert result.source == "fallback"
    assert result.reason == "forbidden_term"


def test_approval_offer_cannot_promise(monkeypatch):
    result = _generate(
        {
            "reply_text": "保证成交，180 给你。",
            "chosen_offer_id": "offer_approval",
            "stance": "OFFER",
        },
        monkeypatch=monkeypatch,
    )
    assert result.source == "fallback"
    assert result.reason == "unapproved_promise"


def test_invalid_json_falls_back(monkeypatch):
    result = _generate("这不是 JSON", monkeypatch=monkeypatch)
    assert result.source == "fallback"
    assert result.reason == "invalid_json"


def test_template_mode_does_not_call_llm(monkeypatch):
    llm = FakeLLM({
        "reply_text": "180 可以。",
        "chosen_offer_id": "offer_approval",
        "stance": "OFFER",
    })
    result = _generate(
        {
            "reply_text": "180 可以。",
            "chosen_offer_id": "offer_approval",
            "stance": "OFFER",
        },
        monkeypatch=monkeypatch,
        mode="template",
    )
    assert result.source == "fallback"
    assert result.reason == "template_mode"
