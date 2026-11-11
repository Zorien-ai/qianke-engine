"""B 端会话用户画像：从 C 买家 ↔ 商家店宠会话抽取结构化画像。

只处理店宠/客服会话（v1 固定 store_demo / m_gear_002）；
30 分钟无新消息后由扫描任务触发；画像不反写 C 长期记忆。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from rag_demo.c_end import social, store
from rag_demo.c_end import store_agent

logger = logging.getLogger(__name__)

STORE_FRIEND_ID = "store_demo"
STORE_MERCHANT_ID = store_agent.STORE_MERCHANT_ID
DEFAULT_STORE_FRIEND_ID = STORE_FRIEND_ID
DEFAULT_MERCHANT_ID = STORE_MERCHANT_ID
IDLE_MINUTES = 30
PROFILE_MAX_MESSAGES = 200
_PII_RE = re.compile(
    r"\b1[3-9]\d{9}\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\b\d{17}[\dXx]\b|\b\d{16,19}\b"
)

ProfileLLM = Callable[[list[dict[str, str]]], str]
ProfileEmbedder = Callable[[str], list[float] | None]


def _fallback_llm(messages: list[dict[str, str]]) -> str:
    from rag_demo.generation.generator import chat_completion

    response = chat_completion(
        messages,
        temperature=0,
        max_tokens=500,
        deep_thinking=False,
        feature="b_chat_profile",
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    return str(getattr(choices[0].message, "content", "") or "")


def _clean_list(values: Any, *, limit: int = 10, max_len: int = 40) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split())[:max_len]
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _clean_sizes(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    result = {}
    for key, value in values.items():
        key_text = " ".join(str(key or "").split())[:20]
        value_text = " ".join(str(value or "").split())[:20]
        if key_text and value_text:
            result[key_text] = value_text
    return result


def normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    confidence = data.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "needs": _clean_list(data.get("needs")),
        "preferences": _clean_list(data.get("preferences")),
        "boundaries": _clean_list(data.get("boundaries")),
        "budget": " ".join(str(data.get("budget") or "").split())[:40],
        "sizes": _clean_sizes(data.get("sizes")),
        "purchase_stage": " ".join(str(data.get("purchase_stage") or "").split())[:40],
        "open_questions": _clean_list(data.get("open_questions"), limit=5),
        "confidence": confidence,
    }


def profile_to_text(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    if profile.get("needs"):
        parts.append("需求：" + "、".join(profile["needs"]))
    if profile.get("preferences"):
        parts.append("偏好：" + "、".join(profile["preferences"]))
    if profile.get("boundaries"):
        parts.append("边界：" + "、".join(profile["boundaries"]))
    if profile.get("budget"):
        parts.append("预算：" + str(profile["budget"]))
    if profile.get("sizes"):
        parts.append("尺码：" + "；".join(f"{k}={v}" for k, v in profile["sizes"].items()))
    if profile.get("purchase_stage"):
        parts.append("阶段：" + str(profile["purchase_stage"]))
    if profile.get("open_questions"):
        parts.append("未决问题：" + "、".join(profile["open_questions"]))
    return "；".join(parts)[:800]


def _transcript(owner_id: str, messages: list[dict[str, Any]]) -> str:
    lines = []
    for item in messages[-PROFILE_MAX_MESSAGES:]:
        content = " ".join(str(item.get("content") or "").split())
        if not content:
            continue
        sender = str(item.get("sender_id") or "")
        role = "用户" if sender == owner_id else "店宠"
        lines.append(f"{role}：{content[:500]}")
    return "\n".join(lines)[-8000:]


def extract_profile(
    owner_id: str,
    messages: list[dict[str, Any]],
    *,
    llm: ProfileLLM | None = None,
) -> dict[str, Any] | None:
    transcript = _transcript(owner_id, messages)
    if not transcript:
        return None
    prompt = [
        {
            "role": "system",
            "content": (
                "你是商家店宠的画像抽取器。只根据对话中用户明确说过的内容输出 JSON，"
                "不要推测健康、宗教、政治、性取向；不要输出手机号/邮箱/地址/证件号。"
                "字段：needs, preferences, boundaries, budget, sizes, purchase_stage, "
                "open_questions, confidence（0-1）。没有证据的字段留空。只输出 JSON。"
            ),
        },
        {"role": "user", "content": f"对话：\n{transcript}"},
    ]
    try:
        raw = (llm or _fallback_llm)(prompt)
        match = re.search(r"\{.*\}", str(raw or ""), flags=re.S)
        if not match:
            return None
        parsed = json.loads(match.group(0))
        profile = normalize_profile(parsed)
        if _PII_RE.search(json.dumps(profile, ensure_ascii=False)):
            return None
        if not any(profile.get(key) for key in ("needs", "preferences", "boundaries", "budget", "sizes", "purchase_stage")):
            return None
        return profile
    except Exception:  # noqa: BLE001 - 抽取失败不阻塞任务
        logger.warning("B 端画像抽取失败 owner=%s", owner_id, exc_info=True)
        return None


_LOCAL_EMBEDDER = None


def embed_text(text: str) -> list[float]:
    """远程 BGE 或本地 bge-m3；供画像写入和查询共用。"""
    from rag_demo.config import MODEL_API_BASE, MODEL_PATH

    if MODEL_API_BASE:
        from rag_demo.retrieval.remote_models import RemoteEmbedding

        return [float(x) for x in RemoteEmbedding().encode(text)]
    global _LOCAL_EMBEDDER
    if _LOCAL_EMBEDDER is None:
        from sentence_transformers import SentenceTransformer

        _LOCAL_EMBEDDER = SentenceTransformer(MODEL_PATH)
    return [float(x) for x in _LOCAL_EMBEDDER.encode(text)]


def _embed(profile_text: str) -> list[float] | None:
    try:
        return embed_text(profile_text)
    except Exception:  # noqa: BLE001 - embedding 失败仍可保存画像正文
        logger.warning("B 端画像 embedding 失败", exc_info=True)
        return None


def resolve_scope(
    *,
    friend_id: str | None = None,
    merchant_id: str | None = None,
) -> dict[str, Any] | None:
    """把店宠 friend_id 或商家映射成 (merchant_id, friend_id)。"""
    mappings = store.list_store_friend_mappings()
    if friend_id:
        for mapping in mappings:
            if str(mapping.get("friend_id")) == str(friend_id):
                if merchant_id and str(mapping.get("merchant_id")) != str(merchant_id):
                    return None
                return mapping
        return None
    if merchant_id:
        for mapping in mappings:
            if str(mapping.get("merchant_id")) == str(merchant_id):
                return mapping
        return None
    # 兼容旧调用：没有显式 scope 时使用默认店宠。
    for mapping in mappings:
        if str(mapping.get("friend_id")) == DEFAULT_STORE_FRIEND_ID:
            return mapping
    if any(str(item.get("merchant_id")) == DEFAULT_MERCHANT_ID for item in mappings):
        return {"merchant_id": DEFAULT_MERCHANT_ID, "friend_id": DEFAULT_STORE_FRIEND_ID}
    return None


def extract_for_owner(
    owner_id: str,
    *,
    friend_id: str | None = None,
    merchant_id: str | None = None,
    now: datetime | None = None,
    llm: ProfileLLM | None = None,
    embedder: ProfileEmbedder | None = None,
) -> dict[str, Any]:
    scope = resolve_scope(friend_id=friend_id, merchant_id=merchant_id)
    if scope is None:
        return {
            "owner_id": owner_id,
            "ok": False,
            "reason": "NO_MERCHANT",
            "friend_id": friend_id or "",
            "merchant_id": merchant_id or "",
        }
    resolved_merchant = str(scope["merchant_id"])
    resolved_friend = str(scope["friend_id"])
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(minutes=IDLE_MINUTES)).isoformat()
    messages = social.get_messages(owner_id, resolved_friend, limit=PROFILE_MAX_MESSAGES)
    if not messages:
        return {
            "owner_id": owner_id,
            "ok": False,
            "reason": "NO_MESSAGES",
            "friend_id": resolved_friend,
            "merchant_id": resolved_merchant,
        }
    last_at = str(messages[-1].get("created_at") or "")
    if last_at > cutoff:
        return {
            "owner_id": owner_id,
            "ok": False,
            "reason": "NOT_IDLE",
            "friend_id": resolved_friend,
            "merchant_id": resolved_merchant,
        }
    existing = store.get_chat_user_profile(resolved_merchant, owner_id)
    if existing and int(existing.get("source_message_count") or 0) >= len(messages):
        # 老画像或 embedding 失败时，空闲扫描顺手补向量，不改画像内容。
        if not store.has_chat_user_profile_vector(str(existing["profile_id"])):
            text = str(existing.get("profile_text") or "")
            embedding = (embedder or _embed)(text) if text else None
            if embedding:
                store.upsert_chat_user_profile(
                    resolved_merchant,
                    owner_id,
                    profile=existing.get("profile") or {},
                    profile_text=text,
                    confidence=float(existing.get("confidence") or 0),
                    source_message_count=int(existing.get("source_message_count") or 0),
                    source_session_ids=existing.get("source_session_ids") or [],
                    last_message_at=existing.get("last_message_at"),
                    embedding=embedding,
                )
                return {
                    "owner_id": owner_id,
                    "ok": True,
                    "reason": "VECTOR_BACKFILL",
                    "friend_id": resolved_friend,
                    "merchant_id": resolved_merchant,
                }
        return {
            "owner_id": owner_id,
            "ok": False,
            "reason": "NO_NEW_MESSAGES",
            "friend_id": resolved_friend,
            "merchant_id": resolved_merchant,
        }
    profile = extract_profile(owner_id, messages, llm=llm)
    if profile is None:
        return {
            "owner_id": owner_id,
            "ok": False,
            "reason": "EXTRACT_EMPTY",
            "friend_id": resolved_friend,
            "merchant_id": resolved_merchant,
        }
    text = profile_to_text(profile)
    embedding = (embedder or _embed)(text) if text else None
    saved = store.upsert_chat_user_profile(
        resolved_merchant,
        owner_id,
        profile=profile,
        profile_text=text,
        confidence=float(profile.get("confidence") or 0),
        source_message_count=len(messages),
        source_session_ids=[str(item.get("message_id") or "") for item in messages[-20:]],
        last_message_at=last_at,
        embedding=embedding,
    )
    return {
        "owner_id": owner_id,
        "ok": True,
        "friend_id": resolved_friend,
        "merchant_id": resolved_merchant,
        "profile": saved,
    }


def run_idle_profiles(
    *,
    now: datetime | None = None,
    limit: int = 200,
    llm: ProfileLLM | None = None,
    embedder: ProfileEmbedder | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(minutes=IDLE_MINUTES)).isoformat()
    mappings = store.list_store_friend_mappings()
    if not mappings:
        mappings = [{"merchant_id": DEFAULT_MERCHANT_ID, "friend_id": DEFAULT_STORE_FRIEND_ID}]
    results: list[dict[str, Any]] = []
    checked = 0
    for mapping in mappings:
        friend_id = str(mapping.get("friend_id") or "")
        merchant_id = str(mapping.get("merchant_id") or "")
        owners = social.list_idle_store_owners(cutoff, friend_id, limit=limit)
        checked += len(owners)
        results.extend(
            extract_for_owner(
                owner,
                friend_id=friend_id,
                merchant_id=merchant_id,
                now=current,
                llm=llm,
                embedder=embedder,
            )
            for owner in owners
        )
    return {
        "checked": checked,
        "ok": sum(1 for item in results if item.get("ok")),
        "skipped": sum(1 for item in results if not item.get("ok")),
        "merchants": len({item.get("merchant_id") for item in results if item.get("merchant_id")}),
        "results": results,
    }
