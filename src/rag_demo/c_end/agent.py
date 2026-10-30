"""C 端导购 Agent：推荐 → 准备订单 → interrupt 人工确认 → 模拟下单。"""
from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from rag_demo.c_end import persona as c_persona
from rag_demo.c_end import store, store_agent
from rag_demo.merchant import MerchantError, get_merchant_repository

C_TOOL_RULES = """你可以：
1. recommend_products(need, budget)：按需求/预算推荐真实商家商品；
2. query_my_orders(order_id, status)：查询当前买家的真实商家订单/物流状态；
3. prepare_order(items)：根据商品和数量准备订单草稿。

规则：
- 商品价格、库存、订单金额只能来自工具结果，禁止编造。
- 用户问物流、订单到哪、发货状态时，调用 query_my_orders，不要说自己没有工具。
- 用户表达购买意向后，调用 prepare_order 生成待确认订单。
- 不要在 prepare_order 后自行声称订单已创建；订单必须由用户确认。
- 如果商品或预算不匹配，如实说明。
"""


def build_system_prompt(buyer_id: str) -> str:
    """人设段 + 工具规则段；人设来自用户可配置的伙伴字段。"""
    try:
        companion = store.get_companion(buyer_id)
    except Exception:  # noqa: BLE001 - 伙伴读取失败不应阻断对话
        companion = {}
    return (
        c_persona.build_persona_prompt(
            name=companion.get("name"),
            user_nickname=companion.get("user_nickname"),
            species=companion.get("species"),
            persona=companion.get("persona"),
        )
        + "\n"
        + C_TOOL_RULES
    )


class ItemSchema(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=40)
    quantity: int = Field(..., ge=1, le=99)


class PrepareOrderSchema(BaseModel):
    items: list[ItemSchema] = Field(..., min_length=1, max_length=20)


class OrderQuerySchema(BaseModel):
    order_id: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=20)


class CAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    buyer_id: str
    thread_id: str
    draft: dict[str, Any]
    order: dict[str, Any]
    status: str


def _tools(buyer_id: str):
    @tool
    def recommend_products(need: str, budget: float | None = None) -> dict[str, Any]:
        """按需求关键词和预算推荐真实商家商品；返回价格、库存、SKU 和商品 ID。"""
        try:
            repo = get_merchant_repository()
            products = repo.list_products(store_agent.STORE_MERCHANT_ID, keyword=need, limit=20)
            result = []
            for product in products:
                skus = repo.list_product_skus(product.product_id, merchant_id=store_agent.STORE_MERCHANT_ID)
                if not skus:
                    continue
                sku = skus[0]
                inventory = repo.get_inventory(sku.sku, merchant_id=store_agent.STORE_MERCHANT_ID)
                price = float(sku.price)
                if budget is not None and price > float(budget):
                    continue
                item = product.to_dict()
                item.update({
                    "price": price,
                    "stock": inventory.available_qty if inventory else 0,
                    "sku": sku.sku,
                    "spec": sku.spec,
                    "in_stock": inventory.in_stock if inventory else False,
                    "source": "merchant_v1",
                })
                result.append(item)
            return {"ok": True, "source": "merchant_v1", "products": result}
        except MerchantError:
            products = store.list_products(keyword=need, limit=20)
            if budget is not None:
                products = [p for p in products if float(p["price"]) <= float(budget)]
            for product in products:
                product["source"] = "c_end_fallback"
            return {"ok": True, "source": "c_end_fallback", "products": products}

    @tool(args_schema=OrderQuerySchema)
    def query_my_orders(order_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        """查询当前买家自己的真实商家订单与物流状态；不能查其他买家。"""
        try:
            repo = get_merchant_repository()
            m_buyer = store_agent.merchant_buyer_id(buyer_id)
            if order_id:
                order = repo.get_order(
                    order_id,
                    merchant_id=store_agent.STORE_MERCHANT_ID,
                    buyer_id=m_buyer,
                )
                if order is None:
                    return {"ok": False, "error": {"code": "ORDER_NOT_FOUND", "message": "没有找到这笔订单"}}
                return {"ok": True, "source": "merchant_v1", "order": order.to_dict()}
            orders = repo.list_orders(
                store_agent.STORE_MERCHANT_ID,
                buyer_id=m_buyer,
                status=status,
                limit=10,
            )
            return {
                "ok": True,
                "source": "merchant_v1",
                "orders": [order.to_dict() for order in orders],
            }
        except MerchantError as exc:
            return {"ok": False, "error": {"code": "MERCHANT_UNAVAILABLE", "message": str(exc)}}

    @tool(args_schema=PrepareOrderSchema)
    def prepare_order(items: list[ItemSchema]) -> dict[str, Any]:
        """准备待确认订单；只生成草稿，不扣库存、不创建正式订单。"""
        normalized = [
            {"product_id": item.product_id, "quantity": item.quantity}
            for item in items
        ]
        draft = store.prepare_order(buyer_id, normalized)
        return {"ok": True, "data": draft, **draft}

    return [recommend_products, query_my_orders, prepare_order]


def _make_llm():
    from rag_demo.generation.generator import API_KEY, BASE_URL, MODEL
    from langchain_openai import ChatOpenAI

    if not API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法运行 C 端 Agent")
    return ChatOpenAI(
        model=MODEL,
        api_key=API_KEY,
        base_url=BASE_URL,
        temperature=0.2,
        timeout=60,
        max_retries=2,
    )


def _extract_draft(messages: list[Any]) -> dict[str, Any] | None:
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if getattr(msg, "name", "") != "prepare_order":
            continue
        payload = msg.content
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            candidate = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if candidate.get("order_id") and candidate.get("confirmation_token"):
                return candidate
    return None


def _last_ai_text(messages: list[Any]) -> str:
    for msg in reversed(messages or []):
        if getattr(msg, "content", None) and getattr(msg, "type", "") == "ai":
            return str(msg.content)
    return ""


def build_c_graph(buyer_id: str, checkpointer: Any, llm: Any | None = None):
    tools = _tools(buyer_id)
    llm = llm or _make_llm()
    llm_with_tools = llm.bind_tools(tools)

    def chatbot(state: CAgentState) -> dict[str, Any]:
        response = llm_with_tools.invoke(state.get("messages") or [])
        return {"messages": [response]}

    def route_after_chatbot(state: CAgentState) -> str:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        return "tools" if getattr(last, "tool_calls", None) else END

    def route_after_tools(state: CAgentState) -> str:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        if isinstance(last, ToolMessage) and getattr(last, "name", "") == "prepare_order":
            return "confirm"
        return "chatbot"

    def confirm(state: CAgentState) -> dict[str, Any]:
        draft = _extract_draft(state.get("messages") or [])
        if draft is None:
            return {
                "status": "FAILED",
                "messages": [AIMessage(content="没有找到可确认的订单草稿。")],
            }
        decision = interrupt({
            "type": "order_confirmation",
            "draft": draft,
            "message": "请确认订单商品、数量和金额；确认前不会扣库存。",
        })
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else False
        if not approved:
            return {
                "draft": draft,
                "status": "CANCELLED",
                "messages": [AIMessage(content="订单已取消，不会扣库存。")],
            }
        order = store.confirm_order(
            state["buyer_id"],
            draft["order_id"],
            draft["confirmation_token"],
            request_id=state.get("thread_id"),
        )
        return {
            "draft": draft,
            "order": order,
            "status": "CONFIRMED",
            "messages": [
                AIMessage(
                    content=(
                        f"订单已创建：{order['order_id']}，"
                        f"金额 {order['total_amount']:.2f} 元。"
                    )
                )
            ],
        }

    graph = StateGraph(CAgentState)
    graph.add_node("chatbot", chatbot)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("confirm", confirm)
    graph.add_edge(START, "chatbot")
    graph.add_conditional_edges("chatbot", route_after_chatbot, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", route_after_tools, {"confirm": "confirm", "chatbot": "chatbot"})
    graph.add_edge("confirm", END)
    return graph.compile(checkpointer=checkpointer)


def run_c_agent(
    message: str,
    *,
    buyer_id: str,
    thread_id: str,
    checkpointer: Any,
    llm: Any | None = None,
) -> dict[str, Any]:
    graph = build_c_graph(buyer_id, checkpointer, llm=llm)
    config = {"configurable": {"thread_id": thread_id}}
    if graph.get_state(config).values:
        raise ValueError("thread_id 已存在，请使用新的 thread_id")
    state = graph.invoke(
        {
            "messages": [
                SystemMessage(content=build_system_prompt(buyer_id)),
                HumanMessage(content=message),
            ],
            "buyer_id": buyer_id,
            "thread_id": thread_id,
            "status": "RUNNING",
        },
        config=config,
    )
    snapshot = graph.get_state(config)
    interrupted = bool(snapshot.next)
    draft = _extract_draft(state.get("messages") or [])
    if interrupted:
        status = "AWAITING_CONFIRMATION"
    elif _last_ai_text(state.get("messages") or []):
        status = "COMPLETED"
    else:
        status = state.get("status") or "FAILED"
    return {
        "thread_id": thread_id,
        "interrupted": interrupted,
        "status": status,
        "draft": draft,
        "order": state.get("order"),
        "messages": state.get("messages") or [],
        "next": list(snapshot.next or ()),
    }


def resume_c_agent(
    *,
    buyer_id: str,
    thread_id: str,
    approved: bool,
    checkpointer: Any,
    llm: Any | None = None,
) -> dict[str, Any]:
    graph = build_c_graph(buyer_id, checkpointer, llm=llm)
    config = {"configurable": {"thread_id": thread_id}}
    before = graph.get_state(config)
    if not before.values:
        raise ValueError("thread_id 不存在")
    if before.values.get("buyer_id") != buyer_id:
        raise PermissionError("不能恢复其他用户的 Agent 会话")
    if not before.next:
        return {
            "thread_id": thread_id,
            "status": before.values.get("status") or "COMPLETED",
            "order": before.values.get("order"),
            "messages": before.values.get("messages") or [],
            "interrupted": False,
        }
    state = graph.invoke(Command(resume={"approved": bool(approved)}), config=config)
    snapshot = graph.get_state(config)
    return {
        "thread_id": thread_id,
        "interrupted": bool(snapshot.next),
        "status": state.get("status") or "COMPLETED",
        "order": state.get("order"),
        "draft": state.get("draft"),
        "messages": state.get("messages") or [],
        "next": list(snapshot.next or ()),
    }
