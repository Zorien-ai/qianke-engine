#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : main.py
@Function: FastAPI 编排层：交互页面 + 问答接口 + 数据概况

启动（项目根目录下执行）：
    uvicorn rag_demo.api.main:app --reload --port 8000

访问：
    http://127.0.0.1:8000/       交互页面
    http://127.0.0.1:8000/docs   API 文档（config.ENABLE_API_DOCS 可关）
    http://127.0.0.1:8000/health 健康检查
    http://127.0.0.1:8000/whoami 当前角色的能力清单（前端据此渲染）

权限（Demo 过渡态，详见 README「角色与访问权限」）：
    角色由请求头 `X-Role` 传入：admin / exec / analyst / ops / cs / guest，
    交互页面可切换。⚠ **调用方可以自报身份，这不是安全边界**，只是演示开关——
    接入电商系统后角色必须来自登录态，见 config.DEFAULT_API_ROLE 的说明。

前置条件：
    1. PostgreSQL(pgvector) 已启动，且已跑过 ingest_data.py 与 ingest_docs.py
    2. 环境变量 DEEPSEEK_API_KEY 已设置

首次请求会加载 bge-m3 与 bge-reranker-v2-m3（约 2GB 显存），启动时已预加载。
"""
import json
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import APIError
from pydantic import BaseModel

from rag_demo import permissions
from rag_demo.cache import answer_cache
from rag_demo.config import (
    DEFAULT_API_ROLE,
    ENABLE_API_DOCS,
    TOP_K_PROFILE_MAX,
    TOP_K_PROFILE_MIN,
)
from rag_demo.db.connection import close_conn, get_conn
from rag_demo.generation.generator import generate_stream
from rag_demo.logging_setup import setup_logging
from rag_demo.pipeline import answer_question, brief_rows, prepare
from rag_demo.prompts import LLM_UNAVAILABLE_REPLY
from rag_demo.retrieval.hybrid_retriever import (
    _load_bm25_corpus,
    bm25_search,
    get_model,
    reload_bm25,
    sparse_search,  # 可能为 None（FlagEmbedding 未安装时降级）
)

# 控制台 + logs/rag_demo.log 双通道（此前只打屏，服务跑后台日志就丢了）
setup_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ================= 角色与权限 =================
# ⚠ 角色来源目前是**请求头**，即调用方可自报。这不是安全边界，是演示开关：
#   接入电商系统后必须改为「登录态 → 角色」，并把 config.DEFAULT_API_ROLE 改成 guest。
ROLE_HEADER = "X-Role"


def _role(x_role: str | None) -> str:
    """解析请求角色：缺失走兜底（config.DEFAULT_API_ROLE），非法降级 guest"""
    return permissions.resolve_role(x_role, default=DEFAULT_API_ROLE)


def _require(role: str, cap: str) -> None:
    """
    能力校验：不满足就 403

    用 403 而不是 404/静默忽略——调用方明确知道"这条路不通"，
    比"看起来成功了但字段没了"更容易排查。
    """
    if not permissions.has(role, cap):
        logger.warning("权限拦截: role=%s 缺少能力 %s", role, cap)
        raise HTTPException(status_code=403, detail=permissions.FORBIDDEN_DETAIL)


def _warmup_sparse() -> None:
    """
    后台预热稀疏模型

    BGEM3 模型首次加载实测要多付约 4s（相比 BM25 路径）。
    若等到用户第一次点「稀疏向量」才加载，那次请求会明显卡顿——
    这曾被误读成「两者组合比稀疏向量更快」的假象。

    放在后台线程预热：既不阻塞服务启动，又让首个 sparse 请求就是热态。
    注意：索引数据现在留在库内（search_index 表），无需预热，这里预热的是模型。
    """
    try:
        from rag_demo.retrieval.sparse_retriever import prewarm

        prewarm()
        logger.info("稀疏模型预热完成")
    except Exception as e:  # 预热失败不影响主流程，首次调用时会再试
        logger.warning("稀疏模型预热失败（不影响使用，首次调用时会重试）: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预加载模型与索引，避免首个请求等待过久"""
    # 这里再配置一次日志：模块导入时那次执行早于 uvicorn 的 dictConfig，
    # 而 uvicorn 会重置自己那几个 logger 的 handler。不在这里补挂，
    # 「启动信息 + 谁在什么时候请求了什么」就不会落盘。
    setup_logging()
    logger.info("预加载模型和 BM25 语料...")
    get_model()
    _load_bm25_corpus()
    logger.info("预加载完成")

    # 稀疏索引放后台预热：不拖慢启动，但让首个 sparse 请求即热态
    if sparse_search is not None:
        threading.Thread(target=_warmup_sparse, daemon=True).start()
        logger.info("稀疏索引正在后台预热...")

    yield
    close_conn()


app = FastAPI(
    title="用户画像 RAG Demo",
    lifespan=lifespan,
    # 生产环境关掉：/docs 与 /openapi.json 会一次性暴露所有接口与字段结构
    **({} if ENABLE_API_DOCS else {
        "docs_url": None, "redoc_url": None, "openapi_url": None,
    }),
)


# ================= 请求 / 响应模型 =================
class QueryRequest(BaseModel):
    question: str
    dept: str | None = None
    # 「返回多少个用户」的上限（画像条数）。None = 走系统默认（不额外截断）。
    # 只有运营及以上角色能生效，其余角色的传值会被静默忽略（见 permissions.clamp_top_k）。
    #
    # 改造前这个字段是 `top_k: int = 5` 但**整条链路没有任何地方用它**——
    # 收了参数却完全忽略，比不收更糟：调用方以为生效了。
    top_k: int | None = None
    retriever: str | None = None  # 关键词召回方式：bm25 / sparse / both；缺省用 config


class SearchRequest(BaseModel):
    question: str
    top_k: int = 10
    retriever: str | None = None


def _brief(hits: list[dict], text_len: int = 90) -> list[dict]:
    """精简召回结果用于前端展示（截断长文本，避免响应过大）"""
    return [
        {
            "rank": i,
            "source": h["source"],
            "score": round(float(h.get("score", 0)), 4),
            "text": (h.get("text") or "")[:text_len],
        }
        for i, h in enumerate(hits, 1)
    ]


class StatusResponse(BaseModel):
    status: str


# ================= 静态资源与页面 =================
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """交互页面"""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/whoami")
def whoami(x_role: str | None = Header(default=None, alias=ROLE_HEADER)) -> dict:
    """
    当前身份的能力清单——**前端据此决定渲染什么**

    为什么不让前端硬编码权限表：那会变成两份真源，改一处漏一处。
    前端只认这个接口返回的 `can`，与后端 permissions.py 是同一份定义。
    """
    info = permissions.describe(_role(x_role))
    info["topk_range"] = {"min": TOP_K_PROFILE_MIN, "max": TOP_K_PROFILE_MAX}
    info["roles"] = [
        {"value": r, "label": permissions.ROLE_LABELS[r], "usable": permissions.has(r, permissions.CAP_ANSWER)}
        for r in permissions.ROLE_SELECTOR_ORDER
    ]
    info["default_role"] = permissions.DEFAULT_UI_ROLE
    # Demo 声明：权限申请不做处理，只声明现状（尚未接入电商系统）
    info["note"] = (
        "当前为 Demo，身份由请求头自报，尚未接入电商系统。"
        "正式权限应以登录态为准；权限申请需走电商系统审批流程。"
    )
    return info


# ================= 接口 =================
@app.post("/qa")
def qa(req: QueryRequest, x_role: str | None = Header(default=None, alias=ROLE_HEADER)):
    """
    统一问答入口

    内部按意图路由：闲聊走固定回复、聚合/统计类走 Text2SQL、其余走 RAG 混合检索。
    返回中 route 字段标明实际走向：chitchat / rag / error / llm_error

    retriever 可按请求覆盖关键词召回方式（bm25 / sparse / both）；不传则用 config。
    top_k 是「返回多少个用户」，只有运营及以上角色能生效，其余角色静默忽略。
    响应**按角色裁剪**后才返回（见 permissions.render 与 README 权限矩阵）。
    """
    role = _role(x_role)
    _require(role, permissions.CAP_ANSWER)

    limit = permissions.clamp_top_k(role, req.top_k, TOP_K_PROFILE_MAX, TOP_K_PROFILE_MIN)

    # dept 不接受调用方自报：它决定召回范围，等同越权口子（ODD-09 暴露的正是这一点）。
    # 目前只有管理员能显式覆盖，其余角色一律走默认过滤；接入电商系统后应改为
    # 「由登录身份推导部门」，届时这个参数应整体从请求模型里删掉。
    dept = req.dept if permissions.has(role, permissions.CAP_OPS) else None

    result = answer_question(
        req.question, dept, keyword_mode=req.retriever, profile_limit=limit
    )
    return permissions.render(result, role)


@app.post("/search")
def search(req: SearchRequest, x_role: str | None = Header(default=None, alias=ROLE_HEADER)) -> dict:
    """
    仅召回、不生成 —— 用于对比 BM25 与 BGE-M3 稀疏向量召回了什么

    相当于 A/B 实验的在线版：同一问题分别走两条关键词通路并排返回，
    让「为什么 A 找到了而 B 没找到」变得可见。不跑精排与生成，所以很快。

    ⚠ 这是**最敏感**的接口：它绕过精排与生成，直接吐出知识库原文片段，
    等于"不经过任何加工地扒库"。只对系统管理员开放。
    """
    role = _role(x_role)
    _require(role, permissions.CAP_RAW_SEARCH)

    question = (req.question or "").strip()
    if not question:
        return {"error": "问题不能为空"}

    k = max(1, min(req.top_k, 50))
    bm_hits = bm25_search(question, top_k=k)

    sparse_note = ""
    if sparse_search is None:
        sp_hits = []
        sparse_note = "FlagEmbedding 未安装，稀疏检索不可用"
    else:
        try:
            sp_hits = sparse_search(question, top_k=k)
        except Exception as e:  # 稀疏索引加载失败不应影响 BM25 结果展示
            sp_hits = []
            sparse_note = f"稀疏检索失败：{e}"

    bm_sources = {h["source"] for h in bm_hits}
    sp_sources = {h["source"] for h in sp_hits}

    return {
        "question": question,
        "bm25": _brief(bm_hits),
        "sparse": _brief(sp_hits),
        "sparse_note": sparse_note,
        "both_hit": sorted(bm_sources & sp_sources),
        "only_bm25": sorted(bm_sources - sp_sources),
        "only_sparse": sorted(sp_sources - bm_sources),
    }


@app.get("/stats")
def stats(x_role: str | None = Header(default=None, alias=ROLE_HEADER)) -> dict:
    """
    数据概况，供首页展示（画像规模 / 知识库规模 / 会员等级分布）

    ⚠ 它等价于「免 SQL 的聚合统计」：会员等级分布、钻石占比直接给出，
    还附带画像表的字段数（等于泄露 schema 规模）。故只对系统管理员开放。
    """
    _require(_role(x_role), permissions.CAP_STATS)

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
        users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM wiki_vectors")
        chunks = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT doc_name) FROM wiki_vectors")
        docs = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT city) FROM user_profile_vectors")
        cities = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT top_category) FROM user_profile_vectors")
        categories = cur.fetchone()[0]

        cur.execute(
            "SELECT member_level, COUNT(*) FROM user_profile_vectors "
            "GROUP BY member_level ORDER BY COUNT(*) DESC"
        )
        levels = dict(cur.fetchall())

        cur.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'user_profile_vectors'"
        )
        columns = cur.fetchone()[0]
    finally:
        conn.rollback()  # 清理查询事务，避免连接停在 idle in transaction
        cur.close()

    total = sum(levels.values()) or 1
    return {
        "users": users,
        "chunks": chunks,
        "docs": docs,
        "cities": cities,
        "categories": categories,
        "member_levels": levels,
        "profiles_columns": columns,
        "diamond_ratio": f"{levels.get('钻石', 0) / total * 100:.1f}%",
    }


def _sse(event: str, data: dict) -> str:
    """构造一条 SSE 消息"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/qa/stream")
def qa_stream(req: QueryRequest, x_role: str | None = Header(default=None, alias=ROLE_HEADER)):
    """
    流式问答（SSE）

    解决的问题：一次问答 9~17s，其中 92~96% 花在生成。此前用户要「盯着转圈」
    十几秒才看到第一个字；改为流式后，前置检索（约 3~6s）一完成，文字就开始
    逐字出现。**总耗时基本不变，但感知延迟大幅下降。**

    事件类型：
        stage  阶段提示（retrieving / generating）
        meta   元信息（route / sources / cached），**按角色裁剪后才发出**
        delta  文本片段
        done   结束
        error  错误

    权限说明（重要）：本函数有 **4 个 meta 出口**（缓存命中 / 检索不可用 / 闲聊 /
    正常生成），每个都单独构造 payload。**每一处都必须过 permissions.render()**——
    漏一个就是一次越权，而这类漏在 code review 里极难发现，因为四个分支长得不像。
    缓存里存的是**完整结果**，裁剪只发生在发出前，所以角色不进缓存键。
    """
    role = _role(x_role)
    _require(role, permissions.CAP_ANSWER)

    limit = permissions.clamp_top_k(role, req.top_k, TOP_K_PROFILE_MAX, TOP_K_PROFILE_MIN)
    # 与 /qa 同一口径：dept 不接受自报，仅管理员可覆盖
    dept = req.dept if permissions.has(role, permissions.CAP_OPS) else None

    def meta(payload: dict, **extra) -> str:
        """构造 meta 事件：先裁剪再序列化，避免各处漏裁剪"""
        return _sse("meta", permissions.render(payload, role) | extra)

    def event_stream():
        try:
            # 命中缓存时直接吐完，不用走生成
            key = answer_cache.make_key(req.question, dept, req.retriever, limit)
            hit = answer_cache.get(key)
            if hit is not None:
                yield meta({
                    "route": hit.get("route"),
                    "sources": hit.get("sources", []),
                    "sql": hit.get("sql", ""),
                    "rows_count": hit.get("rows_count"),
                    "sql_rows": hit.get("sql_rows", []),
                    "sql_error": hit.get("sql_error"),
                    "trace": hit.get("trace", {}),
                }, cached=True)
                # 回答正文原样下发：引用标记的清理交给前端（按 can.sources 判断），
                # 因为 delta 是逐片吐的，服务端正则匹配会被切片边界漏掉
                yield _sse("delta", {"delta": hit.get("answer", "")})
                yield _sse("done", {})
                return

            yield _sse("stage", {"stage": "retrieving"})
            ctx = prepare(req.question, dept, req.retriever, profile_limit=limit)
            route_name = ctx["route"]

            # 检索基础设施不可用：直接告知，不走生成、不写缓存
            # （不能缓存，否则数据库恢复后还会返回这条错误）
            # 兜底文案对**所有角色**透出——把"服务坏了"裁成"资料里没有"是最坏的结果
            if route_name == "error":
                yield meta({"route": route_name, "sources": []})
                yield _sse("delta", {"delta": ctx["answer"]})
                yield _sse("done", {})
                return

            # 闲聊：不调模型，直接给固定回复
            if route_name == "chitchat":
                yield meta({"route": route_name, "sources": []})
                yield _sse("delta", {"delta": ctx["answer"]})
                yield _sse("done", {})
                answer_cache.set(key, {"answer": ctx["answer"], "sources": [], "route": route_name})
                return

            # 流式生成：检索路候选 + （按需的）SQL 路结果一起进 context
            sql_result = ctx.get("sql_result")
            sql_payload = {
                "sql": (sql_result or {}).get("sql", ""),
                "rows_count": len((sql_result or {}).get("rows", [])),
                # 过程数据：SQL 实际结果 + 检索留痕，供前端展开查看
                "sql_rows": brief_rows((sql_result or {}).get("rows", [])),
                "sql_error": (sql_result or {}).get("error"),
                "trace": ctx.get("trace", {}),
            }
            yield meta({"route": route_name, "sources": ctx["sources"], **sql_payload})
            yield _sse("stage", {"stage": "generating"})

            chunks = []
            for delta in generate_stream(req.question, ctx["candidates"], sql_result):
                chunks.append(delta)
                yield _sse("delta", {"delta": delta})

            yield _sse("done", {})
            # 写缓存的是**完整结果**（不裁剪）：否则低权角色先问一次，
            # 高权角色再问就只剩被裁过的版本
            answer_cache.set(key, {
                "answer": "".join(chunks),
                "sources": ctx["sources"],
                "route": route_name,
                **sql_payload,
            })

        except APIError as e:
            # LLM 接口故障：与检索不可用分开处理，文案与 route 都不同
            # （排查方向相反：一个查 LLM 接口，一个查数据库）
            logger.exception("LLM 服务不可用")
            if not chunks:
                # 还没吐过任何字，用固定文案兜底——用户看到的是人话，
                # 而不是「请求失败：APITimeoutError」
                yield _sse("delta", {"delta": LLM_UNAVAILABLE_REPLY})
            yield _sse("error", {"message": str(e), "kind": "llm_unavailable"})
        except Exception as e:  # 流式过程中出错也要让前端知道
            logger.exception("流式问答失败")
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/cache/stats")
def cache_stats(x_role: str | None = Header(default=None, alias=ROLE_HEADER)) -> dict:
    """问答缓存命中情况——用于验证缓存是否真的生效（运维信息，仅管理员）"""
    _require(_role(x_role), permissions.CAP_OPS)
    return answer_cache.stats()


@app.post("/admin/clear-cache")
def clear_cache(x_role: str | None = Header(default=None, alias=ROLE_HEADER)) -> StatusResponse:
    """数据或配置更新后清空问答缓存（写操作，仅管理员）"""
    _require(_role(x_role), permissions.CAP_OPS)
    answer_cache.clear()
    logger.info("问答缓存已清空")
    return {"status": "cleared"}


@app.get("/health")
def health() -> StatusResponse:
    """存活探针：不鉴权。监控系统需要它，且它不泄露任何业务信息"""
    return {"status": "ok"}


@app.post("/admin/reload")
def admin_reload(x_role: str | None = Header(default=None, alias=ROLE_HEADER)) -> StatusResponse:
    """数据更新后重建 BM25 内存索引（写操作 + 影响性能，仅管理员）"""
    _require(_role(x_role), permissions.CAP_OPS)
    reload_bm25()
    return {"status": "reloaded"}
