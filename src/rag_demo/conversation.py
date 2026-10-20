# -*- coding: utf-8 -*-
"""多轮追问改写：把「那女性呢 / 他们呢 / 继续」改写成独立问题。

设计原则：
- 只有在有历史且问题看起来像追问时才调用 LLM；
- 改写失败永远回退原问题，不阻断主链路；
- 改写调用单独记录 span 与 token（feature=query_rewrite）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from rag_demo import ai_monitor

logger = logging.getLogger(__name__)

# 指代 / 延续词：这些问题离开历史通常无法独立成立
_FOLLOWUP_RE = re.compile(
    r"(那|这个|那个|这些|那些|他们|她们|它们|上述|上面|前面|其中|还有|继续|接着|再|换成|改成|呢|吗|么)"
)


def _compact_history(history: list[dict], max_turns: int = 6, max_chars: int = 1600) -> str:
    lines = []
    used = 0
    for item in history[-max_turns:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = " ".join(str(item.get("content") or "").split())
        if not content:
            continue
        content = content[:500]
        line = f"{role}：{content}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def should_rewrite(question: str, history: list[dict]) -> bool:
    if not history:
        return False
    q = (question or "").strip()
    if not q:
        return False
    # 纯问候不触发
    if re.fullmatch(r"(你好|您好|hi|hello|在吗|谢谢|好的|ok)[!！。.？?]*", q, re.I):
        return False
    if len(q) <= 30 and _FOLLOWUP_RE.search(q):
        return True
    if len(q) <= 12 and not re.search(r"\d", q):
        return True
    return False


def _parse_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def rewrite_followup(question: str, history: list[dict]) -> dict:
    """返回 {"question": 用于检索的问题, "rewritten": bool, "original": ...}。"""
    original = (question or "").strip()
    if not should_rewrite(original, history):
        return {"question": original, "rewritten": False, "reason": "skip"}

    from rag_demo.generation.generator import chat_completion
    from rag_demo.prompts import QUERY_REWRITE_PROMPT

    prompt = QUERY_REWRITE_PROMPT.format(
        history=_compact_history(history),
        question=original,
    )
    started = time.perf_counter()
    try:
        resp = chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=180,
            deep_thinking=False,
            feature="query_rewrite",
        )
        text = (resp.choices[0].message.content or "") if getattr(resp, "choices", None) else ""
        data = _parse_json(text)
        standalone = str((data or {}).get("standalone_question") or "").strip()
        standalone = " ".join(standalone.split())
        if not standalone or len(standalone) > 300:
            return {"question": original, "rewritten": False, "reason": "invalid_output"}
        return {
            "question": standalone,
            "rewritten": standalone != original,
            "original": original,
            "reason": "ok",
        }
    except Exception as exc:  # noqa: BLE001 改写失败必须回退，不能阻断问答
        logger.warning("追问改写失败，回退原问题: %s: %s", type(exc).__name__, exc)
        return {"question": original, "rewritten": False, "reason": "error"}
    finally:
        ai_monitor.record_span(
            kind="rewrite",
            name="query_rewrite",
            latency_ms=round((time.perf_counter() - started) * 1000),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        )
