"""企业微信原生回调：签名、AES、XML、事件转换。"""
from __future__ import annotations

import base64
import os

import pytest

from rag_demo.superagent import wecom

TOKEN = "test-token"
AES_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")
CORP_ID = "ww_test_corp"


def _crypto() -> wecom.WeComCrypto:
    return wecom.WeComCrypto(TOKEN, AES_KEY, CORP_ID)


def test_encrypt_decrypt_and_signature():
    crypto = _crypto()
    encrypted, signature = crypto.encrypt("<xml><Content>订单退款</Content></xml>", timestamp="1", nonce="2")
    assert crypto.verify_signature(signature, "1", "2", encrypted) is True
    assert crypto.verify_signature("bad", "1", "2", encrypted) is False
    assert "订单退款" in crypto.decrypt(encrypted)


def test_url_verification_roundtrip():
    crypto = _crypto()
    encrypted, signature = crypto.encrypt("echo-123", timestamp="10", nonce="20")
    assert crypto.decrypt(encrypted) == "echo-123"
    assert crypto.verify_signature(signature, "10", "20", encrypted)


def test_wrong_corp_id_rejected():
    crypto = _crypto()
    encrypted, _ = crypto.encrypt("hello")
    wrong = wecom.WeComCrypto(TOKEN, AES_KEY, "ww_other")
    with pytest.raises(wecom.WeComCryptoError):
        wrong.decrypt(encrypted)


def test_parse_text_message_to_event():
    xml = (
        "<xml><ToUserName><![CDATA[ww_test_corp]]></ToUserName>"
        "<FromUserName><![CDATA[user_1]]></FromUserName>"
        "<CreateTime>123</CreateTime><MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[订单 order_abc 要退款]]></Content>"
        "<MsgId>MSG_1</MsgId><AgentID>100001</AgentID></xml>"
    )
    message = wecom.parse_message(xml)
    event = wecom.message_to_event(message)
    assert event is not None
    assert event["source"] == "wecom"
    assert event["thread_key"] == "wecom:user_1"
    assert "退款" in event["content"]
    assert event["metadata"]["msg_id"] == "MSG_1"


def test_non_text_message_ignored():
    xml = "<xml><MsgType>event</MsgType><Event>subscribe</Event></xml>"
    assert wecom.message_to_event(wecom.parse_message(xml)) is None


def test_env_config(monkeypatch):
    monkeypatch.setenv(wecom.WECOM_TOKEN_ENV, TOKEN)
    monkeypatch.setenv(wecom.WECOM_AES_KEY_ENV, AES_KEY)
    monkeypatch.setenv(wecom.WECOM_CORP_ID_ENV, CORP_ID)
    token, aes, corp = wecom.config_from_env()
    assert token == TOKEN
    assert aes == AES_KEY
    assert corp == CORP_ID
