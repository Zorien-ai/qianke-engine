"""Super-agent Worker：Deep Agents 调查订单 / 售后 / 政策。

写操作不在这里执行：Worker 只读调查并给出结论，最终由人工审批。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from rag_demo.c_end import store, store_policy
from rag_demo.merchant import get_merchant_repository
from rag_demo.superagent import store as sa_store

logger = logging.getLogger(__name__)

MERCHANT_ID = "m_gear_002"


@tool
def query_order(order_id: str) -> str:
    """查询订单：C 端状态、商家状态、金额、物流、售后摘要。"""
    order = store.get_order(order_id.strip())
    if order is None:
        return f"订单 {order_id} 不存在或无权查看。"
    item_names = "、".join(
        f"{item.get('title') or item.get('product_id')}×{item.get('quantity')}"
        for item in order.get("items") or []
    )
    return (
        f"订单 {order['order_id']}：C状态={order['status']}；"
        f"商家状态={order.get('merchant_status')}；金额=¥{order.get('total_amount')}；"
        f"商品={item_names}；物流={order.get('merchant_carrier') or '-'} "
        f"{order.get('merchant_tracking_no') or ''}；"
        f"售后={order.get('after_sale') or '无'}；"
        f"可取消={order.get('can_cancel')}；可售后={order.get('can_after_sale')}"
    )


@tool
def query_after_sales(order_id: str) -> str:
    """查询某订单的售后工单；order_id 为空时查最近工单。"""
    tickets = store.list_after_sales(
        order_id=order_id.strip() or None,
        limit=20,
    )
    if not tickets:
        return "没有查到售后工单。"
    return "\n".join(
        f"- {t['ticket_id']} / {t['type']} / {t['status']} / 退款={t.get('refund_amount')} / "
        f"原因={t['reason']} / 退回={t.get('return_tracking_no') or '-'}"
        for t in tickets
    )


@tool
def query_products(keyword: str) -> str:
    """按关键词查询商家商品、价格与库存。"""
    repo = get_merchant_repository()
    products = repo.list_products(MERCHANT_ID, keyword=keyword.strip() or None, limit=10)
    if not products:
        return "没有匹配商品。"
    lines = []
    for product in products:
        skus = repo.list_product_skus(product.product_id, merchant_id=MERCHANT_ID)
        price = skus[0].price if skus else "?"
        inv = repo.get_inventory(skus[0].sku, merchant_id=MERCHANT_ID) if skus else None
        lines.append(
            f"- {product.product_id} {product.title}：¥{price}，"
            f"可售={inv.available_qty if inv else '?'}"
        )
    return "\n".join(lines)


@tool
def query_policy(topic: str) -> str:
    """查询售后/发货/优惠平台政策。"""
    hits = store_policy.search_policies(topic.strip())
    return "\n".join(f"- {item.get('title')}：{item.get('content')}" for item in hits)


SYSTEM_PROMPT = """你是千客 B 端 Super-agent 的售后/订单调查员。

职责：
- 查清订单、售后、商品/库存、平台政策；
- 只给事实、依据、建议，不编造；
- 绝不能修改订单、退款、库存、售后状态；
- 如果建议动作涉及退款、取消、退货入库，必须标记「需要人工确认」；
- 最终输出中文，结构：结论 / 依据 / 建议 / 需要人工确认。

可用子代理：
- order_analyst：订单/售后/商品库存
- policy_advisor：售后、发货、优惠政策
"""

SUBAGENTS = [
    {
        "name": "order_analyst",
        "description": "查询订单、售后工单、商品价格与库存；只读。",
        "system_prompt": "你是订单调查员。只查询事实，不修改任何数据。",
        "tools": [query_order, query_after_sales, query_products],
    },
    {
        "name": "policy_advisor",
        "description": "查询平台售后、发货、优惠规则；只给政策依据。",
        "system_prompt": "你是政策顾问。只引用已配置政策，不发明规则。",
        "tools": [query_policy],
    },
]


def _make_llm() -> ChatOpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    return ChatOpenAI(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL") or None,
        temperature=0.1,
        timeout=120,
        max_retries=1,
    )


def build_agent():
    """延迟构造 Deep Agent，避免模块导入时就要求模型依赖。"""
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=_make_llm(),
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        subagents=SUBAGENTS,
        name="qianke_superagent_worker",
    )


def _fallback_report(item: dict[str, Any], error: str) -> str:
    """LLM/Worker 不可用时的确定性调查，保证链路可用。"""
    import re

    text = "\n".join(trigger["content"] for trigger in item.get("triggers") or [])
    match = re.search(r"\b(order_[a-zA-Z0-9]+|ORD-\d{8}-\d{4})\b", text)
    order_text = query_order.invoke({"order_id": match.group(1)}) if match else "未从事件中识别到订单号。"
    ticket_text = query_after_sales.invoke({"order_id": match.group(1)}) if match else ""
    policy_text = query_policy.invoke({"topic": "售后"})
    return (
        "结论：Worker 模型暂不可用，以下为确定性只读调查结果。\n"
        f"依据：\n- {order_text}\n- {ticket_text}\n- {policy_text}\n"
        f"错误：{error}\n"
        "建议：请人工复核订单与售后状态。\n"
        "需要人工确认：是"
    )


def run_work_item(work_item_id: str) -> dict[str, Any]:
    """同步执行一个 WorkItem；由 API 放进后台线程调用。"""
    item = sa_store.start_work_item(work_item_id)
    triggers = item.get("triggers") or []
    user_text = "\n".join(
        f"[{trigger['source']}/{trigger['channel']}] {trigger['content']}" for trigger in triggers
    )
    try:
        agent = build_agent()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_text}]},
            config={"recursion_limit": 12},
        )
        messages = result.get("messages") or []
        final = ""
        for message in reversed(messages):
            if getattr(message, "type", "") == "ai" and getattr(message, "content", ""):
                final = str(message.content).strip()
                break
        if not final:
            raise RuntimeError("Worker 没有产生最终回答")
        output = {
            "summary": final,
            "trigger_count": len(triggers),
            "worker": "deepagents",
        }
        return sa_store.finish_work_item(work_item_id, output, approval=True)
    except Exception as exc:  # noqa: BLE001 - 失败回退到确定性调查，便于运维
        logger.exception("Super-agent Worker 失败 work_item=%s", work_item_id)
        output = {
            "summary": _fallback_report(item, str(exc)),
            "trigger_count": len(triggers),
            "worker": "deterministic_fallback",
            "error": str(exc)[:1000],
        }
        return sa_store.finish_work_item(work_item_id, output, approval=True)
