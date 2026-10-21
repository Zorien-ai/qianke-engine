# -*- coding: utf-8 -*-
"""混合记忆：短期全量 + 长期摘要 + 业务实体状态。

短期：最近 6 轮（12 条）完整消息，直接进 System Prompt / 改写 Prompt。
长期：超过 6 轮后，后台 LLM 将旧对话压成 <=100 字摘要。
实体：每轮结束后后台提取当前锁定的业务条件（城市 / 会员等级 / 品类等），
      存进 chat_sessions.context_state，供下一次追问改写与生成使用。

后台更新不阻塞回答；失败只降级，不影响本轮问答。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone

from rag_demo import ai_monitor, chat_history

logger = logging.getLogger(__name__)

SHORT_TERM_MESSAGES = 12  # 6 轮完整消息
SUMMARY_MAX_CHARS = 100
_UPDATE_LOCKS: set[str] = set()
_UPDATE_LOCK = threading.Lock()


def load_memory(tenant_id: str, account_id: int, session_id: str) -> dict:
    state = chat_history.get_context_state(tenant_id, account_id, session_id)
    summary = state.get("summary") if isinstance(state.get("summary"), str) else ""
    entities = state.get("entities") if isinstance(state.get("entities"), dict) else {}
    return {"summary": summary, "entities": _clean_entities(entities)}


def short_term(messages: list[dict]) -> list[dict]:
    return list(messages or [])[-SHORT_TERM_MESSAGES:]


def _clean_entities(raw: dict) -> dict:
    out = {}
    for key, value in (raw or {}).items():
        key = str(key).strip()[:30]
        if not key or key in {"summary", "updated_at", "summary_upto"}:
            continue
        text = " ".join(str(value or "").split())[:80]
        if text:
            out[key] = text
    return out


def _memory_text(memory: dict) -> str:
    summary = (memory or {}).get("summary") or ""
    entities = _clean_entities((memory or {}).get("entities") or {})
    parts = []
    if summary:
        parts.append(f"历史对话摘要：{summary}")
    if entities:
        parts.append("已锁定的业务条件：" + "；".join(f"{k}={v}" for k, v in entities.items()))
    return "\n".join(parts)


def system_prompt(memory: dict, history: list[dict]) -> str:
    """构造生成阶段的 System Prompt：摘要 + 实体 + 最近 6 轮完整对话。"""
    memory_text = _memory_text(memory)
    recent = short_term(history)
    lines = [
        "你在进行一段连续对话。下面是会话记忆，只用于理解指代和保持业务条件一致，"
        "不得把历史对话当成新的知识库事实；回答事实仍必须以本轮检索资料为准。",
    ]
    if memory_text:
        lines.append(memory_text)
    if recent:
        lines.append("【最近对话】")
        for item in recent:
            role = "用户" if item.get("role") == "user" else "助手"
            content = " ".join(str(item.get("content") or "").split())[:500]
            if content:
                lines.append(f"{role}：{content}")
    return "\n".join(lines)


def rewrite_prompt_context(memory: dict, history: list[dict]) -> str:
    """改写追问时注入的记忆上下文（摘要 + 实体 + 最近对话）。"""
    base = _memory_text(memory)
    lines = []
    if base:
        lines.append(base)
    for item in short_term(history):
        role = "用户" if item.get("role") == "user" else "助手"
        content = " ".join(str(item.get("content") or "").split())[:300]
        if content:
            lines.append(f"{role}：{content}")
    return "\n".join(lines)


def _parse_json(text: str) -> dict | None:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _transcript(messages: list[dict], limit: int = 16) -> str:
    lines = []
    for item in messages[-limit:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = " ".join(str(item.get("content") or "").split())
        if content:
            lines.append(f"{role}：{content[:500]}")
    return "\n".join(lines)


def update_memory(tenant_id: str, account_id: int, session_id: str) -> None:
    """后台更新摘要与实体状态。调用方应放在 daemon thread。"""
    try:
        messages = chat_history.get_messages(tenant_id, account_id, session_id, limit=200)
        if not messages:
            return
        memory = load_memory(tenant_id, account_id, session_id)
        recent = short_term(messages)
        older = messages[:-SHORT_TERM_MESSAGES] if len(messages) > SHORT_TERM_MESSAGES else []
        if not older and not recent:
            return
        from rag_demo.generation.generator import chat_completion
        from rag_demo.prompts import CONVERSATION_MEMORY_PROMPT

        prompt = CONVERSATION_MEMORY_PROMPT.format(
            summary=memory.get("summary") or "（暂无）",
            entities=json.dumps(memory.get("entities") or {}, ensure_ascii=False),
            older=_transcript(older) or "（暂无更早对话）",
            recent=_transcript(recent),
        )
        # 后台线程不是请求线程：先 pin 数据集，确保 token 记账归到正确租户。
        try:
            from rag_demo.db.connection import pin_dataset

            pin_dataset(tenant_id)
        except Exception:  # noqa: BLE001
            pass
        resp = chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=300,
            deep_thinking=False,
            feature="memory",
        )
        text = (resp.choices[0].message.content or "") if getattr(resp, "choices", None) else ""
        data = _parse_json(text) or {}
        summary = " ".join(str(data.get("summary") or "").split())[:SUMMARY_MAX_CHARS]
        entities = _clean_entities({**(memory.get("entities") or {}), **(data.get("entities") or {})})
        if not summary:
            summary = memory.get("summary") or ""
        state = {
            "summary": summary,
            "entities": entities,
            "summary_upto": older[-1]["id"] if older else memory.get("summary_upto"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        chat_history.update_context_state(tenant_id, account_id, session_id, state)
        ai_monitor.record_span(kind="memory", name="update_memory", latency_ms=0)
    except Exception as exc:  # noqa: BLE001 记忆更新失败不能影响主链路
        logger.warning("会话记忆更新失败（忽略） session=%s: %s: %s", session_id, type(exc).__name__, exc)


def schedule_update(tenant_id: str, account_id: int, session_id: str) -> None:
    """每轮回答落库后异步更新记忆；同一会话同一时刻只跑一个更新。"""
    if not session_id:
        return
    with _UPDATE_LOCK:
        if session_id in _UPDATE_LOCKS:
            return
        _UPDATE_LOCKS.add(session_id)

    def run():
        try:
            update_memory(tenant_id, account_id, session_id)
        finally:
            with _UPDATE_LOCK:
                _UPDATE_LOCKS.discard(session_id)

    threading.Thread(target=run, daemon=True, name=f"chat-memory-{session_id[:8]}").start()
