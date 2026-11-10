"""企业微信原生回调：签名校验 + AES 解密/加密 + XML 解析。

协议参考企业微信「接收消息与事件」：
- msg_signature = sha1(sort(token, timestamp, nonce, encrypt))
- AESKey = Base64Decode(EncodingAESKey + "=")，32 字节
- 明文 = random(16) + msg_len(4, network order) + msg + receive_id
- PKCS#7 补位块长 32
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import xml.etree.ElementTree as ET
from typing import Any

from Crypto.Cipher import AES  # type: ignore[import-untyped]

WECOM_TOKEN_ENV = "QIANKE_WECOM_TOKEN"
WECOM_AES_KEY_ENV = "QIANKE_WECOM_AES_KEY"
WECOM_CORP_ID_ENV = "QIANKE_WECOM_CORP_ID"


class WeComCryptoError(Exception):
    pass


def config_from_env() -> tuple[str, str, str]:
    return (
        (os.environ.get(WECOM_TOKEN_ENV) or "").strip(),
        (os.environ.get(WECOM_AES_KEY_ENV) or "").strip(),
        (os.environ.get(WECOM_CORP_ID_ENV) or "").strip(),
    )


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, receive_id: str = ""):
        if not token or not encoding_aes_key:
            raise WeComCryptoError("企业微信 token / EncodingAESKey 未配置")
        try:
            self.key = base64.b64decode(encoding_aes_key + "=")
        except Exception as exc:  # noqa: BLE001
            raise WeComCryptoError("EncodingAESKey 不是合法 Base64") from exc
        if len(self.key) != 32:
            raise WeComCryptoError("EncodingAESKey 解码后必须为 32 字节")
        self.token = token
        self.receive_id = receive_id

    def signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        raw = "".join(sorted([self.token, str(timestamp), str(nonce), encrypt]))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        expected = self.signature(timestamp, nonce, encrypt)
        return hmac.compare_digest(expected, str(msg_signature or ""))

    def decrypt(self, encrypt: str) -> str:
        try:
            cipher = AES.new(self.key, AES.MODE_CBC, self.key[:16])
            plain = cipher.decrypt(base64.b64decode(encrypt))
            pad = plain[-1]
            if pad < 1 or pad > 32:
                raise WeComCryptoError("AES 补位非法")
            plain = plain[:-pad]
            msg_len = struct.unpack("!I", plain[16:20])[0]
            msg = plain[20:20 + msg_len]
            receive_id = plain[20 + msg_len:].decode("utf-8", errors="replace")
            # 企业微信「智能机器人」的回调 receive_id 可能为空，明文是机器人 ID；
            # 普通应用回调仍要求 receive_id 与 corpId 一致。空值不绕过签名/AES 校验。
            if self.receive_id and receive_id and receive_id != self.receive_id:
                raise WeComCryptoError("receive_id 不匹配")
            return msg.decode("utf-8")
        except WeComCryptoError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WeComCryptoError("企业微信消息解密失败") from exc

    def encrypt(self, message: str, timestamp: str = "0", nonce: str = "0") -> tuple[str, str]:
        raw = message.encode("utf-8")
        body = os.urandom(16) + struct.pack("!I", len(raw)) + raw + self.receive_id.encode("utf-8")
        pad = 32 - len(body) % 32
        body += bytes([pad]) * pad
        cipher = AES.new(self.key, AES.MODE_CBC, self.key[:16])
        encrypt = base64.b64encode(cipher.encrypt(body)).decode("utf-8")
        return encrypt, self.signature(timestamp, nonce, encrypt)

    def decrypt_xml(self, xml_text: str) -> str:
        try:
            root = ET.fromstring(xml_text)
            encrypt = root.findtext("Encrypt") or ""
        except ET.ParseError as exc:
            raise WeComCryptoError("企业微信 XML 解析失败") from exc
        if not encrypt:
            raise WeComCryptoError("企业微信 XML 缺少 Encrypt")
        return self.decrypt(encrypt)


def parse_message(xml_text: str) -> dict[str, Any]:
    """解析解密后的明文 XML；未知字段忽略。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise WeComCryptoError("企业微信明文 XML 解析失败") from exc
    return {child.tag: (child.text or "").strip() for child in root}


def message_to_event(message: dict[str, Any]) -> dict[str, Any] | None:
    """把企业微信文本/事件转成 Super-agent 通用事件。"""
    msg_type = str(message.get("MsgType") or "").lower()
    if msg_type == "text":
        content = str(message.get("Content") or "").strip()
        if not content:
            return None
        thread = (
            message.get("ChatId")
            or message.get("FromUserName")
            or message.get("ToUserName")
            or "wecom"
        )
        return {
            "source": "wecom",
            "channel": f"wecom:{msg_type}",
            "content": content,
            "thread_key": f"wecom:{thread}",
            "metadata": {
                "from_user": message.get("FromUserName"),
                "to_user": message.get("ToUserName"),
                "msg_id": message.get("MsgId"),
                "agent_id": message.get("AgentID"),
                "chat_id": message.get("ChatId"),
                "create_time": message.get("CreateTime"),
            },
        }
    return None
