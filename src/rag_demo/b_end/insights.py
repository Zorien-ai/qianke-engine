"""B 端画像查询：千客用户 / 导入用户 / 全部用户 的检索与问答编排。

三条链路：
- imported：原 RAG 产品的 `answer_question`（RAG + Text2SQL + guard），
  数据空间是商户自己的 `mch_*` 数据集；
- qianke：千客用户池（会话 + 交易并集）语义检索 + 一次 `generate`，不跑 Text2SQL；
- all：导入侧 `pipeline.prepare` 的证据 + 千客池证据合并后一次 `generate`；
  结构化查询（SQL）只覆盖导入用户，回答必须带覆盖说明。

本模块不做租户解析：merchant_id / dataset 由 `api/b_workbench.py` 从登录态推导后传入。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from rag_demo import pipeline
from rag_demo.b_end import persona as b_persona
from rag_demo.b_end import store as persona_store
from rag_demo.b_end import user_pool
from rag_demo.c_end import store
from rag_demo.config import is_doc_source
from rag_demo.db.connection import get_conn, reset_dataset, use_dataset
from rag_demo.generation.generator import generate
from rag_demo.profile_view import (
    PROFILE_SELECT_COLUMNS,
    extract_profile_name,
    mask_name,
    profile_row,
    redact_profile_text,
)
from rag_demo.prompts import LLM_UNAVAILABLE_REPLY
from rag_demo.retrieval.query_processor import STRATEGY_DIRECT, search_variants

logger = logging.getLogger(__name__)

SCOPES = ("qianke", "imported", "all")
DEFAULT_PROFILE_LIMIT = 5

_IMPORTED_CARD_COLUMNS = (
    "user_id, profile_text, age, gender, city, member_level, "
    "order_count, avg_amount::float8, top_category, days_since_last_buy"
)


# ==================== 人设 ====================

def persona_context(account: dict | None) -> tuple[str, dict, str]:
    """返回 (人设 prompt, identity, 缓存键)。与 /qa、/api/agent/run 同一套账号级人设。"""
    account = account or {}
    account_id = account.get("id")
    row = persona_store.get_persona(account_id) if account_id is not None else None
    identity = b_persona.resolve_identity(account, row)
    prompt = b_persona.build_from_identity(identity, mode="chat")
    key = f"{identity.get('name')}|{identity.get('user_address')}|{identity.get('tone_profile')}"
    return prompt, identity, key


def compose_persona(prompt: str, note: str | None = None) -> str:
    return b_persona.compose_system_message(prompt, note)


# ==================== 导入用户（商户数据集） ====================

def dataset_status(dataset: str) -> dict[str, Any]:
    """数据空间是否就绪 + 画像/文档/切片计数；任何失败都降级成 ready=False。"""
    status = {
        "dataset": dataset,
        "ready": False,
        "profiles": 0,
        "docs": 0,
        "chunks": 0,
        "error": "",
    }
    try:
        conn = get_conn(dataset)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT to_regclass('public.user_profile_vectors') IS NOT NULL, "
                "to_regclass('public.wiki_vectors') IS NOT NULL"
            )
            profiles_table, wiki_table = cur.fetchone()
            if not (profiles_table and wiki_table):
                return status
            cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
            status["profiles"] = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT doc_name) FROM wiki_vectors")
            status["chunks"], status["docs"] = (int(x or 0) for x in cur.fetchone())
            status["ready"] = True
        finally:
            conn.rollback()
            cur.close()
    except Exception as exc:  # noqa: BLE001 - 未建库/连不上都按「未就绪」展示
        status["error"] = str(exc)[:200]
        logger.info("B 端数据空间不可用 dataset=%s: %s", dataset, exc)
    return status


def imported_profile_page(dataset: str, *, page: int = 1, size: int = 12) -> dict[str, Any]:
    """导入用户卡牌分页（只读；姓名脱敏；不返回 profile_text）。"""
    page = max(1, int(page or 1))
    size = min(50, max(1, int(size or 12)))
    token = use_dataset(dataset)
    try:
        conn = get_conn(dataset)
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
            total = int(cur.fetchone()[0] or 0)
            cur.execute(
                f"SELECT {PROFILE_SELECT_COLUMNS} FROM user_profile_vectors "
                "ORDER BY user_id ASC LIMIT %s OFFSET %s",
                (size, (page - 1) * size),
            )
            items = [_card_from_profile_row(profile_row(row)) for row in cur.fetchall()]
        finally:
            conn.rollback()
            cur.close()
    finally:
        reset_dataset(token)
    return {
        "source": "imported",
        "page": page,
        "size": size,
        "total": total,
        "total_pages": (total + size - 1) // size if total else 0,
        "items": items,
        "mode": "list",
    }


def _card_from_profile_row(row: dict) -> dict[str, Any]:
    tags = [value for value in (row.get("member_level"), row.get("city"), row.get("top_category")) if value]
    return {
        "source": "imported",
        "user_id": row.get("user_id"),
        "display_name": row.get("name"),
        "tags": tags,
        "stats": {
            "order_count": int(row.get("order_count") or 0),
            "avg_amount": row.get("avg_amount"),
            "total_amount": None,
            "last_order_at": None,
        },
        "fields": {
            "age": row.get("age"),
            "gender": row.get("gender"),
            "city": row.get("city"),
            "member_level": row.get("member_level"),
            "top_category": row.get("top_category"),
            "days_since_last_buy": row.get("days_since_last_buy"),
        },
        "chat": {},
        "confidence": None,
        "updated_at": None,
    }


def _imported_cards_from_candidates(candidates: list[dict]) -> list[dict]:
    """按检索候选里的 user:U... 补齐结构化卡片（含脱敏姓名）。"""
    user_ids: list[str] = []
    for candidate in candidates or []:
        cid = str(candidate.get("id") or "")
        if candidate.get("source") != "user_profile" or not cid.startswith("user:"):
            continue
        uid = cid.split(":", 1)[1].strip()
        if uid and uid not in user_ids:
            user_ids.append(uid)
    if not user_ids:
        return []
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT {_IMPORTED_CARD_COLUMNS} FROM user_profile_vectors WHERE user_id = ANY(%s)",
            (user_ids,),
        )
        rows = {row[0]: row for row in cur.fetchall()}
    finally:
        conn.rollback()
        cur.close()
    cards = []
    for uid in user_ids:
        row = rows.get(uid)
        if row is None:
            continue
        cards.append(_card_from_profile_row(profile_row(row)))
    return cards


def imported_profile_search(dataset: str, question: str, *, limit: int = 10) -> dict[str, Any]:
    """导入用户的确定性语义检索：单路 hybrid（向量+BM25）→ 画像候选 → 结构化卡片。"""
    limit = min(20, max(1, int(limit or 10)))
    token = use_dataset(dataset)
    try:
        try:
            candidates = search_variants(
                [(STRATEGY_DIRECT, question)],
                top_k_profile=limit,
                origin_query=question,
            )
        except Exception:  # noqa: BLE001 - 模型/索引异常时退回文本匹配
            logger.warning("B 端导入画像检索失败，退回文本匹配 dataset=%s", dataset, exc_info=True)
            candidates = []
        profiles = [c for c in candidates if not is_doc_source(str(c.get("source") or ""))]
        cards = _imported_cards_from_candidates(profiles)
        if not cards:
            keyword = str(question or "").strip()
            if keyword:
                conn = get_conn(dataset)
                cur = conn.cursor()
                try:
                    cur.execute(
                        f"SELECT {_IMPORTED_CARD_COLUMNS} FROM user_profile_vectors "
                        "WHERE profile_text ILIKE %s OR user_id ILIKE %s "
                        "ORDER BY user_id ASC LIMIT %s",
                        (f"%{keyword[:80]}%", f"%{keyword[:80]}%", limit),
                    )
                    cards = [_card_from_profile_row(profile_row(row)) for row in cur.fetchall()]
                finally:
                    conn.rollback()
                    cur.close()
    finally:
        reset_dataset(token)
    return {
        "source": "imported",
        "page": 1,
        "size": limit,
        "total": len(cards),
        "total_pages": 1 if cards else 0,
        "items": cards,
        "mode": "search",
    }


def imported_profile_count(dataset: str) -> int:
    try:
        token = use_dataset(dataset)
        try:
            conn = get_conn(dataset)
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
                return int(cur.fetchone()[0] or 0)
            finally:
                conn.rollback()
                cur.close()
        finally:
            reset_dataset(token)
    except Exception:  # noqa: BLE001
        return 0


# ==================== 千客用户池 ====================

def qianke_profile_page(merchant_id: str, *, page: int = 1, size: int = 12) -> dict[str, Any]:
    page = max(1, int(page or 1))
    size = min(50, max(1, int(size or 12)))
    total = store.count_qianke_user_profiles(merchant_id)
    rows = store.list_qianke_user_profiles(
        merchant_id, limit=size, offset=(page - 1) * size
    )
    return {
        "source": "qianke",
        "page": page,
        "size": size,
        "total": total,
        "total_pages": (total + size - 1) // size if total else 0,
        "items": [_card_from_qianke(row) for row in rows],
        "mode": "list",
    }


def _qianke_embedding(text: str) -> list[float] | None:
    try:
        from rag_demo.c_end.chat_profile import embed_text

        return embed_text(text)
    except Exception:  # noqa: BLE001
        return None


def _keyword_tokens(text: str) -> list[str]:
    """SQLite/纯文本检索的兜底词：优先 ASCII 标识（buyer_1 / qk_u001）。"""
    tokens = re.findall(r"[A-Za-z0-9_]{2,}", str(text or ""))
    result = []
    for token in tokens:
        if token not in result:
            result.append(token)
    return result[:3]


def _search_qianke_rows(
    merchant_id: str, question: str, *, limit: int
) -> list[dict[str, Any]]:
    rows = store.search_qianke_user_profiles(
        merchant_id, question, _qianke_embedding(question), limit=limit
    )
    if rows:
        return rows
    # SQLite 控制面没有向量检索；整句 LIKE 对「buyer_1 想要什么」这类问题
    # 命中不了。退一步用标识/短词再搜一次。
    for token in _keyword_tokens(question):
        rows = store.search_qianke_user_profiles(merchant_id, token, None, limit=limit)
        if rows:
            return rows
    return []


def qianke_profile_search(merchant_id: str, question: str, *, limit: int = 10) -> dict[str, Any]:
    limit = min(20, max(1, int(limit or 10)))
    rows = _search_qianke_rows(merchant_id, question, limit=limit)
    return {
        "source": "qianke",
        "page": 1,
        "size": limit,
        "total": len(rows),
        "total_pages": 1 if rows else 0,
        "items": [_card_from_qianke(row) for row in rows],
        "mode": "search",
    }


def _card_from_qianke(row: dict[str, Any]) -> dict[str, Any]:
    chat = row.get("chat_profile") or {}
    tags: list[str] = []
    for value in (chat.get("needs") or []) + (chat.get("preferences") or []):
        text = str(value or "").strip()
        if text and text not in tags:
            tags.append(text)
    if row.get("top_category"):
        tags.append(str(row["top_category"]))
    return {
        "source": "qianke",
        "user_id": row.get("buyer_id"),
        "display_name": "",
        "tags": tags[:5],
        "stats": {
            "order_count": int(row.get("order_count") or 0),
            "avg_amount": row.get("avg_order_amount"),
            "total_amount": row.get("order_amount"),
            "last_order_at": row.get("last_order_at"),
        },
        "fields": {
            "age": None,
            "gender": None,
            "city": None,
            "member_level": None,
            "top_category": row.get("top_category"),
            "days_since_last_buy": None,
        },
        "chat": chat,
        "confidence": row.get("confidence"),
        "updated_at": row.get("updated_at"),
        "has_order": bool(row.get("has_order")),
        "has_chat": bool(row.get("has_chat")),
    }


def _qianke_candidates(merchant_id: str, question: str, *, limit: int = 5) -> tuple[list[dict], list[dict]]:
    rows = _search_qianke_rows(merchant_id, question, limit=limit)
    candidates = []
    for row in rows:
        text = str(row.get("profile_text") or "").strip()
        if not text:
            continue
        distance = row.get("distance")
        try:
            score = max(0.0, 1.0 - float(distance)) if distance is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0
        candidates.append(
            {
                "id": f"qianke:{row.get('buyer_id')}",
                "source": "qianke_user",
                "text": text,
                "rerank_score": round(score, 4),
                "origin_query": question,
                "from_query": question,
                "strategies": ["千客用户池"],
            }
        )
    return rows, candidates


# ==================== 覆盖说明 ====================

def coverage_note(
    merchant_id: str,
    *,
    imported_ready: bool,
    imported_total: int,
    retrieved_qianke: int,
    retrieved_imported: int,
) -> dict[str, Any]:
    qianke = user_pool.pool_summary(merchant_id)
    note_parts = []
    if qianke.get("count"):
        note_parts.append(
            f"千客用户池共 {qianke['count']} 人（有订单 {qianke['with_orders']} 人、"
            f"有会话 {qianke['with_chat']} 人），本次检索到 {retrieved_qianke} 人"
        )
    else:
        note_parts.append("千客用户池暂无可查用户")
    if imported_ready:
        note_parts.append(
            f"导入用户 {imported_total} 人，本次检索到 {retrieved_imported} 人"
        )
    else:
        note_parts.append("导入用户数据空间尚未构建")
    note_parts.append("不要用检索到的少数用户推算全量；无法确定的统计口径要说明")
    return {
        "qianke": qianke,
        "imported": {
            "ready": imported_ready,
            "total": imported_total,
            "retrieved": retrieved_imported,
        },
        "retrieved_qianke": retrieved_qianke,
        "note": "；".join(note_parts),
    }


# ==================== 问答 ====================

def answer(
    *,
    scope: str,
    question: str,
    merchant_id: str,
    account: dict | None,
    dataset: str | None,
    imported_ready: bool = False,
    imported_total: int = 0,
    profile_limit: int = DEFAULT_PROFILE_LIMIT,
) -> dict[str, Any]:
    """三种范围的问答统一入口；返回 answer/route/sources/cards/coverage。"""
    if scope not in SCOPES:
        raise ValueError(f"未知的查询范围: {scope!r}")
    question = str(question or "").strip()
    persona_prompt, identity, persona_key = persona_context(account)

    def dispatch() -> dict[str, Any]:
        if scope == "qianke":
            return _answer_qianke(
                question, merchant_id, persona_prompt, identity, profile_limit
            )
        if scope == "imported":
            return _answer_imported(
                question,
                dataset,
                persona_prompt,
                identity,
                persona_key,
                profile_limit,
                imported_total,
            )
        return _answer_all(
            question,
            merchant_id,
            dataset,
            imported_ready,
            imported_total,
            persona_prompt,
            identity,
            persona_key,
            profile_limit,
        )

    # 导入侧（answer_question / prepare / 卡片补库）都依赖 contextvar 里的数据集；
    # 千客侧不需要，但 all 需要，所以在入口统一钉住，finally 还原。
    if dataset and scope in {"imported", "all"}:
        token = use_dataset(dataset)
        try:
            return dispatch()
        finally:
            reset_dataset(token)
    return dispatch()


def _answer_qianke(
    question: str,
    merchant_id: str,
    persona_prompt: str,
    identity: dict,
    profile_limit: int,
) -> dict[str, Any]:
    rows, candidates = _qianke_candidates(merchant_id, question, limit=profile_limit)
    coverage = coverage_note(
        merchant_id,
        imported_ready=False,
        imported_total=0,
        retrieved_qianke=len(rows),
        retrieved_imported=0,
    )
    if not candidates:
        return {
            "answer": "根据现有资料无法确定。千客用户池里没有检索到相关用户，可以先刷新用户池或换个问法。",
            "route": "empty",
            "sources": [],
            "cards": [],
            "coverage": coverage,
        }
    note = f"【数据范围】本次只查千客用户（会话 + 交易并集）。{coverage['note']}。"
    try:
        result = generate(
            question,
            candidates,
            memory_context=compose_persona(persona_prompt, note),
        )
    except Exception:  # noqa: BLE001 - LLM 故障给固定文案，不让接口 500
        logger.exception("千客用户问答失败 merchant=%s", merchant_id)
        return {
            "answer": LLM_UNAVAILABLE_REPLY,
            "route": "llm_error",
            "sources": [],
            "cards": [_card_from_qianke(row) for row in rows],
            "coverage": coverage,
        }
    pipeline.apply_answer_guards(question, result)
    _redact_result(result, [c.get("text", "") for c in candidates])
    return {
        **result,
        "cards": [_card_from_qianke(row) for row in rows],
        "coverage": coverage,
        "route": "rag",
    }


def _answer_imported(
    question: str,
    dataset: str | None,
    persona_prompt: str,
    identity: dict,
    persona_key: str,
    profile_limit: int,
    imported_total: int,
) -> dict[str, Any]:
    if not dataset:
        raise ValueError("导入用户查询缺少数据空间")
    result = pipeline.answer_question(
        question,
        profile_limit=profile_limit,
        memory_context=persona_prompt,
        persona_name=identity.get("name"),
        persona_key=persona_key,
        force_rag=True,
        # B 端画像查询显式指定了范围，不能复用通用 /qa 缓存里可能存在的
        # 「闲聊/域外」旧答案（force_rag 也不在缓存键里）。
        use_cache=False,
    )
    _redact_result(result, [s.get("text", "") for s in result.get("sources") or []])
    return {
        **result,
        "cards": [_card_from_user_card(card) for card in result.get("user_cards") or []],
        "coverage": {
            "qianke": {},
            "imported": {
                "ready": True,
                "total": int(imported_total or 0),
                "retrieved": len(result.get("user_cards") or []),
            },
            "retrieved_qianke": 0,
            "note": "本次只查导入用户（商户 CSV 导入画像）；结构化查询（SQL）只覆盖这份数据。",
        },
    }


def _answer_all(
    question: str,
    merchant_id: str,
    dataset: str | None,
    imported_ready: bool,
    imported_total: int,
    persona_prompt: str,
    identity: dict,
    persona_key: str,
    profile_limit: int,
) -> dict[str, Any]:
    imported_prepare: dict[str, Any] | None = None
    if dataset and imported_ready:
        try:
            imported_prepare = pipeline.prepare(
                question,
                profile_limit=profile_limit,
                persona_name=identity.get("name"),
                force_rag=True,
            )
        except Exception:  # noqa: BLE001 - 导入侧失败不能拖垮千客侧
            logger.warning("全部用户：导入侧准备失败 merchant=%s", merchant_id, exc_info=True)
            imported_prepare = None
    qianke_rows, qianke_candidates = _qianke_candidates(
        merchant_id, question, limit=profile_limit
    )
    imported_candidates: list[dict] = []
    sql_result = None
    prepared_answer = ""
    prepared_route = "rag"
    if imported_prepare:
        prepared_route = str(imported_prepare.get("route") or "rag")
        prepared_answer = str(imported_prepare.get("answer") or "")
        imported_candidates = list(imported_prepare.get("candidates") or [])
        sql_result = imported_prepare.get("sql_result")

    candidates = imported_candidates + qianke_candidates
    coverage = coverage_note(
        merchant_id,
        imported_ready=imported_ready,
        imported_total=imported_total,
        retrieved_qianke=len(qianke_rows),
        retrieved_imported=len(imported_candidates),
    )
    if not candidates and not (sql_result and sql_result.get("rows")):
        if prepared_route in {"chitchat", "error"} and prepared_answer:
            return {
                "answer": prepared_answer,
                "route": prepared_route,
                "sources": [],
                "cards": [],
                "coverage": coverage,
            }
        return {
            "answer": "根据现有资料无法确定。可以在「数据接入」里先构建导入用户，或刷新千客用户池。",
            "route": "empty",
            "sources": [],
            "cards": [],
            "coverage": coverage,
        }

    note = (
        "【数据范围】本次同时查千客用户与导入用户。"
        f"{coverage['note']}。结构化查询（SQL）只覆盖导入用户，"
        "引用 SQL 数字时必须说明是导入用户口径。"
    )
    try:
        result = generate(
            question,
            candidates,
            sql_result=sql_result,
            memory_context=compose_persona(persona_prompt, note),
        )
    except Exception:  # noqa: BLE001 - LLM 故障给固定文案，不让接口 500
        logger.exception("全部用户问答失败 merchant=%s", merchant_id)
        return {
            "answer": LLM_UNAVAILABLE_REPLY,
            "route": "llm_error",
            "sources": [],
            "cards": [_card_from_qianke(row) for row in qianke_rows],
            "coverage": coverage,
        }
    pipeline.apply_answer_guards(question, result)
    _redact_result(result, [c.get("text", "") for c in candidates])
    imported_cards = _imported_cards_from_candidates(imported_candidates) if imported_candidates else []
    qianke_cards = [_card_from_qianke(row) for row in qianke_rows]
    return {
        **result,
        "cards": imported_cards + qianke_cards,
        "coverage": coverage,
        "route": "rag",
    }


def _card_from_user_card(card: dict) -> dict:
    """把 pipeline.load_user_cards 的卡片转成 B 端统一卡片结构。"""
    tags = [
        value
        for value in (card.get("member_level"), card.get("city"), card.get("top_category"))
        if value
    ]
    return {
        "source": "imported",
        "user_id": card.get("user_id"),
        "display_name": None,
        "tags": tags,
        "stats": {
            "order_count": int(card.get("order_count") or 0),
            "avg_amount": card.get("avg_amount"),
            "total_amount": card.get("total_amount"),
            "last_order_at": None,
        },
        "fields": {
            "age": card.get("age"),
            "gender": card.get("gender"),
            "city": card.get("city"),
            "member_level": card.get("member_level"),
            "top_category": card.get("top_category"),
            "days_since_last_buy": card.get("days_since_last_buy"),
        },
        "chat": {},
        "confidence": None,
        "updated_at": None,
    }


def _redact_result(result: dict, texts: list[str]) -> None:
    """姓名脱敏：回答正文里出现检索文本中的完整姓名时替换；来源逐条替换。"""
    answer = str(result.get("answer") or "")
    names = {n for n in (extract_profile_name(t) for t in texts) if n}
    for name in names:
        answer = answer.replace(name, mask_name(name))
    if answer:
        result["answer"] = answer
    for source in result.get("sources") or []:
        if isinstance(source, dict) and source.get("text"):
            source["text"] = redact_profile_text(source["text"])


__all__ = [
    "SCOPES",
    "answer",
    "coverage_note",
    "dataset_status",
    "imported_profile_count",
    "imported_profile_page",
    "imported_profile_search",
    "persona_context",
    "qianke_profile_page",
    "qianke_profile_search",
]
