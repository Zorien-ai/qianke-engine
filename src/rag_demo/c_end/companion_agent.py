"""C 端守护伙伴：只做辅助传达和锐评，不参与砍价/下单。

人格与输出检查统一走 `c_end.persona`，避免两个入口的人设漂移。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from rag_demo.c_end import persona as c_persona
from rag_demo.c_end import store

logger = logging.getLogger(__name__)

FALLBACK = c_persona.DEFAULT_FALLBACK

# 供测试与外部引用；运行时按伙伴字段重新生成，保证名字/昵称可配置。
SYSTEM_PROMPT = c_persona.build_persona_prompt(mode="commentary")


def _system_prompt(companion: dict[str, Any]) -> str:
    return c_persona.build_persona_prompt(
        name=companion.get("name"),
        user_nickname=companion.get("user_nickname"),
        species=companion.get("species"),
        persona=companion.get("persona"),
        mode="commentary",
    )


def _make_llm():
    from rag_demo.generation.generator import API_KEY, BASE_URL, MODEL

    if not API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    return ChatOpenAI(
        model=MODEL,
        api_key=API_KEY,
        base_url=BASE_URL,
        temperature=0.4,
        timeout=20,
        max_retries=1,
    )


def commentary(
    buyer_id: str,
    user_text: str,
    store_reply: str,
    *,
    llm: Any | None = None,
) -> str:
    """生成守护伙伴锐评；无授权动作，仅文本，输出必过 persona guard。"""
    try:
        companion = store.get_companion(buyer_id)
    except Exception:
        companion = {
            "name": c_persona.DEFAULT_NAME,
            "species": c_persona.DEFAULT_SPECIES,
            "persona": c_persona.DEFAULT_PERSONA,
            "user_nickname": "",
        }

    try:
        llm = llm or _make_llm()
        response = llm.invoke([
            SystemMessage(content=_system_prompt(companion)),
            HumanMessage(content=(
                f"伙伴名字：{companion.get('name')}\n"
                f"伙伴设定：{companion.get('species')} / {companion.get('persona')}\n"
                f"用户原话：{user_text}\n"
                f"店宠回复：{store_reply}\n"
                "请只给用户一句锐评或提醒。"
            )),
        ])
        text = str(getattr(response, "content", "") or "").strip()
    except Exception:
        logger.exception("伙伴锐评生成失败 buyer=%s", buyer_id)
        text = ""

    return c_persona.guard(text, tier="commentary", fallback=FALLBACK).text
