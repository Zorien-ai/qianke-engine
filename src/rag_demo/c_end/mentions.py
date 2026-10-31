"""@ 提及的确定性解析与成员映射。

协议只保存 token / 目标成员，不把 @ 文本当权限。
"""
from __future__ import annotations

import re
from typing import Any

MEMBERS: dict[str, dict[str, str]] = {
    "@小鱼": {"target_id": "companion", "name": "小鱼", "kind": "companion", "thread_id": "companion"},
    "@店宠": {"target_id": "store_demo", "name": "山野店宠", "kind": "merchant", "thread_id": "store_demo"},
    "@小满": {"target_id": "friend_demo", "name": "小满", "kind": "friend", "thread_id": "friend_demo"},
    "@我": {"target_id": "me", "name": "我", "kind": "user", "thread_id": ""},
}

_PATTERN = re.compile(r"@(店宠|小鱼|小满|我)")


def extract_mentions(text: str | None) -> list[dict[str, str]]:
    """按出现顺序去重提取已知 @ 成员。"""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _PATTERN.finditer(text or ""):
        token = f"@{match.group(1)}"
        if token in seen:
            continue
        seen.add(token)
        member = MEMBERS[token]
        found.append({"token": token, **member})
    return found


def attach_metadata(metadata: dict[str, Any] | None, text: str | None) -> dict[str, Any]:
    """把 mentions 合并进消息 metadata；没有 @ 时不写空数组。"""
    meta = dict(metadata or {})
    found = extract_mentions(text)
    if found:
        meta["mentions"] = found
    return meta
