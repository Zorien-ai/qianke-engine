"""C 端守护伙伴：只做辅助传达和锐评，不参与砍价/下单。"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from rag_demo.c_end import store

logger = logging.getLogger(__name__)

FALLBACK = "主人，店宠说得再甜，价格和活动还是以结算页为准。"

SYSTEM_PROMPT = """你是用户的守护伙伴，不是店宠，也不是谈判代表。

你只能：
- 帮用户理解店宠回复；
- 做一句简短、犀利的提醒/锐评；
- 提醒用户确认价格、活动规则和订单。

你不能：
- 替用户砍价或答应价格；
- 承诺优惠、退款、赔付；
- 替用户确认或创建订单；
- 编造商品/活动信息。

输出 1-2 句中文，不超过 80 字，不能包含“已下单”“已确认”“保证”等承诺。
"""


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
    """生成守护伙伴锐评；无授权动作，仅文本。"""
    try:
        companion = store.get_companion(buyer_id)
    except Exception:
        companion = {"name": "小伴", "species": "digital_companion", "persona": "warm"}

    try:
        llm = llm or _make_llm()
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
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

    text = text.strip().strip("`").strip()
    if not text:
        return FALLBACK
    # 不做硬性内容改写；只限长，避免污染聊天区。
    return text[:120]
