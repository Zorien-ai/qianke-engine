"""C 端导购 Agent：推荐 → 准备订单 → interrupt 人工确认 → 模拟下单。"""
from __future__ import annotations

import hashlib
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
from rag_demo.c_end import express, store, store_agent
from rag_demo.c_end import router as question_router
from rag_demo.c_end.router import (
    MODE_ADVISOR,
    MODE_COMPANION,
    MODE_ORDER,
    MODE_TRANSACTION,
    MODES,
    route_question,
)
from rag_demo.c_end.catalog_search import is_browse_query, rank_product_matches
from rag_demo.merchant import MerchantError, get_merchant_repository

C_TOOL_RULES = """你可以：
1. recommend_products(need, budget)：按需求/预算推荐真实商家商品；
2. query_my_orders(order_id, status)：查询当前买家的真实商家订单/物流状态；
3. query_tracking(order_id)：查询当前买家订单的实时快递轨迹；
4. prepare_order(items)：根据商品和数量准备订单草稿。

规则：
- 商品价格、库存、订单金额只能来自工具结果，禁止编造。
- 用户问物流、订单到哪、发货状态时，调用 query_my_orders；需要轨迹时再调用 query_tracking。
- 用户问快递轨迹时，不要说自己没有工具；先拿订单号，再查轨迹。
- 物流服务商未配置或查询失败时，如实说明暂时查不到，禁止编造物流节点。
- 用户表达购买意向后，调用 prepare_order 生成待确认订单。
- 用户明确说"下单 / 买一件 / 直接出草稿"时，直接调用 prepare_order；数量按用户说的，
  系统里没有的字段（尺码、颜色、材质）不要追问，也不要替用户补。
- 不要在 prepare_order 后自行声称订单已创建；订单必须由用户确认。
- 如果商品或预算不匹配，如实说明。
"""

VALID_MODES = MODES

_COMPANION_RULES = """【本次模式：陪伴】
本轮只做陪伴和倾听，不主动推荐商品、不生成订单、不查询订单。
用户只是聊天、倾诉、分享日常时，先接住情绪，再决定要不要给建议。
不要为了完成销售把话题拉回商品；不要使用"买点东西会开心"这类引导消费的话。
如果用户明确问商品、价格、订单，告诉用户可以切到"帮我挑东西"或直接说需求，再进入购物模式。
"""

_ORDER_RULES = """【本次模式：订单服务】
本轮只处理订单、物流、售后状态查询，调用 query_my_orders / query_tracking。
不主动推荐商品，不生成订单草稿；用户要下单时提示切到交易流程。
物流服务不可用时如实说明，禁止编造物流节点。
"""

_ADVISOR_RULES = """【本次模式：购物参谋】
本轮可以调用 recommend_products 帮助用户挑商品、比价、判断是否值得买。
只能推荐真实商品，价格、库存、活动必须来自工具结果。
本轮不要生成订单草稿；用户明确要下单时，让用户确认进入交易流程，再生成订单草稿。
不要催单，不要把"陪伴"当作推销理由。
"""

_IMAGE_RULES = """【商品图片】
CApp 会自动把商品结果显示成图片卡，不需要你“上传”图片。
用户要看图片、实拍、汤色、商品页时，直接说“给你看图片/商品图在下面”，
禁止说“图发不了、传不过去、我做不到”。如果当前没有商品结果，如实说明需要先选商品。
"""

_IMAGE_TOOL_RULES = """商品工具会返回 image_url。用户要看图片时，调用 recommend_products 获取商品，
再正常介绍；图片会由界面自动展示。"""

_MODE_RULES = {
    MODE_COMPANION: _COMPANION_RULES + "\n" + _IMAGE_RULES,
    MODE_ADVISOR: _ADVISOR_RULES + "\n" + _IMAGE_RULES + "\n" + _IMAGE_TOOL_RULES,
    MODE_ORDER: _ORDER_RULES,
    MODE_TRANSACTION: C_TOOL_RULES + "\n" + _IMAGE_RULES + "\n" + _IMAGE_TOOL_RULES,
}

_TRANSACTION_HINTS = (
    "下单", "买", "购买", "订单", "物流", "发货", "收货", "退货", "退款",
    "售后", "支付", "付款", "取消", "草稿", "确认订单", "到哪", "快递", "运单",
    "buy", "order", "checkout",
)
_ADVISOR_HINTS = (
    "推荐", "挑", "选", "对比", "值不值", "预算", "价格", "多少钱", "活动",
    "优惠", "便宜", "礼物", "送", "尺码", "库存", "哪个", "怎么选", "跑鞋",
    "图片", "看图", "看看图", "照片", "实拍", "商品图", "商品页", "我要看看",
    "鞋", "衣服", "包", "推荐一下", "recommend",
)
_MEMORY_DECLARATION_MARKERS = (
    "我喜欢", "我不喜欢", "我的预算", "我预算", "别给我推荐",
    "不要推荐", "别推荐", "我对", "我穿",
)


def detect_mode(message: str, requested: str | None = None) -> str:
    """兼容旧调用：模式判断统一收口到问题 Router。"""
    return route_question(message, requested_mode=requested).mode


def build_system_prompt(
    buyer_id: str,
    mode: str = MODE_TRANSACTION,
    *,
    message: str = "",
) -> str:
    """人设段 + 记忆段 + 本轮模式规则段。"""
    try:
        companion = store.get_companion(buyer_id)
    except Exception:  # noqa: BLE001 - 伙伴读取失败不应阻断对话
        companion = {}
    try:
        memories = store.list_memories(buyer_id, limit=8)
    except Exception:  # noqa: BLE001 - 记忆读取失败不应阻断对话
        memories = []
    try:
        digests = store.list_memory_digests(buyer_id, limit=5)
    except Exception:  # noqa: BLE001
        digests = []
    diary = None
    if any(marker in str(message or "") for marker in ("日记", "昨天", "前天")):
        try:
            recent = store.list_diaries(buyer_id, limit=1)
            diary = recent[0] if recent else None
        except Exception:  # noqa: BLE001
            diary = None
    selected = mode if mode in VALID_MODES else MODE_TRANSACTION
    text = c_persona.build_persona_prompt(
        name=companion.get("name"),
        user_nickname=companion.get("user_nickname"),
        species=companion.get("species"),
        persona=companion.get("persona"),
    )
    if memories:
        lines = [f"- {item['kind']}：{item['content']}" for item in memories]
        text += (
            "\n【你记得的事】\n"
            + "\n".join(lines)
            + "\n这些是用户明确说过的偏好或边界，只作为上下文参考；"
            "价格、库存、订单仍以工具结果为准，用户当前说法与记忆冲突时以当前说法为准。"
        )
    if digests:
        lines = [f"- {item['kind']}：{item['content']}" for item in digests]
        text += "\n【你压缩后的记忆】\n" + "\n".join(lines)
    if diary:
        text += (
            f"\n【你 {diary.get('diary_date')} 的日记】\n"
            + str(diary.get("content") or "")[:600]
            + "\n只有在用户主动聊到日记或过去时才引用，不要主动编造日记内容。"
        )
    return text + "\n" + _MODE_RULES[selected]


class ItemSchema(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=40)
    quantity: int = Field(..., ge=1, le=99)


class PrepareOrderSchema(BaseModel):
    items: list[ItemSchema] = Field(..., min_length=1, max_length=20)


class OrderQuerySchema(BaseModel):
    order_id: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=20)


class TrackingQuerySchema(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=80)


class CAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    buyer_id: str
    thread_id: str
    mode: str
    draft: dict[str, Any]
    order: dict[str, Any]
    status: str


def _tools(buyer_id: str, mode: str = MODE_TRANSACTION):
    @tool
    def recommend_products(need: str, budget: float | None = None) -> dict[str, Any]:
        """按需求关键词和预算推荐真实商家商品；返回价格、库存、SKU 和商品 ID。"""
        try:
            repo = get_merchant_repository()
            # 先按商品目录做语义召回；没有命中时再跨商家兜底，
            # 避免 CApp 小伴因为默认商家不是当前店铺而“查不到在售商品”。
            products = rank_product_matches(
                repo.list_products(store_agent.STORE_MERCHANT_ID, limit=100),
                need,
                limit=20,
            )
            if not products:
                all_products = []
                for tenant in store.list_tenants():
                    tenant_id = str(tenant.get("merchant_id") or "").strip()
                    if not tenant_id:
                        continue
                    all_products.extend(repo.list_products(tenant_id, limit=100))
                products = rank_product_matches(all_products, need, limit=20)
                if not products and is_browse_query(need):
                    products = all_products[:20]
            result = []
            for product in products:
                product_merchant = str(getattr(product, "merchant_id", "") or store_agent.STORE_MERCHANT_ID)
                skus = repo.list_product_skus(product.product_id, merchant_id=product_merchant)
                if not skus:
                    continue
                sku = skus[0]
                inventory = repo.get_inventory(sku.sku, merchant_id=product_merchant)
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
            merchant_ids = [
                str(tenant.get("merchant_id") or "").strip()
                for tenant in store.list_tenants()
                if str(tenant.get("merchant_id") or "").strip()
            ]
            if not merchant_ids:
                merchant_ids = [store_agent.STORE_MERCHANT_ID]
            if order_id:
                for merchant_id in merchant_ids:
                    order = repo.get_order(order_id, merchant_id=merchant_id, buyer_id=m_buyer)
                    if order is not None:
                        return {"ok": True, "source": "merchant_v1", "order": order.to_dict()}
                return {"ok": False, "error": {"code": "ORDER_NOT_FOUND", "message": "没有找到这笔订单"}}
            orders = []
            for merchant_id in merchant_ids:
                orders.extend(repo.list_orders(
                    merchant_id,
                    buyer_id=m_buyer,
                    status=status,
                    limit=10,
                ))
            orders.sort(key=lambda item: str(getattr(item, "created_at", "") or ""), reverse=True)
            return {
                "ok": True,
                "source": "merchant_v1",
                "orders": [order.to_dict() for order in orders[:10]],
            }
        except MerchantError as exc:
            return {"ok": False, "error": {"code": "MERCHANT_UNAVAILABLE", "message": str(exc)}}

    @tool(args_schema=TrackingQuerySchema)
    def query_tracking(order_id: str) -> dict[str, Any]:
        """查询当前买家订单的实时快递轨迹；只查本人订单，不伪造物流节点。"""
        order = store.get_order(order_id)
        if order is None or order.get("buyer_id") != buyer_id:
            return {"ok": False, "error": {"code": "ORDER_NOT_FOUND", "message": "没有找到这笔订单"}}
        tracking_no = str(order.get("merchant_tracking_no") or "").strip()
        if not tracking_no:
            return {
                "ok": False,
                "error": {"code": "TRACKING_NOT_AVAILABLE", "message": "这笔订单还没有物流单号"},
            }
        try:
            return {
                "ok": True,
                "order_id": order_id,
                **express.query_tracking(order.get("merchant_carrier"), tracking_no),
            }
        except express.ExpressError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        except Exception:  # noqa: BLE001 - 物流通道异常不阻塞 Agent
            return {
                "ok": False,
                "error": {"code": "EXPRESS_UNAVAILABLE", "message": "物流查询暂不可用"},
            }

    @tool(args_schema=PrepareOrderSchema)
    def prepare_order(items: list[ItemSchema]) -> dict[str, Any]:
        """准备待确认订单；只生成草稿，不扣库存、不创建正式订单。"""
        normalized = [
            {"product_id": item.product_id, "quantity": item.quantity}
            for item in items
        ]
        draft = store.prepare_order(buyer_id, normalized)
        return {"ok": True, "data": draft, **draft}

    if mode == MODE_COMPANION:
        return []
    if mode == MODE_ADVISOR:
        return [recommend_products]
    if mode == MODE_ORDER:
        return [query_my_orders, query_tracking]
    return [recommend_products, query_my_orders, query_tracking, prepare_order]


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


def _extract_product_refs(messages: list[Any]) -> list[dict[str, Any]]:
    """从本轮工具结果提取商品卡片，供 CApp 气泡直接展示图片。"""
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages or []:
        name = getattr(message, "name", "")
        if name not in {"recommend_products", "search_catalog"}:
            continue
        payload = getattr(message, "content", "")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                continue
        if not isinstance(payload, dict):
            continue
        for product in payload.get("products") or []:
            product_id = str(product.get("product_id") or "").strip()
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            refs.append({
                "product_id": product_id,
                "merchant_id": product.get("merchant_id") or "",
                "title": product.get("title") or "",
                "price": product.get("price"),
                "sku": product.get("sku") or "",
                "spec": product.get("spec") or "",
                "image_url": product.get("image_url") or "",
                "thumb_url": product.get("image_url") or "",
            })
    return refs[:6]


def _is_image_request(text: str) -> bool:
    return any(word in (text or "") for word in ("图片", "看图", "看看图", "照片", "实拍", "商品图", "商品页", "我要看看"))


def _last_saved_product_refs(buyer_id: str) -> list[dict[str, Any]]:
    try:
        messages = store.list_app_messages(buyer_id, "companion", limit=30)
    except Exception:  # noqa: BLE001 - 历史消息不可用不应阻断当前回复
        return []
    for message in reversed(messages):
        metadata = message.get("metadata") or {}
        refs = metadata.get("product_refs") if isinstance(metadata, dict) else None
        if message.get("role") == "companion" and isinstance(refs, list) and refs:
            return refs[:6]
    return []


def _last_ai_text(messages: list[Any]) -> str:
    for msg in reversed(messages or []):
        if getattr(msg, "content", None) and getattr(msg, "type", "") == "ai":
            return str(msg.content)
    return ""


def build_c_graph(
    buyer_id: str,
    checkpointer: Any,
    llm: Any | None = None,
    mode: str = MODE_TRANSACTION,
):
    selected = mode if mode in VALID_MODES else MODE_TRANSACTION
    tools = _tools(buyer_id, selected)
    llm = llm or _make_llm()
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    def chatbot(state: CAgentState) -> dict[str, Any]:
        response = llm_with_tools.invoke(state.get("messages") or [])
        return {"messages": [response]}

    def route_after_chatbot(state: CAgentState) -> str:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        if not tools:
            return END
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
    graph.add_node("confirm", confirm)
    graph.add_edge(START, "chatbot")
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_conditional_edges("chatbot", route_after_chatbot, {"tools": "tools", END: END})
        graph.add_conditional_edges("tools", route_after_tools, {"confirm": "confirm", "chatbot": "chatbot"})
    else:
        graph.add_conditional_edges("chatbot", route_after_chatbot, {END: END})
    graph.add_edge("confirm", END)
    return graph.compile(checkpointer=checkpointer)


def _load_app_history(buyer_id: str, current_message: str, *, limit: int = 20) -> list[Any]:
    """从 C App 已持久化消息回填上下文；同一条当前用户消息不重复注入。"""
    try:
        rows = store.list_app_messages(buyer_id, "companion", limit=limit)
    except Exception:  # noqa: BLE001 - 历史读取失败不应阻断当前对话
        return []
    history: list[Any] = []
    for row in rows or []:
        text = str(row.get("content") or "").strip()
        if not text:
            continue
        role = str(row.get("role") or "")
        if role == "user":
            history.append(HumanMessage(content=text))
        elif role in {"companion", "assistant"}:
            history.append(AIMessage(content=text))
    # 前端在请求前会先持久化当前 user 消息，避免重复。
    if history and isinstance(history[-1], HumanMessage) and history[-1].content.strip() == current_message.strip():
        history.pop()
    return history[-limit:]


def companion_thread_id(buyer_id: str) -> str:
    """同一买家的稳定小鱼会话 ID；服务端生成，客户端只引用。"""
    digest = hashlib.sha256(f"qianke:c:companion:{buyer_id}".encode("utf-8")).hexdigest()[:24]
    return f"c_conv_{digest}"


class _SessionProbeLLM:
    """只用于读取 checkpoint 状态，不执行模型调用。"""

    def bind_tools(self, tools: Any) -> "_SessionProbeLLM":
        return self

    def invoke(self, messages: Any) -> Any:  # pragma: no cover - 防御性
        raise RuntimeError("session probe 不应调用模型")


def get_c_agent_session(buyer_id: str, checkpointer: Any) -> dict[str, Any]:
    """返回稳定会话、当前模式以及是否还有待确认草稿。"""
    thread_id = companion_thread_id(buyer_id)
    graph = build_c_graph(buyer_id, checkpointer, llm=_SessionProbeLLM(), mode=MODE_TRANSACTION)
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values or {}
    if values and values.get("buyer_id") != buyer_id:
        raise PermissionError("不能读取其他用户的 Agent 会话")
    return {
        "thread_id": thread_id,
        "mode": values.get("mode") or MODE_COMPANION,
        "interrupted": bool(snapshot.next),
        "draft": _extract_draft(values.get("messages") or []),
        "status": values.get("status") or "IDLE",
    }


def _mode_switch_message(mode: str, previous_mode: str) -> SystemMessage:
    return SystemMessage(content=(
        f"【模式切换】上一轮是 {previous_mode} 模式；本轮用户意图切换到 {mode} 模式。"
        "忽略之前所有模式限制，从这一轮开始按下面的规则执行。\n"
        + _MODE_RULES.get(mode, _MODE_RULES[MODE_COMPANION])
    ))


def run_c_agent(
    message: str,
    *,
    buyer_id: str,
    thread_id: str,
    checkpointer: Any,
    llm: Any | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    decision = route_question(message, requested_mode=mode)
    selected = decision.mode
    graph = build_c_graph(buyer_id, checkpointer, llm=llm, mode=selected)
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    existing = snapshot.values or {}
    history: list[Any] = []
    if existing:
        if existing.get("buyer_id") != buyer_id:
            raise PermissionError("不能继续其他用户的 Agent 会话")
        if snapshot.next:
            raise ValueError("当前会话有待确认订单，请先确认或取消后再发新消息")
        existing_mode = str(existing.get("mode") or MODE_COMPANION)
        switch_messages: list[Any] = []
        if existing_mode != selected:
            # 允许同一 thread 内随用户意图切模式；只重建工具图，不丢历史消息。
            graph = build_c_graph(buyer_id, checkpointer, llm=llm, mode=selected)
            switch_messages = [_mode_switch_message(selected, existing_mode)]
        payload: dict[str, Any] = {
            "messages": [*switch_messages, HumanMessage(content=message)],
            "buyer_id": buyer_id,
            "thread_id": thread_id,
            "mode": selected,
            "status": "RUNNING",
        }
    else:
        history = _load_app_history(buyer_id, message)
        payload = {
            "messages": [
                SystemMessage(content=build_system_prompt(buyer_id, selected, message=message)),
                *history,
                HumanMessage(content=message),
            ],
            "buyer_id": buyer_id,
            "thread_id": thread_id,
            "mode": selected,
            "status": "RUNNING",
        }
    state = graph.invoke(payload, config=config)
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
        "mode": selected,
        "route": decision.route,
        "confidence": decision.confidence,
        "slots": decision.slots,
        "interrupted": interrupted,
        "status": status,
        "draft": draft,
        "order": state.get("order"),
        "messages": state.get("messages") or [],
        "product_refs": _extract_product_refs(state.get("messages") or [])
        or (_last_saved_product_refs(buyer_id) if _is_image_request(message) else []),
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
    # 只有交易模式会 interrupt；恢复时使用完整工具图，避免 checkpoint 节点不匹配。
    graph = build_c_graph(buyer_id, checkpointer, llm=llm, mode=MODE_TRANSACTION)
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
