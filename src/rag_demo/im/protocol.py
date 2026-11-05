"""Qianke IM Protocol v0：帧编解码、校验与降级。

协议层边界（见 ``docs/design/im-protocol-v0.md``）：

- 只处理 JSON 帧，**不 import** ``rag_demo.store`` / ``rag_demo.agent`` / ``rag_demo.auth``；
- 只做结构校验、限额、消息段归一化与纯文本降级；
- 业务语义（会话权限、订单草稿、Agent 唤醒）由上层服务决定。

错误一律抛 :class:`ProtocolError`（结构化 ``code``），调用方禁止用字符串匹配判断。
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import urlsplit

PROTOCOL_VERSION = 1

MAX_FRAME_BYTES = 64 * 1024
MAX_SEGMENTS = 32
MAX_TEXT_CHARS = 4000
MAX_CARD_BYTES = 4096
MAX_ID_CHARS = 128
MAX_NAME_CHARS = 64
MAX_TOKEN_CHARS = 512
MAX_META_BYTES = 4096

FRAME_TYPES = ("hello", "hello_ack", "event", "action", "response", "ping", "pong")

EVENTS = (
    "session.ready",
    "message.created",
    "message.read",
    "presence.changed",
    "conversation.updated",
    "system.notice",
)

ACTIONS = (
    "conversation.list",
    "conversation.sync",
    "message.history",
    "message.send",
    "message.read",
    "presence.update",
)

SEGMENT_TYPES = ("text", "at", "reply", "image", "business_card", "system_notice")
CARD_TYPES = ("product", "quote", "order_draft")
SENDER_KINDS = ("user", "agent")
PRESENCE_STATES = ("online", "away", "quiet", "sleeping")

_CARD_LABELS = {"product": "商品", "quote": "报价", "order_draft": "订单草稿"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FORBIDDEN_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "credential",
    "csrf",
    "cookie",
    "sessdata",
    "authorization",
)


class ProtocolError(Exception):
    """结构化协议错误；``code`` 供调用方判断，禁止字符串匹配。"""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


# ---------------------------------------------------------------------------
# 基础校验
# ---------------------------------------------------------------------------


def _as_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError("BAD_PARAMS", f"{name} 必须是对象")
    return dict(value)


def _as_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProtocolError("BAD_PARAMS", f"{name} 必须是数组")
    return value


def _as_str(
    value: Any,
    name: str,
    *,
    max_chars: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ProtocolError("BAD_PARAMS", f"{name} 必须是字符串")
    if len(value) > max_chars:
        raise ProtocolError("BAD_PARAMS", f"{name} 超过 {max_chars} 字符")
    if not allow_empty and not value.strip():
        raise ProtocolError("BAD_PARAMS", f"{name} 不能为空")
    return value


def _as_int(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError("BAD_PARAMS", f"{name} 必须是整数")
    if value < minimum:
        raise ProtocolError("BAD_PARAMS", f"{name} 不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise ProtocolError("BAD_PARAMS", f"{name} 不能大于 {maximum}")
    return value


def _as_id(value: Any, name: str) -> str:
    text = _as_str(value, name, max_chars=MAX_ID_CHARS)
    if not _ID_RE.match(text):
        raise ProtocolError("BAD_ID", f"{name} 格式不合法：{text!r}")
    return text


def _as_choice(value: Any, name: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ProtocolError("BAD_PARAMS", f"{name} 必须是 {choices} 之一")
    return value


# ---------------------------------------------------------------------------
# JSON 编解码
# ---------------------------------------------------------------------------


def _dump(frame: Mapping[str, Any]) -> str:
    try:
        return json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:  # pragma: no cover - 防御性分支
        raise ProtocolError("BAD_FRAME", f"帧无法序列化为 JSON：{exc}") from exc


def dumps(frame: Mapping[str, Any]) -> str:
    """序列化一帧，并检查 64 KiB 上限。"""
    text = _dump(frame)
    size = len(text.encode("utf-8"))
    if size > MAX_FRAME_BYTES:
        raise ProtocolError(
            "FRAME_TOO_LARGE",
            f"帧超过 {MAX_FRAME_BYTES} 字节",
            size=size,
        )
    return text


def loads(raw: str | bytes | bytearray | Mapping[str, Any]) -> dict[str, Any]:
    """解析一帧；只接受 UTF-8 JSON 对象。"""
    if isinstance(raw, Mapping):
        text = _dump(raw)
        if len(text.encode("utf-8")) > MAX_FRAME_BYTES:
            raise ProtocolError("FRAME_TOO_LARGE", f"帧超过 {MAX_FRAME_BYTES} 字节")
        return dict(raw)

    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_FRAME_BYTES:
            raise ProtocolError("FRAME_TOO_LARGE", f"帧超过 {MAX_FRAME_BYTES} 字节")
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("BAD_ENCODING", "帧必须是 UTF-8") from exc
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
            raise ProtocolError("FRAME_TOO_LARGE", f"帧超过 {MAX_FRAME_BYTES} 字节")
        text = raw
    else:
        raise ProtocolError("BAD_FRAME", "帧必须是 JSON 字符串或对象")

    try:
        frame = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("BAD_FRAME", f"JSON 解析失败：{exc.msg}") from exc
    if not isinstance(frame, dict):
        raise ProtocolError("BAD_FRAME", "帧必须是 JSON 对象")
    return frame


# ---------------------------------------------------------------------------
# 消息段
# ---------------------------------------------------------------------------


def _check_no_secrets(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            for part in _FORBIDDEN_KEY_PARTS:
                if part in lowered:
                    raise ProtocolError(
                        "CARD_SECRET_LEAK",
                        f"{path}.{key} 不允许出现在消息卡片里",
                    )
            _check_no_secrets(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_no_secrets(item, path=f"{path}[{index}]")


def _normalize_card(data: Mapping[str, Any], index: int) -> dict[str, Any]:
    path = f"segments[{index}].data"
    _check_no_secrets(data, path=path)

    card_type = _as_choice(data.get("card_type"), "card_type", CARD_TYPES)
    ref_id = _as_id(data.get("ref_id"), "ref_id")
    title = _as_str(data.get("title"), "title", max_chars=64)

    subtitle = data.get("subtitle")
    if subtitle is not None:
        subtitle = _as_str(subtitle, "subtitle", max_chars=200, allow_empty=True)

    amount = data.get("amount")
    if amount is not None:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
            raise ProtocolError("BAD_CARD", "amount 必须是非负数")
        amount = float(amount)

    fallback = data.get("fallback_text")
    if fallback is None:
        label = _CARD_LABELS[card_type]
        fallback = f"【{label}】{title}"
        if amount is not None:
            fallback += f" ¥{amount:.2f}"
    else:
        fallback = _as_str(fallback, "fallback_text", max_chars=MAX_TEXT_CHARS)

    card: dict[str, Any] = {
        "type": "business_card",
        "data": {
            "card_type": card_type,
            "ref_id": ref_id,
            "title": title,
            "fallback_text": fallback,
        },
    }
    if subtitle is not None:
        card["data"]["subtitle"] = subtitle
    if amount is not None:
        card["data"]["amount"] = amount

    size = len(_dump(card).encode("utf-8"))
    if size > MAX_CARD_BYTES:
        raise ProtocolError("BAD_CARD", f"business_card 超过 {MAX_CARD_BYTES} 字节")
    return card


def _normalize_segment(segment: Any, index: int) -> dict[str, Any]:
    if not isinstance(segment, Mapping):
        raise ProtocolError("BAD_SEGMENT", f"segments[{index}] 必须是对象")
    seg_type = segment.get("type")
    if not isinstance(seg_type, str) or not seg_type:
        raise ProtocolError("BAD_SEGMENT", f"segments[{index}].type 必须是字符串")
    data = segment.get("data") or {}
    data = _as_dict(data, f"segments[{index}].data")

    if seg_type == "text":
        raw_text = data.get("text")
        if isinstance(raw_text, str) and len(raw_text) > MAX_TEXT_CHARS:
            raise ProtocolError("TEXT_TOO_LONG", f"text 超过 {MAX_TEXT_CHARS} 字符")
        text = _as_str(raw_text, "text", max_chars=MAX_TEXT_CHARS)
        return {"type": "text", "data": {"text": text}}

    if seg_type == "at":
        user_id = _as_id(data.get("user_id"), "at.user_id")
        normalized: dict[str, Any] = {"user_id": user_id}
        name = data.get("name")
        if name is not None:
            normalized["name"] = _as_str(name, "at.name", max_chars=MAX_NAME_CHARS, allow_empty=True)
        return {"type": "at", "data": normalized}

    if seg_type == "reply":
        return {"type": "reply", "data": {"message_id": _as_id(data.get("message_id"), "reply.message_id")}}

    if seg_type == "image":
        url = data.get("url")
        file_id = data.get("file_id")
        if not url and not file_id:
            raise ProtocolError("BAD_SEGMENT", "image 需要 url 或 file_id")
        normalized = {"type": "image", "data": {}}
        if url:
            url = _as_str(url, "image.url", max_chars=1024)
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ProtocolError("BAD_SEGMENT", "image.url 必须是 http/https")
            normalized["data"]["url"] = url
        if file_id:
            normalized["data"]["file_id"] = _as_id(file_id, "image.file_id")
        alt = data.get("alt")
        if alt is not None:
            normalized["data"]["alt"] = _as_str(alt, "image.alt", max_chars=200, allow_empty=True)
        return normalized

    if seg_type == "business_card":
        return _normalize_card(data, index)

    if seg_type == "system_notice":
        text = _as_str(data.get("text"), "system_notice.text", max_chars=MAX_TEXT_CHARS)
        return {"type": "system_notice", "data": {"text": text}}

    # 前向兼容：未知类型保留降级文本，旧端仍能显示。
    fallback = data.get("fallback_text") or data.get("text") or "[不支持的消息类型]"
    fallback = _as_str(fallback, f"segments[{index}].fallback_text", max_chars=MAX_TEXT_CHARS)
    return {"type": seg_type, "data": {"fallback_text": fallback}}


def normalize_segments(raw: Any) -> list[dict[str, Any]]:
    """校验并归一化消息段列表（至少 1 段，最多 32 段）。"""
    segments = _as_list(raw, "segments")
    if not segments:
        raise ProtocolError("EMPTY_MESSAGE", "segments 不能为空")
    if len(segments) > MAX_SEGMENTS:
        raise ProtocolError("TOO_MANY_SEGMENTS", f"segments 不能超过 {MAX_SEGMENTS} 段")
    return [_normalize_segment(segment, index) for index, segment in enumerate(segments)]


def render_text(segments: list[dict[str, Any]]) -> str:
    """把已归一化的消息段降级为纯文本（通知、日志、旧客户端、Agent 输入用）。"""
    parts: list[str] = []
    for segment in segments:
        seg_type = segment.get("type")
        data = segment.get("data") or {}
        if seg_type == "text":
            parts.append(str(data.get("text", "")))
        elif seg_type == "at":
            parts.append(f"@{data.get('name') or data.get('user_id', '')} ")
        elif seg_type == "reply":
            continue
        elif seg_type == "image":
            parts.append("[图片] ")
        elif seg_type == "business_card":
            parts.append(f"{data.get('fallback_text') or '[卡片]'} ")
        elif seg_type == "system_notice":
            parts.append(f"{data.get('text', '')} ")
        else:
            parts.append(f"{data.get('fallback_text') or '[不支持的消息类型]'} ")
    return "".join(parts).strip()


def from_legacy_content(content: str) -> list[dict[str, Any]]:
    """旧 ``c_message.content`` → v0 ``text`` 段。"""
    return normalize_segments([{"type": "text", "data": {"text": content}}])


def to_legacy_content(segments: Any) -> str:
    """v0 消息段 → 旧 ``c_message.content``（纯文本）。"""
    return render_text(normalize_segments(segments))


# ---------------------------------------------------------------------------
# 消息 / 事件
# ---------------------------------------------------------------------------


def _validate_meta(value: Any) -> dict[str, Any]:
    meta = _as_dict(value, "meta")
    if len(_dump(meta).encode("utf-8")) > MAX_META_BYTES:
        raise ProtocolError("BAD_PARAMS", f"meta 超过 {MAX_META_BYTES} 字节")
    return meta


def _validate_sender(value: Any) -> dict[str, str]:
    sender = _as_dict(value, "sender")
    kind = _as_choice(sender.get("kind"), "sender.kind", SENDER_KINDS)
    return {"kind": kind, "id": _as_id(sender.get("id"), "sender.id")}


def validate_message(value: Any) -> dict[str, Any]:
    message = _as_dict(value, "message")
    result: dict[str, Any] = {
        "message_id": _as_id(message.get("message_id"), "message_id"),
        "conversation_id": _as_id(message.get("conversation_id"), "conversation_id"),
        "seq": _as_int(message.get("seq"), "seq", minimum=1),
        "sender": _validate_sender(message.get("sender")),
        "segments": normalize_segments(message.get("segments")),
    }
    if message.get("client_msg_id") is not None:
        result["client_msg_id"] = _as_id(message["client_msg_id"], "client_msg_id")
    if message.get("meta") is not None:
        result["meta"] = _validate_meta(message["meta"])
    if message.get("created_at") is not None:
        result["created_at"] = _as_str(
            message["created_at"], "created_at", max_chars=40, allow_empty=True
        )
    return result


def validate_event(frame: Mapping[str, Any]) -> dict[str, Any]:
    event = frame.get("event")
    if not isinstance(event, str) or event not in EVENTS:
        raise ProtocolError("UNKNOWN_EVENT", f"未知 event：{event!r}")
    seq = _as_int(frame.get("seq"), "seq", minimum=0)
    data = _as_dict(frame.get("data", {}), "data")

    if event == "message.created":
        payload: dict[str, Any] = {"message": validate_message(data.get("message"))}
    elif event == "message.read":
        payload = {
            "conversation_id": _as_id(data.get("conversation_id"), "conversation_id"),
            "user_id": _as_id(data.get("user_id"), "user_id"),
            "seq": _as_int(data.get("seq"), "seq", minimum=0),
        }
    elif event == "presence.changed":
        payload = {
            "user_id": _as_id(data.get("user_id"), "user_id"),
            "state": _as_choice(data.get("state"), "state", PRESENCE_STATES),
        }
    elif event == "conversation.updated":
        payload = {
            "conversation_id": _as_id(data.get("conversation_id"), "conversation_id"),
            "last_seq": _as_int(data.get("last_seq"), "last_seq", minimum=0),
        }
        if data.get("last_message_id") is not None:
            payload["last_message_id"] = _as_id(data["last_message_id"], "last_message_id")
    elif event == "session.ready":
        payload = {
            "user_id": _as_id(data.get("user_id"), "user_id"),
            "session_id": _as_id(data.get("session_id"), "session_id"),
        }
    else:  # system.notice
        payload = {
            "level": _as_choice(data.get("level"), "level", ("info", "warn", "error")),
            "text": _as_str(data.get("text"), "text", max_chars=500),
        }

    return {"type": "event", "event": event, "seq": seq, "data": payload}


# ---------------------------------------------------------------------------
# 动作
# ---------------------------------------------------------------------------


def _validate_message_send(params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "conversation_id": _as_id(params.get("conversation_id"), "conversation_id"),
        "client_msg_id": _as_id(params.get("client_msg_id"), "client_msg_id"),
        "segments": normalize_segments(params.get("segments")),
    }
    if params.get("meta") is not None:
        result["meta"] = _validate_meta(params["meta"])
    return result


def _validate_conversation_sync(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": _as_id(params.get("conversation_id"), "conversation_id"),
        "after_seq": _as_int(params.get("after_seq"), "after_seq", minimum=0),
    }


def _validate_message_history(params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "conversation_id": _as_id(params.get("conversation_id"), "conversation_id"),
        "limit": _as_int(params.get("limit", 50), "limit", minimum=1, maximum=100),
    }
    if params.get("before_seq") is not None:
        result["before_seq"] = _as_int(params["before_seq"], "before_seq", minimum=0)
    return result


def _validate_message_read(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": _as_id(params.get("conversation_id"), "conversation_id"),
        "seq": _as_int(params.get("seq"), "seq", minimum=0),
    }


def _validate_presence_update(params: dict[str, Any]) -> dict[str, Any]:
    return {"state": _as_choice(params.get("state"), "state", PRESENCE_STATES)}


def _validate_empty(params: dict[str, Any]) -> dict[str, Any]:
    if params:
        raise ProtocolError("BAD_PARAMS", "该动作不接受参数")
    return {}


_ACTION_VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "conversation.list": _validate_empty,
    "conversation.sync": _validate_conversation_sync,
    "message.history": _validate_message_history,
    "message.send": _validate_message_send,
    "message.read": _validate_message_read,
    "presence.update": _validate_presence_update,
}


def validate_action(frame: Mapping[str, Any]) -> dict[str, Any]:
    action = frame.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise ProtocolError("UNKNOWN_ACTION", f"未知 action：{action!r}")
    params = _as_dict(frame.get("params", {}), "params")
    result: dict[str, Any] = {
        "type": "action",
        "action": action,
        "params": _ACTION_VALIDATORS[action](params),
    }
    echo = frame.get("echo")
    if echo is not None:
        result["echo"] = _as_str(echo, "echo", max_chars=MAX_ID_CHARS)
    return result


# ---------------------------------------------------------------------------
# 握手 / 响应 / 保活
# ---------------------------------------------------------------------------


def validate_hello(frame: Mapping[str, Any]) -> dict[str, Any]:
    version = _as_int(frame.get("protocol_version"), "protocol_version", minimum=1, maximum=1000)
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            "PROTOCOL_VERSION_UNSUPPORTED",
            f"协议版本 {version} 不支持",
            supported=[PROTOCOL_VERSION],
        )
    result: dict[str, Any] = {
        "type": "hello",
        "protocol_version": version,
        "device_id": _as_id(frame.get("device_id"), "device_id"),
    }
    if frame.get("token") is not None:
        result["token"] = _as_str(
            frame["token"], "token", max_chars=MAX_TOKEN_CHARS, allow_empty=True
        )
    return result


def validate_hello_ack(frame: Mapping[str, Any]) -> dict[str, Any]:
    version = _as_int(frame.get("protocol_version"), "protocol_version", minimum=1, maximum=1000)
    if version != PROTOCOL_VERSION:
        raise ProtocolError("PROTOCOL_VERSION_UNSUPPORTED", f"协议版本 {version} 不支持")
    result: dict[str, Any] = {
        "type": "hello_ack",
        "protocol_version": version,
        "user_id": _as_id(frame.get("user_id"), "user_id"),
        "session_id": _as_id(frame.get("session_id"), "session_id"),
    }
    if frame.get("server_time") is not None:
        result["server_time"] = _as_str(
            frame["server_time"], "server_time", max_chars=40, allow_empty=True
        )
    return result


def validate_response(frame: Mapping[str, Any]) -> dict[str, Any]:
    status = frame.get("status")
    if status not in ("ok", "error"):
        raise ProtocolError("BAD_RESPONSE", "status 必须是 ok 或 error")
    result: dict[str, Any] = {"type": "response", "status": status}
    echo = frame.get("echo")
    if echo is not None:
        result["echo"] = _as_str(echo, "echo", max_chars=MAX_ID_CHARS)
    if status == "ok":
        result["data"] = _as_dict(frame.get("data", {}), "data")
    else:
        error = _as_dict(frame.get("error"), "error")
        result["error"] = {
            "code": _as_str(error.get("code"), "error.code", max_chars=64),
            "message": _as_str(error.get("message"), "error.message", max_chars=500, allow_empty=True),
        }
    return result


def _validate_keepalive(frame: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": frame["type"]}


_FRAME_VALIDATORS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "hello": validate_hello,
    "hello_ack": validate_hello_ack,
    "event": validate_event,
    "action": validate_action,
    "response": validate_response,
    "ping": _validate_keepalive,
    "pong": _validate_keepalive,
}


def validate_frame(frame: Mapping[str, Any]) -> dict[str, Any]:
    """校验任意帧，返回归一化副本。"""
    frame = _as_dict(frame, "frame")
    frame_type = frame.get("type")
    if not isinstance(frame_type, str):
        raise ProtocolError("BAD_FRAME", "缺少 type 字段")
    if frame_type not in FRAME_TYPES:
        raise ProtocolError("UNKNOWN_FRAME_TYPE", f"未知帧类型：{frame_type!r}")
    return _FRAME_VALIDATORS[frame_type](frame)


def parse_frame(raw: str | bytes | bytearray | Mapping[str, Any]) -> dict[str, Any]:
    """解析 + 校验一帧。"""
    return validate_frame(loads(raw))


# ---------------------------------------------------------------------------
# 构造器（自动校验，便于服务端/测试使用）
# ---------------------------------------------------------------------------


def new_id(prefix: str) -> str:
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,15}", prefix):
        raise ProtocolError("BAD_PARAMS", "prefix 必须是字母开头的短标识")
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def new_echo() -> str:
    return f"e_{uuid.uuid4().hex[:16]}"


def next_seq(last_seq: int) -> int:
    """会话内下一个 seq（服务端用；seq 从 1 开始）。"""
    return _as_int(last_seq, "last_seq", minimum=0) + 1


def make_hello(*, device_id: str, token: str | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION,
        "device_id": device_id,
    }
    if token is not None:
        frame["token"] = token
    return validate_hello(frame)


def make_hello_ack(
    *,
    user_id: str,
    session_id: str,
    server_time: str | None = None,
) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "type": "hello_ack",
        "protocol_version": PROTOCOL_VERSION,
        "user_id": user_id,
        "session_id": session_id,
    }
    if server_time is not None:
        frame["server_time"] = server_time
    return validate_hello_ack(frame)


def make_event(event: str, *, seq: int, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return validate_event({"type": "event", "event": event, "seq": seq, "data": data or {}})


def make_action(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    echo: str | None = None,
) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "action", "action": action, "params": params or {}}
    if echo is not None:
        frame["echo"] = echo
    return validate_action(frame)


def make_response(echo: str | None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "response", "status": "ok", "data": data or {}}
    if echo is not None:
        frame["echo"] = echo
    return validate_response(frame)


def make_error_response(
    echo: str | None,
    code: str,
    message: str,
) -> dict[str, Any]:
    text = _as_str(code, "code", max_chars=64)
    detail = _as_str(message, "message", max_chars=500, allow_empty=True)
    frame: dict[str, Any] = {
        "type": "response",
        "status": "error",
        "error": {"code": text, "message": detail},
    }
    if echo is not None:
        frame["echo"] = _as_str(echo, "echo", max_chars=MAX_ID_CHARS)
    return validate_response(frame)


def make_ping() -> dict[str, Any]:
    return {"type": "ping"}


def make_pong() -> dict[str, Any]:
    return {"type": "pong"}


__all__ = [
    "PROTOCOL_VERSION",
    "MAX_FRAME_BYTES",
    "MAX_SEGMENTS",
    "MAX_TEXT_CHARS",
    "MAX_CARD_BYTES",
    "FRAME_TYPES",
    "EVENTS",
    "ACTIONS",
    "SEGMENT_TYPES",
    "CARD_TYPES",
    "SENDER_KINDS",
    "PRESENCE_STATES",
    "ProtocolError",
    "dumps",
    "loads",
    "parse_frame",
    "validate_frame",
    "validate_action",
    "validate_event",
    "validate_message",
    "validate_response",
    "normalize_segments",
    "render_text",
    "from_legacy_content",
    "to_legacy_content",
    "new_id",
    "new_echo",
    "next_seq",
    "make_hello",
    "make_hello_ack",
    "make_event",
    "make_action",
    "make_response",
    "make_error_response",
    "make_ping",
    "make_pong",
]
