# -*- coding: utf-8 -*-
"""千人千面营销文案生成。

核心红线：
1. 画像只取当前 dataset 中、属于当前账号可见范围的 user_id；
2. 金额/折扣/有效期等硬指标必须来自文档轨检索到的 SOP 文本；
3. 生成后再次做数字校验，文档没有的数字一律不允许留在文案里。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rag_demo import config
from rag_demo.db.connection import get_conn
from rag_demo.retrieval.hybrid_retriever import hybrid_search

DOC_DIR = Path(config.BASE_DIR) / "data" / "docs"
USER_ID_RE = re.compile(r"^U\d{3,12}$")
HARD_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:元|折|天|小时|分钟|%|倍|积分)")
DOC_KEYWORDS = ("黑卡", "召回", "优惠", "券", "权益", "SOP", "活动", "折扣", "满减", "有效期")

STYLE_SPECS = [
    ("warm", "温情召唤风"),
    ("urgent", "紧迫促销风"),
    ("exclusive", "尊贵专属风"),
]

SYSTEM_PROMPT = """你是一位资深电商营销专家，擅长为高价值会员写一对一触达短信。

你必须严格遵守：
1. 只能使用【用户特征】和【文档事实】中明确出现的信息；
2. 金额、折扣、券面额、有效期、频控、时间等硬指标，必须逐字来自【文档事实】；
   文档没有写具体金额/折扣/时间，就绝对不要写任何具体数字；
3. 不得编造权益、活动名、品牌名、截止时间、券额；
4. 不得输出用户姓名、手机号、身份证等敏感信息；
5. 尊贵称谓来自会员等级；不知道等级时用「亲爱的会员」；
6. 只输出一个 JSON 对象，不要 Markdown、不要解释，格式：
{
  "variants": [
    {"style": "warm", "label": "温情召唤风", "sms": "……", "basis": "引用了哪条文档事实"},
    {"style": "urgent", "label": "紧迫促销风", "sms": "……", "basis": "..."},
    {"style": "exclusive", "label": "尊贵专属风", "sms": "……", "basis": "..."}
  ]
}
每条短信 45–120 个中文字符，不要换行，不要出现「【】」占位符。"""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _read_doc_file(name: str) -> str:
    path = DOC_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _doc_hits(question: str) -> list[dict]:
    """先走混合检索；再补上关键 SOP 文件，保证权益条件不会因召回漏掉。"""
    hits: list[dict] = []
    try:
        for hit in hybrid_search(f"{question} 营销 召回 权益 优惠券 权益条件", top_k=24):
            source = _clean(hit.get("source"))
            text = _clean(hit.get("text"))
            if source.lower().endswith(".md") and text:
                hits.append({"source": source, "text": text})
    except Exception:  # noqa: BLE001 文档检索失败时仍可用本地关键文件兜底
        pass

    # 权益类文档必须参与：不能因为向量召回没命中就当成"没有规则"
    for name in ("black_card_sop.md", "marketing_playbook.md", "member_benefits.md", "cs_sop.md"):
        text = _read_doc_file(name)
        if text:
            hits.append({"source": name, "text": text})
    return hits


def _effective_docs(hits: list[dict]) -> list[dict]:
    """同一文件名优先保留完整文件内容，避免检索出来的 400 字截断丢掉权益行。"""
    by_source: dict[str, str] = {}
    for hit in hits:
        source = hit["source"]
        text = hit["text"]
        if len(text) > len(by_source.get(source, "")):
            by_source[source] = text
    return [{"source": source, "text": text} for source, text in by_source.items()]


def extract_facts(docs: list[dict]) -> list[dict]:
    """提取文档里的硬指标 token + 上下文，供 Prompt 和后置校验共用。"""
    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for doc in docs:
        source = doc["source"]
        for line in doc["text"].splitlines():
            line = line.strip()
            if not line or not any(k in line for k in DOC_KEYWORDS):
                continue
            for match in HARD_TOKEN_RE.finditer(line):
                token = re.sub(r"\s+", "", match.group(0))
                key = (source, token)
                if key in seen:
                    continue
                seen.add(key)
                facts.append({
                    "token": token,
                    "source": source,
                    "snippet": line[:220],
                })
    return facts


def _load_profiles(user_ids: list[str]) -> list[dict]:
    ids = []
    for uid in user_ids:
        uid = _clean(uid)
        if not USER_ID_RE.match(uid):
            continue
        if uid not in ids:
            ids.append(uid)
    ids = ids[:10]
    if not ids:
        raise ValueError("没有可用的用户 ID，请先在对话中列出目标人群")
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT user_id, city, member_level, gender, age,
                      order_count, avg_amount::float8, top_category,
                      days_since_last_buy
               FROM user_profile_vectors
               WHERE user_id = ANY(%s)
               ORDER BY avg_amount DESC NULLS LAST
               LIMIT 10""",
            (ids,),
        )
        rows = cur.fetchall()
    finally:
        conn.rollback()
        cur.close()
    if not rows:
        raise ValueError("传入的用户 ID 不在当前数据空间，或当前账号无权访问")
    profiles = []
    for row in rows:
        profiles.append({
            "user_id": row[0],
            "city": row[1],
            "member_level": row[2],
            "gender": row[3],
            "age": row[4],
            "order_count": row[5],
            "avg_amount": round(float(row[6] or 0), 2),
            "top_category": row[7],
            "days_since_last_buy": row[8],
        })
    return profiles


def _honorific(profiles: list[dict]) -> str:
    levels = [p.get("member_level") for p in profiles if p.get("member_level")]
    if not levels:
        return "亲爱的会员"
    # 取最高频等级；黑卡等前缀保留
    level = max(set(levels), key=levels.count)
    return f"尊贵的{level}会员"


def _profile_features(profiles: list[dict]) -> dict:
    categories = [p.get("top_category") for p in profiles if p.get("top_category")]
    cities = [p.get("city") for p in profiles if p.get("city")]
    return {
        "count": len(profiles),
        "cities": sorted(set(cities)),
        "levels": sorted({p.get("member_level") for p in profiles if p.get("member_level")}),
        "categories": sorted(set(categories)),
        "avg_amount_range": (
            min(p["avg_amount"] for p in profiles),
            max(p["avg_amount"] for p in profiles),
        ),
        "honorific": _honorific(profiles),
    }


def _build_prompt(question: str, profiles: list[dict], facts: list[dict], docs: list[dict]) -> list[dict]:
    feature = _profile_features(profiles)
    facts_text = "\n".join(
        f"- {f['token']} | 来源 {f['source']} | {f['snippet']}" for f in facts
    ) or "（文档没有提供任何金额/折扣/有效期等硬指标；禁止编造任何数字）"
    docs_text = "\n\n".join(f"### {d['source']}\n{d['text'][:1800]}" for d in docs[:4])
    user_payload = {
        "用户特征": {
            "人数": feature["count"],
            "城市": feature["cities"],
            "会员等级": feature["levels"],
            "偏好品类": feature["categories"],
            "尊贵称谓": feature["honorific"],
        },
        "文档事实（唯一可用的权益依据）": facts_text,
        "文档原文": docs_text,
        "原始问题": question,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请为下面这群用户各写 3 条不同风格的召回短信。\n\n"
                + json.dumps(user_payload, ensure_ascii=False, indent=2)
                + "\n\n只输出 JSON。"
            ),
        },
    ]


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError("营销文案输出不是合法 JSON")


def validate_variants(variants: list[dict], facts: list[dict], honorific: str) -> tuple[list[dict], list[dict]]:
    """返回（合法文案，被拦截项）。文档没有的数字 token 一律拦截。"""
    allowed = {f["token"] for f in facts}
    valid: list[dict] = []
    rejected: list[dict] = []
    for raw in variants:
        if not isinstance(raw, dict):
            continue
        sms = _clean(raw.get("sms") or raw.get("content"))
        if not sms:
            continue
        tokens = {re.sub(r"\s+", "", m.group(0)) for m in HARD_TOKEN_RE.finditer(sms)}
        bad = sorted(t for t in tokens if t not in allowed)
        if bad:
            rejected.append({"sms": sms, "bad_tokens": bad, "reason": "出现文档未提供的硬指标"})
            continue
        style = _clean(raw.get("style"))
        if style not in {s[0] for s in STYLE_SPECS}:
            style = ""
        valid.append({
            "style": style,
            "label": _clean(raw.get("label")) or _label_for(style),
            "sms": sms,
            "basis": _clean(raw.get("basis")),
        })
    return valid, rejected


def _label_for(style: str) -> str:
    for key, label in STYLE_SPECS:
        if key == style:
            return label
    return "营销文案"


def _fallback_variants(honorific: str, categories: list[str]) -> list[dict]:
    category = categories[0] if categories else "专属"
    return [
        {"style": "warm", "label": "温情召唤风",
         "sms": f"{honorific}，感谢您一直以来的信任。{category}专属礼遇已为您准备，期待继续为您服务。",
         "basis": "无具体权益数字，使用通用关怀文案"},
        {"style": "urgent", "label": "紧迫促销风",
         "sms": f"{honorific}，您的{category}专属权益已就绪，别让这份心意等太久，期待您的到来。",
         "basis": "无具体权益数字，使用通用提醒文案"},
        {"style": "exclusive", "label": "尊贵专属风",
         "sms": f"{honorific}，{category}甄选体验为您开启，愿每一次选择都配得上您的品味。",
         "basis": "无具体权益数字，使用通用尊享文案"},
    ]


def generate_copy(question: str, user_ids: list[str]) -> dict:
    profiles = _load_profiles(user_ids)
    docs = _effective_docs(_doc_hits(question))
    # 黑卡用户以黑卡专属 SOP 为唯一权益依据，避免模型拿其他等级的 50/200 元券串台
    if any("黑卡" in str(p.get("member_level") or "") for p in profiles):
        black_docs = [d for d in docs if d["source"] == "black_card_sop.md"]
        if black_docs:
            docs = black_docs
    facts = extract_facts(docs)
    honorific = _honorific(profiles)
    categories = _profile_features(profiles)["categories"]
    messages = _build_prompt(question, profiles, facts, docs)

    from rag_demo.generation.generator import chat_completion

    resp = chat_completion(
        messages,
        temperature=0.55,
        max_tokens=1400,
        deep_thinking=False,
        response_format={"type": "json_object"},
    )
    raw_text = (resp.choices[0].message.content or "").strip()
    parsed = _parse_json(raw_text)
    raw_variants = parsed.get("variants") if isinstance(parsed, dict) else None
    if not isinstance(raw_variants, list):
        raw_variants = []
    valid, rejected = validate_variants(raw_variants, facts, honorific)

    # 保证始终有 3 种风格；缺失的用无金额兜底模板，不调用第二次模型
    by_style = {v.get("style"): v for v in valid if v.get("style")}
    fallback = _fallback_variants(honorific, categories)
    for item in fallback:
        if item["style"] not in by_style:
            by_style[item["style"]] = item
    variants = [by_style[key] for key, _ in STYLE_SPECS]
    degraded = bool(rejected) or not raw_variants or len(valid) < 3
    return {
        "variants": variants,
        "facts": facts[:30],
        "profiles": profiles,
        "doc_sources": [{"source": d["source"], "snippet": d["text"][:220]} for d in docs[:6]],
        "guard": {
            "degraded": degraded,
            "rejected_count": len(rejected),
            "rejected": rejected[:5],
            "allowed_tokens": sorted({f["token"] for f in facts}),
            "honorific": honorific,
        },
    }


__all__ = [
    "extract_facts",
    "generate_copy",
    "validate_variants",
    "STYLE_SPECS",
]
