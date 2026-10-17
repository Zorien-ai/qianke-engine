#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : permissions.py
@Function: 角色与访问权限——接口层裁剪的唯一真源

为什么要单独一个模块
--------------------
权限最容易做错的地方不是"能不能判断"，而是**判断散布在多个出口**：
一次问答有 3 个响应出口（`/qa` 直接返回、`/qa/stream` 的 meta、缓存命中直吐），
任何一处忘了裁剪就是一次越权。所以这里提供**唯一**的 `render()`，
所有出口都必须过它。

设计原则（四条，都来自实际踩过的坑）
----------------------------------
1. **裁剪只发生在响应序列化那一刻**，缓存里存的始终是完整结果。
   否则要么按角色重复计算（浪费 LLM 调用），要么低权角色命中高权角色的缓存。
2. **角色不能由调用方自报**——生产环境必须从登录态取。
   本模块接受请求头传来的角色，仅因为当前是 Demo（尚未接入电商系统），
   见 `resolve_role()` 的注释与 README 的权限章节。
3. **普通角色用不了的功能直接不提供**：接口层 403、前端不渲染入口，
   不做"点一下告诉我没权限"那种交互。
4. **`route == "error"` 必须对所有人透出**：数据库挂掉若被裁成普通回复，
   用户会把"服务坏了"当成"资料里没有"（本仓库为此专门加过兜底文案）。

能力（capability）与角色的对应关系见 `_ROLE_CAPS`，与 README 的权限矩阵一一对应。
"""
import re
from typing import Any

# ==================== 角色 ====================

ROLE_ADMIN = "admin"        # 系统管理员
ROLE_EXEC = "exec"          # 管理层
ROLE_ANALYST = "analyst"    # 数据分析师 / 产品
ROLE_OPS = "ops"            # 运营 / 市场
ROLE_CS = "cs"              # 销售 / 客服
ROLE_GUEST = "guest"        # 未识别身份（非法或缺失角色一律降级到这里）

ROLES = (ROLE_ADMIN, ROLE_EXEC, ROLE_ANALYST, ROLE_OPS, ROLE_CS, ROLE_GUEST)

ROLE_LABELS = {
    ROLE_ADMIN: "系统管理员",
    ROLE_EXEC: "管理层",
    ROLE_ANALYST: "数据分析师/产品",
    ROLE_OPS: "运营/市场",
    ROLE_CS: "销售/客服",
    ROLE_GUEST: "未识别身份",
}

# 页面下拉框的顺序：权限从高到低，默认选中最低的可用档（cs），保证页面开箱可用
ROLE_SELECTOR_ORDER = (ROLE_ADMIN, ROLE_EXEC, ROLE_ANALYST, ROLE_OPS, ROLE_CS, ROLE_GUEST)
DEFAULT_UI_ROLE = ROLE_CS

# ==================== 能力 ====================

CAP_ANSWER = "answer"          # 能提问（业务问答）
CAP_SOURCES = "sources"        # 能看到来源列表（编号 + 来源名）
CAP_SQL = "sql"                # 能看到 SQL 原文与结果行（仅管理员，见 README 权限矩阵）
CAP_INTERNALS = "internals"    # 能看到 trace / 原文片段 / 精排分数 / 检索式
CAP_TRACE_FLOW = "trace_flow"  # 能看到「融合与精排」汇总：融合条数 / 各池名额 / 画像池基数
CAP_STATS = "stats"            # 能看到 /stats 数据概况
CAP_RAW_SEARCH = "raw_search"  # 能调用 /search（只召回不生成，最敏感）
CAP_OPS = "ops"                # 能调用 /admin/*（清缓存、重建索引）
CAP_TOPK = "topk"              # 能调整"返回多少个用户"

# 角色 -> 能力。与 README「权限矩阵」严格对应，改一处要改另一处。
_ROLE_CAPS: dict[str, frozenset[str]] = {
    ROLE_ADMIN: frozenset({
        CAP_ANSWER, CAP_SOURCES, CAP_SQL, CAP_INTERNALS, CAP_TRACE_FLOW,
        CAP_STATS, CAP_RAW_SEARCH, CAP_OPS, CAP_TOPK,
    }),
    ROLE_EXEC: frozenset({CAP_ANSWER, CAP_SOURCES, CAP_INTERNALS, CAP_TOPK}),
    ROLE_ANALYST: frozenset({CAP_ANSWER, CAP_SOURCES, CAP_TOPK}),
    ROLE_OPS: frozenset({CAP_ANSWER, CAP_SOURCES, CAP_TOPK}),
    ROLE_CS: frozenset({CAP_ANSWER}),
    # 未识别身份：连业务问答都不给——后端不知道你是谁，就不该吐业务数据
    ROLE_GUEST: frozenset(),
}

# 能调 top_k 的最低角色（README：「运营以上可调」）
TOPK_ROLES = frozenset({ROLE_ADMIN, ROLE_EXEC, ROLE_ANALYST, ROLE_OPS})

# 「来源N」引用标记：低权角色看不到来源列表时，留着这些标记反而像坏了
_CITE_RE = re.compile(r"\[来源\s*\d+\]")

# 无权限时的统一文案。
# 刻意不透露"有什么功能被挡住了"——普通角色用不了的能力是**不设计**，
# 而不是"设计了再告诉他没权限"（那样等于把内部功能清单报给每个人）。
FORBIDDEN_DETAIL = "当前身份无权访问该接口"


def resolve_role(value: str | None, default: str = ROLE_GUEST) -> str:
    """
    把外部传入的角色标识解析成合法角色

    - **请求头缺失**（value 为 None 或空白）→ 返回 `default`
    - **请求头是非法值**（如 "root"、"admin2"）→ 一律降级为 guest，不放行

    两种情况必须区分开：缺失代表"调用方没带身份"，非法代表"调用方编了一个身份"。
    后者按 guest 处理，绝不允许落到有权限的角色上。

    ⚠ Demo 阶段角色由请求头 `X-Role` 传入，**调用方可以自报**——这在生产是不可接受的
    （等同于 ODD-09 那个"dept 由调用方自报"的越权口子）。接入电商系统后必须改为
    「登录态 → 角色」，并把 `default` 从 admin 改成 guest。届时删掉 API 层的 Header
    依赖即可，本模块的接口不用动。
    """
    if value is None or not str(value).strip():
        return default
    role = str(value).strip().lower()
    return role if role in ROLES else ROLE_GUEST


def capabilities(role: str) -> frozenset[str]:
    """角色 -> 能力集合（非法角色按 guest 处理）"""
    return _ROLE_CAPS.get(role, _ROLE_CAPS[ROLE_GUEST])


def has(role: str, cap: str) -> bool:
    return cap in capabilities(role)


def allowed_topk_roles() -> list[str]:
    """能调 top_k 的角色（按选择器顺序，供前端展示）"""
    return [r for r in ROLE_SELECTOR_ORDER if r in TOPK_ROLES]


def describe(role: str) -> dict[str, Any]:
    """给前端的自描述：前端据此决定渲染什么，不在前端硬编码权限表"""
    caps = capabilities(role)
    return {
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "capabilities": sorted(caps),
        "can": {
            "ask": CAP_ANSWER in caps,
            "sources": CAP_SOURCES in caps,
            "sql": CAP_SQL in caps,
            "internals": CAP_INTERNALS in caps,
            "trace_flow": CAP_TRACE_FLOW in caps,
            "stats": CAP_STATS in caps,
            "raw_search": CAP_RAW_SEARCH in caps,
            "ops": CAP_OPS in caps,
            "topk": CAP_TOPK in caps,
        },
    }


# ==================== 响应裁剪（唯一出口） ====================

def answer_for(text: str, role: str) -> str:
    """
    按角色处理回答正文

    看不到来源列表的角色，正文里的 `[来源N]` 指向一个他看不见的东西——
    留着比去掉更糟（看着像功能坏了）。这里只去掉**编号引用**，
    `[来源：结构化查询结果]` 这类散文式标注不去（它本身自解释）。

    注意：流式接口不用这个函数。delta 是逐片吐的，引用标记可能被切成两片，
    服务端按片正则匹配会漏；那一路改由前端按 `can.sources` 处理（见 app.js）。
    """
    if CAP_SOURCES in capabilities(role):
        return text or ""
    return _CITE_RE.sub("", text or "")


def _render_source(src: dict, caps: frozenset[str]) -> dict:
    """层级：L1 只给编号与来源名；L3 才给原文片段、分数与命中路径"""
    out = {"index": src.get("index"), "source": src.get("source")}
    if CAP_INTERNALS in caps:
        out.update({
            "text": src.get("text", ""),
            "origin_query": src.get("origin_query", ""),
            "from_query": src.get("from_query", ""),
            "strategies": src.get("strategies", []),
            "rerank_score": src.get("rerank_score"),
            "expanded": src.get("expanded", False),
        })
    return out


# 「融合与精排」靠这几个汇总字段渲染：融合条数 / 各池名额 / 画像池基数。
# 它们是 trace 的一部分，但权限级别比「各路检索式」更高（管理员专属），
# 所以单独挑出来，而不是把整个 trace 一起裁掉——否则 exec 连「走的路径」都没了。
_TRACE_FLOW_KEYS = ("fused_count", "limits", "profile_pool_count", "wiki_doc_dedup")


def _render_trace(trace: dict, caps: frozenset[str]) -> dict:
    """trace 内部再分级：L3 拿各路明细，管理员额外拿融合汇总"""
    out = dict(trace)
    if CAP_TRACE_FLOW not in caps:
        for key in _TRACE_FLOW_KEYS:
            out.pop(key, None)
    return out


def render(payload: dict, role: str) -> dict:
    """
    按角色裁剪一次问答的响应（**所有出口都必须过这里**）

    被裁掉的字段不是"置空"，而是**整键移除**——前端拿不到就不会渲染，
    也不会有人误以为"有值但没显示"。

    `route` 无条件保留：error / chitchat 这两种走向本身就是用户必须知道的信息。
    """
    caps = capabilities(role)
    out: dict[str, Any] = {"route": payload.get("route")}

    if "answer" in payload:
        out["answer"] = answer_for(payload.get("answer") or "", role)

    if "cached" in payload:
        out["cached"] = payload["cached"]

    if CAP_SOURCES in caps and payload.get("sources") is not None:
        out["sources"] = [_render_source(s, caps) for s in payload["sources"]]

    if CAP_SQL in caps:
        for key in ("sql", "rows_count", "sql_rows", "sql_error"):
            if key in payload:
                out[key] = payload[key]

    if CAP_INTERNALS in caps and payload.get("trace") is not None:
        out["trace"] = _render_trace(payload["trace"], caps)

    return out


# ==================== top_k 的权限收窄 ====================

def clamp_top_k(role: str, value: int | None, max_value: int, min_value: int = 1) -> int | None:
    """
    收窄用户传的 top_k

    - 无权限的角色：**忽略**传值，返回 None（走系统默认），而不是报错——
      报错等于告诉对方"这里有个参数你能用"，属于多余的信息暴露
    - 有权限的角色：夹到 [min_value, max_value]，超出上限按上限处理
    """
    if value is None or not has(role, CAP_TOPK):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return max(min_value, min(n, max_value))
