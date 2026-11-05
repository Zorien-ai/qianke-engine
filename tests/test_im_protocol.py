"""Qianke IM Protocol v0 单测（P0）。

覆盖：帧编解码、限额、握手版本、动作/事件校验、消息段归一化与降级、
卡片密钥防泄漏、旧消息桥接、结构化错误码。
"""
from __future__ import annotations

import json

import pytest

from rag_demo.im import protocol
from rag_demo.im.protocol import ProtocolError


def _message(**overrides):
    message = {
        "message_id": "m_1",
        "conversation_id": "c_1",
        "seq": 1,
        "sender": {"kind": "user", "id": "u_1"},
        "segments": [{"type": "text", "data": {"text": "hi"}}],
    }
    message.update(overrides)
    return message


def _action(action, params=None, echo=None):
    frame = {"type": "action", "action": action, "params": params or {}}
    if echo is not None:
        frame["echo"] = echo
    return frame


def _event(event, data, seq=1):
    return {"type": "event", "event": event, "seq": seq, "data": data}


def _assert_code(exc: pytest.ExceptionInfo[ProtocolError], code: str) -> None:
    assert exc.value.code == code, f"期望 {code}，实际 {exc.value.code}: {exc.value.message}"


# ---------------------------------------------------------------------------
# 编解码与限额
# ---------------------------------------------------------------------------


def test_action_roundtrip():
    frame = protocol.make_action(
        "message.send",
        {
            "conversation_id": "c_1",
            "client_msg_id": "cm_1",
            "segments": [{"type": "text", "data": {"text": "在吗"}}],
        },
        echo="e_1",
    )
    parsed = protocol.parse_frame(protocol.dumps(frame))
    assert parsed == frame
    assert parsed["params"]["segments"][0]["data"]["text"] == "在吗"


def test_dumps_keeps_chinese_readable():
    text = protocol.dumps(protocol.make_ping())
    assert "\\u" not in text


def test_loads_rejects_bad_json():
    with pytest.raises(ProtocolError) as exc:
        protocol.parse_frame("{")
    _assert_code(exc, "BAD_FRAME")


def test_loads_rejects_non_object():
    with pytest.raises(ProtocolError) as exc:
        protocol.parse_frame("[1,2,3]")
    _assert_code(exc, "BAD_FRAME")


def test_loads_rejects_bad_utf8():
    with pytest.raises(ProtocolError) as exc:
        protocol.loads(b"\xff\xfe")
    _assert_code(exc, "BAD_ENCODING")


def test_frame_too_large():
    with pytest.raises(ProtocolError) as exc:
        protocol.dumps({"type": "ping", "pad": "x" * (protocol.MAX_FRAME_BYTES + 1)})
    _assert_code(exc, "FRAME_TOO_LARGE")


def test_unknown_frame_type():
    with pytest.raises(ProtocolError) as exc:
        protocol.parse_frame({"type": "wat"})
    _assert_code(exc, "UNKNOWN_FRAME_TYPE")


# ---------------------------------------------------------------------------
# 握手
# ---------------------------------------------------------------------------


def test_hello_ok():
    frame = protocol.make_hello(device_id="web_1", token="t")
    assert frame["protocol_version"] == protocol.PROTOCOL_VERSION
    assert protocol.parse_frame(frame) == frame


def test_hello_version_mismatch():
    with pytest.raises(ProtocolError) as exc:
        protocol.parse_frame(
            {"type": "hello", "protocol_version": 2, "device_id": "web_1"}
        )
    _assert_code(exc, "PROTOCOL_VERSION_UNSUPPORTED")
    assert exc.value.detail["supported"] == [protocol.PROTOCOL_VERSION]


def test_hello_ack_ok():
    frame = protocol.make_hello_ack(user_id="u_1", session_id="s_1")
    assert protocol.validate_frame(frame)["user_id"] == "u_1"


# ---------------------------------------------------------------------------
# 动作
# ---------------------------------------------------------------------------


def test_unknown_action():
    with pytest.raises(ProtocolError) as exc:
        protocol.validate_action(_action("message.delete"))
    _assert_code(exc, "UNKNOWN_ACTION")


def test_message_send_requires_conversation_and_segments():
    with pytest.raises(ProtocolError) as exc:
        protocol.validate_action(
            _action("message.send", {"client_msg_id": "cm_1", "segments": []})
        )
    _assert_code(exc, "BAD_PARAMS")


def test_empty_segments():
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments([])
    _assert_code(exc, "EMPTY_MESSAGE")


def test_too_many_segments():
    segments = [{"type": "text", "data": {"text": str(i)}} for i in range(33)]
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments(segments)
    _assert_code(exc, "TOO_MANY_SEGMENTS")


def test_text_too_long():
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments(
            [{"type": "text", "data": {"text": "x" * (protocol.MAX_TEXT_CHARS + 1)}}]
        )
    _assert_code(exc, "TEXT_TOO_LONG")


def test_message_history_default_limit():
    frame = protocol.make_action(
        "message.history", {"conversation_id": "c_1"}, echo="e_1"
    )
    assert frame["params"]["limit"] == 50


def test_message_history_limit_cap():
    with pytest.raises(ProtocolError) as exc:
        protocol.make_action("message.history", {"conversation_id": "c_1", "limit": 101})
    _assert_code(exc, "BAD_PARAMS")


def test_presence_state_choice():
    with pytest.raises(ProtocolError) as exc:
        protocol.make_action("presence.update", {"state": "sleeping!"})
    _assert_code(exc, "BAD_PARAMS")

    frame = protocol.make_action("presence.update", {"state": "sleeping"})
    assert frame["params"]["state"] == "sleeping"


def test_action_rejects_extra_params_for_list():
    with pytest.raises(ProtocolError) as exc:
        protocol.make_action("conversation.list", {"foo": 1})
    _assert_code(exc, "BAD_PARAMS")


def test_ids_reject_bad_format():
    with pytest.raises(ProtocolError) as exc:
        protocol.make_action(
            "message.send",
            {
                "conversation_id": "c 1",
                "client_msg_id": "cm_1",
                "segments": [{"type": "text", "data": {"text": "x"}}],
            },
        )
    _assert_code(exc, "BAD_ID")


# ---------------------------------------------------------------------------
# 消息段
# ---------------------------------------------------------------------------


def test_unknown_segment_degrades_to_fallback():
    segments = protocol.normalize_segments(
        [{"type": "sticker", "data": {"fallback_text": "[贴纸]"}}]
    )
    assert segments[0]["type"] == "sticker"
    assert protocol.render_text(segments) == "[贴纸]"


def test_render_text_order_and_labels():
    segments = protocol.normalize_segments(
        [
            {"type": "reply", "data": {"message_id": "m_0"}},
            {"type": "at", "data": {"user_id": "u_2", "name": "小鱼"}},
            {"type": "text", "data": {"text": "你好"}},
            {"type": "image", "data": {"file_id": "img_1"}},
        ]
    )
    assert protocol.render_text(segments) == "@小鱼 你好[图片]"


def test_at_requires_user_id():
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments([{"type": "at", "data": {"name": "小鱼"}}])
    _assert_code(exc, "BAD_PARAMS")


def test_image_requires_http_url_or_file_id():
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments(
            [{"type": "image", "data": {"url": "file:///C:/a.png"}}]
        )
    _assert_code(exc, "BAD_SEGMENT")

    ok = protocol.normalize_segments(
        [{"type": "image", "data": {"url": "https://example.com/a.png"}}]
    )
    assert ok[0]["data"]["url"] == "https://example.com/a.png"


def test_business_card_generates_fallback():
    card = protocol.normalize_segments(
        [
            {
                "type": "business_card",
                "data": {
                    "card_type": "quote",
                    "ref_id": "q_1",
                    "title": "冲锋衣优惠",
                    "amount": 299,
                },
            }
        ]
    )[0]
    assert card["data"]["fallback_text"] == "【报价】冲锋衣优惠 ¥299.00"


def test_business_card_rejects_secret_keys():
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments(
            [
                {
                    "type": "business_card",
                    "data": {
                        "card_type": "order_draft",
                        "ref_id": "d_1",
                        "title": "订单草稿",
                        "confirmation_token": "secret",
                    },
                }
            ]
        )
    _assert_code(exc, "CARD_SECRET_LEAK")


def test_business_card_rejects_nested_secret_keys():
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments(
            [
                {
                    "type": "business_card",
                    "data": {
                        "card_type": "product",
                        "ref_id": "p_1",
                        "title": "商品",
                        "extra": {"csrf": "x"},
                    },
                }
            ]
        )
    _assert_code(exc, "CARD_SECRET_LEAK")


def test_business_card_size_limit():
    with pytest.raises(ProtocolError) as exc:
        protocol.normalize_segments(
            [
                {
                    "type": "business_card",
                    "data": {
                        "card_type": "product",
                        "ref_id": "p_1",
                        "title": "商品",
                        "fallback_text": "x" * 4000,
                    },
                }
            ]
        )
    _assert_code(exc, "BAD_CARD")


# ---------------------------------------------------------------------------
# 事件 / 响应
# ---------------------------------------------------------------------------


def test_message_created_event_ok():
    frame = protocol.make_event(
        "message.created", seq=1, data={"message": _message()}
    )
    assert frame["data"]["message"]["segments"][0]["data"]["text"] == "hi"


def test_message_created_event_rejects_zero_seq():
    with pytest.raises(ProtocolError) as exc:
        protocol.make_event(
            "message.created", seq=1, data={"message": _message(seq=0)}
        )
    _assert_code(exc, "BAD_PARAMS")


def test_presence_changed_event():
    frame = protocol.make_event(
        "presence.changed", seq=2, data={"user_id": "u_1", "state": "quiet"}
    )
    assert frame["event"] == "presence.changed"


def test_system_notice_level():
    with pytest.raises(ProtocolError) as exc:
        protocol.make_event(
            "system.notice", seq=1, data={"level": "fatal", "text": "boom"}
        )
    _assert_code(exc, "BAD_PARAMS")


def test_response_error_roundtrip():
    frame = protocol.make_error_response("e_1", "RATE_LIMITED", "慢一点")
    parsed = protocol.parse_frame(json.dumps(frame))
    assert parsed["status"] == "error"
    assert parsed["error"]["code"] == "RATE_LIMITED"


def test_bad_response_status():
    with pytest.raises(ProtocolError) as exc:
        protocol.validate_response({"type": "response", "status": "done"})
    _assert_code(exc, "BAD_RESPONSE")


def test_ping_pong_roundtrip():
    assert protocol.parse_frame(protocol.dumps(protocol.make_ping())) == {"type": "ping"}
    assert protocol.parse_frame(protocol.dumps(protocol.make_pong())) == {"type": "pong"}


# ---------------------------------------------------------------------------
# 旧消息桥接 / 工具
# ---------------------------------------------------------------------------


def test_legacy_bridge_roundtrip():
    segments = protocol.from_legacy_content("周末去徒步吗")
    assert segments[0] == {"type": "text", "data": {"text": "周末去徒步吗"}}
    assert protocol.to_legacy_content(segments) == "周末去徒步吗"


def test_new_id_and_seq():
    assert protocol.new_id("m").startswith("m_")
    assert protocol.next_seq(0) == 1
    assert protocol.next_seq(41) == 42
    with pytest.raises(ProtocolError):
        protocol.next_seq(-1)


def test_protocol_error_to_dict():
    payload = ProtocolError("BAD_PARAMS", "x", field="segments").to_dict()
    assert payload == {
        "code": "BAD_PARAMS",
        "message": "x",
        "detail": {"field": "segments"},
    }
