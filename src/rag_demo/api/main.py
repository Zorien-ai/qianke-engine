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
    http://127.0.0.1:8000/docs   API 文档
    http://127.0.0.1:8000/health 健康检查

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

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rag_demo.cache import answer_cache
from rag_demo.db.connection import close_conn, get_conn
from rag_demo.generation.generator import generate_stream
from rag_demo.pipeline import answer_question, brief_rows, prepare
from rag_demo.retrieval.hybrid_retriever import (
    _load_bm25_corpus,
    bm25_search,
    get_model,
    reload_bm25,
    sparse_search,  # 可能为 None（FlagEmbedding 未安装时降级）
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


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


app = FastAPI(title="用户画像 RAG Demo", lifespan=lifespan)


# ================= 请求 / 响应模型 =================
class QueryRequest(BaseModel):
    question: str
    dept: str | None = None
    top_k: int = 5
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


# ================= 接口 =================
@app.post("/qa")
def qa(req: QueryRequest):
    """
    统一问答入口

    内部按意图路由：闲聊走固定回复、聚合/统计类走 Text2SQL、其余走 RAG 混合检索。
    返回中 route 字段标明实际走向：chitchat / sql / rag

    retriever 可按请求覆盖关键词召回方式（bm25 / sparse / both）；
    不传则用 config.KEYWORD_RETRIEVER。
    """
    return answer_question(req.question, req.dept, keyword_mode=req.retriever)


@app.post("/search")
def search(req: SearchRequest) -> dict:
    """
    仅召回、不生成 —— 用于对比 BM25 与 BGE-M3 稀疏向量召回了什么

    相当于 A/B 实验的在线版：同一问题分别走两条关键词通路并排返回，
    让「为什么 A 找到了而 B 没找到」变得可见。不跑精排与生成，所以很快。
    """
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
def stats() -> dict:
    """数据概况，供首页展示（画像规模 / 知识库规模 / 会员等级分布）"""
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
def qa_stream(req: QueryRequest):
    """
    流式问答（SSE）

    解决的问题：一次问答 9~17s，其中 92~96% 花在生成。此前用户要「盯着转圈」
    十几秒才看到第一个字；改为流式后，前置检索（约 3~6s）一完成，文字就开始
    逐字出现。**总耗时基本不变，但感知延迟大幅下降。**

    事件类型：
        stage  阶段提示（retrieving / generating）
        meta   元信息（route / sources / cached）
        delta  文本片段
        done   结束
        error  错误
    """

    def event_stream():
        try:
            # 命中缓存时直接吐完，不用走生成
            key = answer_cache.make_key(req.question, req.dept, req.retriever)
            hit = answer_cache.get(key)
            if hit is not None:
                yield _sse("meta", {
                    "route": hit.get("route"),
                    "sources": hit.get("sources", []),
                    "sql": hit.get("sql", ""),
                    "rows_count": hit.get("rows_count"),
                    "sql_rows": hit.get("sql_rows", []),
                    "trace": hit.get("trace", {}),
                    "cached": True,
                })
                yield _sse("delta", {"delta": hit.get("answer", "")})
                yield _sse("done", {})
                return

            yield _sse("stage", {"stage": "retrieving"})
            ctx = prepare(req.question, req.dept, req.retriever)
            route_name = ctx["route"]

            # 闲聊：不调模型，直接给固定回复
            if route_name == "chitchat":
                yield _sse("meta", {"route": route_name, "sources": []})
                yield _sse("delta", {"delta": ctx["answer"]})
                yield _sse("done", {})
                answer_cache.set(key, {"answer": ctx["answer"], "sources": [], "route": route_name})
                return

            # 流式生成：检索路候选 + （按需的）SQL 路结果一起进 context
            sql_result = ctx.get("sql_result")
            yield _sse("meta", {
                "route": route_name,
                "sources": ctx["sources"],
                "sql": (sql_result or {}).get("sql", ""),
                "rows_count": len((sql_result or {}).get("rows", [])),
                # 过程数据：SQL 实际结果 + 检索留痕，供前端展开查看
                "sql_rows": brief_rows((sql_result or {}).get("rows", [])),
                "sql_error": (sql_result or {}).get("error"),
                "trace": ctx.get("trace", {}),
            })
            yield _sse("stage", {"stage": "generating"})

            chunks = []
            for delta in generate_stream(req.question, ctx["candidates"], sql_result):
                chunks.append(delta)
                yield _sse("delta", {"delta": delta})

            yield _sse("done", {})
            answer_cache.set(key, {
                "answer": "".join(chunks),
                "sources": ctx["sources"],
                "route": route_name,
                "sql": (sql_result or {}).get("sql", ""),
                "rows_count": len((sql_result or {}).get("rows", [])),
                "sql_rows": brief_rows((sql_result or {}).get("rows", [])),
                "trace": ctx.get("trace", {}),
            })

        except Exception as e:  # 流式过程中出错也要让前端知道
            logger.exception("流式问答失败")
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/cache/stats")
def cache_stats() -> dict:
    """问答缓存命中情况——用于验证缓存是否真的生效"""
    return answer_cache.stats()


@app.post("/admin/clear-cache")
def clear_cache() -> StatusResponse:
    """数据或配置更新后清空问答缓存"""
    answer_cache.clear()
    logger.info("问答缓存已清空")
    return {"status": "cleared"}


@app.get("/health")
def health() -> StatusResponse:
    return {"status": "ok"}


@app.post("/admin/reload")
def admin_reload() -> StatusResponse:
    """数据更新后重建 BM25 内存索引"""
    reload_bm25()
    return {"status": "reloaded"}
