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
    用户由可选的 `X-User` 传入（用于「对指定人员提权」）。
    交互页面可切换。⚠ **调用方可以自报身份，这不是安全边界**，只是演示开关——
    接入电商系统后角色/用户必须来自登录态，见 config.DEFAULT_API_ROLE 的说明。

    等级与权限由管理员在页面上动态配置（L1~L4 → 能力），落盘 var/permissions.json，
    改完**不用重启**即生效：每个请求都会重新解析身份并读最新配置。

前置条件：
    1. PostgreSQL(pgvector) 已启动，且已跑过 ingest_data.py 与 ingest_docs.py
    2. 环境变量 DEEPSEEK_API_KEY 已设置

首次请求会加载 bge-m3 与 bge-reranker-v2-m3（约 2GB 显存），启动时已预加载。
"""
import base64
import json
import logging
import os
import random
import secrets
import threading
import time
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import APIError
from pydantic import BaseModel

from rag_demo import answer_guard, auth, config, marketing, permissions, tenant_eval
from rag_demo.api.demo_showcase import (
    DEFAULT_LIMIT as DEMO_SHOWCASE_LIMIT,
    DEMO_QUERY_TITLE,
    DEMO_QUERY_WHERE,
    build_labels as build_demo_labels,
    clamp_limit as clamp_demo_limit,
    serialize_user as serialize_demo_user,
)
from rag_demo.api.kb import register_kb
from rag_demo.api.wizard import register_wizard
from rag_demo.cache import answer_cache
from rag_demo.config import (
    DEFAULT_API_ROLE,
    DEFAULT_DATASET,
    ENABLE_API_DOCS,
    INTENT_ROUTER,
    TOP_K_PROFILE_MAX,
    TOP_K_PROFILE_MIN,
)
from rag_demo.db.connection import (
    close_conn,
    current_dataset,
    get_conn,
    pin_dataset,
    reset_dataset,
    use_dataset,
)
from rag_demo.db.schema import ensure_wiki_columns, index_freshness
from rag_demo.generation.generator import (
    EVENT_ANSWER,
    EVENT_REASONING,
    generate_events,
)
from rag_demo.logging_setup import setup_logging
from rag_demo.pipeline import answer_question, brief_rows, prepare
from rag_demo.prompts import LLM_UNAVAILABLE_REPLY, PREDICTION_BLOCKED_REPLY
from rag_demo.retrieval.reranker import get_reranker
from rag_demo.retrieval.hybrid_retriever import (
    _load_bm25_corpus,
    bm25_search,
    get_model,
    reload_bm25,
    sparse_search,  # 可能为 None（FlagEmbedding 未安装时降级）
)
from rag_demo.tools import bert_intent, intent_telemetry

# 控制台 + logs/rag_demo.log 双通道（此前只打屏，服务跑后台日志就丢了）
setup_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ================= 角色与权限 =================
# ⚠ 角色/用户来源目前是**请求头**，即调用方可自报。这不是安全边界，是演示开关：
#   接入电商系统后必须改为「登录态 → 角色/用户」，并把 config.DEFAULT_API_ROLE 改成 guest。
ROLE_HEADER = "X-Role"
USER_HEADER = "X-User"


def _auth_enforced() -> bool:
    """登录态是否必须：开启登录且没有显式放行请求头（见 auth.ALLOW_HEADER_AUTH）"""
    return auth.AUTH_ENABLED and not auth.ALLOW_HEADER_AUTH


def _role(x_role: str | None) -> str:
    """
    当前请求的角色：优先登录态，其次请求头（仅在未强制登录时）

    待审核账号按 guest 处理（没有任何能力），但**能登录**——这样他看到的是
    「等待审核」，而不是「密码错了」。

    管理员身份按**账号标记**判定，不只看 `role` 列：
    系统管理员 = `admin`，企业管理员 = `ent_admin`。这样早期审核出来的企业账号
    （role 可能还停在 cs）也不会因为历史数据而失去身份。
    """
    account = auth.current_account()
    if account is not None:
        if account.get("status") != auth.STATUS_ACTIVE:
            return permissions.ROLE_GUEST
        if account.get("is_system_admin"):
            return permissions.ROLE_ADMIN
        if account.get("is_enterprise_admin"):
            return permissions.ROLE_ENT_ADMIN
        return account.get("role") or permissions.ROLE_GUEST
    if _auth_enforced():
        return permissions.ROLE_GUEST
    return permissions.resolve_role(x_role, default=DEFAULT_API_ROLE)


def _user(x_user: str | None) -> str | None:
    """
    当前请求的「人员标识」：登录态用**用户名**，请求头模式用 X-User

    用用户名而不是自增 ID：管理员在权限页看到的就是 `zhangsan`，
    人和配置项能对上号；换库/迁移也不会因为 ID 变化而错配。
    """
    account = auth.current_account()
    if account is not None:
        return account.get("username")
    if _auth_enforced():
        return None
    return permissions.normalize_user(x_user)


def _require_login() -> dict | None:
    """
    业务接口的登录校验

    - 未登录：401（前端据此跳登录页；403 会被误读成"登录了但没权限"）
    - 待审核：403 + 明确文案
    - 未强制登录（离线脚本模式）：返回 None，后续按请求头走
    """
    account = auth.current_account()
    if account is None:
        if _auth_enforced():
            raise HTTPException(status_code=401, detail="请先登录")
        return None
    if account.get("status") == auth.STATUS_DISABLED:
        raise HTTPException(status_code=403, detail="该账号已停用")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号待审核：请等待管理员通过后再使用")
    return account


def _require_system_admin() -> dict:
    """全局配置/运维接口：只有系统管理员能动（企业管理员只管自己企业）"""
    account = _require_login()
    if account is None or not account.get("is_system_admin"):
        raise HTTPException(status_code=403, detail="仅系统管理员可执行该操作")
    return account


def _require_manager(enterprise_id: int | None = None) -> dict:
    """
    账号管理权限：系统管理员管全部，企业管理员只管本企业

    企业管理员的能力来自账号标记（`is_enterprise_admin`），不是来自等级——
    等级决定"能看什么"，但它不该决定"能管谁"。
    """
    account = _require_login()
    if account is None:
        raise HTTPException(status_code=403, detail="该接口需要登录态（当前为离线脚本模式）")
    if account.get("is_system_admin"):
        return account
    if account.get("is_enterprise_admin"):
        if enterprise_id is not None and account.get("enterprise_id") != enterprise_id:
            raise HTTPException(status_code=403, detail="只能管理本企业的账号")
        return account
    raise HTTPException(status_code=403, detail="仅管理员可执行该操作")


# ================= 租户数据空间（M3 隔离：读侧） =================
# 为什么不让前端传 dataset / tenant_id：数据集决定「读哪个库」，属于权限而不是参数。
# 一旦前端能传，「切到别人的库」就只差一个请求体字段。所以一律从登录账号推导：
#
#   系统管理员 -> demo（演示底座，也是评测基线；要看企业库请走向导）
#   企业账号   -> 本企业库（enterprise.dataset，审核通过时生成 ent_<id>）
#
# 推导不出来就 403，**绝不回落 DEFAULT_DATASET**。这是 M3 头号缺陷：
# 改造前 /qa、/search、/stats 根本不切库，企业租户提问拿到的全是 demo 的答案
# （8110 画像 / 36 篇文档），而界面上没有任何标识——用户会当成自家数据。
_TENANT_EMPTY = "当前租户数据为空，请先到「数据接入」上传数据并构建"


def _tenant_dataset() -> str:
    """当前请求该读哪个库：账号推导，前端无权指定"""
    account = _require_login()
    if account is None:
        # 离线脚本模式（未强制登录）：沿用请求头语义，由调用方负责数据集
        return current_dataset()
    if account.get("is_system_admin"):
        return DEFAULT_DATASET
    dataset = account.get("dataset")
    if not dataset:
        raise HTTPException(
            status_code=403,
            detail="该账号还没有绑定数据空间，请联系企业管理员确认企业信息",
        )
    return dataset


def _tenant_ready(dataset: str) -> bool:
    """
    这个库是不是「已经构建过」：两张核心表都在才算

    审核通过只登记数据集名，真正的库要等第一次构建才建（db/provision.py）。
    所以「有 dataset」不等于「能查」——先确认再查，才能给出「当前租户数据为空」
    这句人话，而不是一句 psycopg2 的 database does not exist。
    """
    try:
        conn = get_conn(dataset)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT to_regclass('public.user_profile_vectors') IS NOT NULL, "
                "to_regclass('public.wiki_vectors') IS NOT NULL"
            )
            profiles, wiki = cur.fetchone()
            return bool(profiles) and bool(wiki)
        finally:
            conn.rollback()  # 清事务，避免连接停在 idle in transaction
            cur.close()
    except Exception as e:  # noqa: BLE001 库不存在 / 连不上都按「还没构建」处理
        logger.info("租户数据空间不可用（%s）：%s", dataset, e)
        return False


@contextmanager
def _tenant_scope():
    """
    把本次请求固定在「当前账号的数据集」上

    pipeline / 检索 / SQL 里几十处 get_conn() 都不传参数，靠 contextvar 决定去哪个库
    （分库改造的取舍见 db/connection.py）。所以切库只有 use_dataset 一句，但**必须在
    finally 里还原**：漏掉 reset 会让同一线程上的下一个请求继续读上一个租户的库。
    """
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    token = use_dataset(dataset)
    try:
        yield dataset
    finally:
        reset_dataset(token)


def _require(role: str, cap: str, user: str | None = None) -> None:
    """
    能力校验：不满足就 403

    用 403 而不是 404/静默忽略——调用方明确知道"这条路不通"，
    比"看起来成功了但字段没了"更容易排查。

    能力按 **用户覆盖后的有效等级** 计算，所以管理员刚授的权下一个请求就生效。
    """
    if not permissions.has(role, cap, user):
        logger.warning(
            "权限拦截: role=%s user=%s level=%s 缺少能力 %s",
            role, user or "-", permissions.resolve_level(role, user), cap,
        )
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

    # 登录态（M3）：建表 + 种子系统管理员 + 恢复企业数据集注册。
    # 注册必须发生在任何请求之前 —— connection._resolve 只认 DATASETS 里的名字，
    # 没注册的企业库第一次 get_conn 就会抛 UnknownDataset。
    auth.init(auth.SEED_ADMIN_USERNAME, auth.SEED_ADMIN_PASSWORD)
    enterprises = auth.list_enterprises()
    for ent in enterprises:
        config.register_dataset(ent["dataset"], config.enterprise_db_name(ent["id"]))
    logger.info(
        "登录态：账号库 %s，企业 %d 家（AUTH_ENABLED=%s）",
        auth.describe_backend(), len(enterprises), auth.AUTH_ENABLED,
    )

    # 老库补列（幂等）：父块 / 图片元数据。demo 库是仓库自带的、不会为重跑 ingest，
    # 不在这里补的话每次检索都会因缺列而降级并刷 warning。
    # 失败只降级不阻断启动：父块与图片是增强能力，缺了仍能答文本问题。
    try:
        ensure_wiki_columns()
    except Exception as e:  # noqa: BLE001
        logger.warning("wiki_vectors 补列失败（父块/图片功能降级）: %s: %s",
                       type(e).__name__, e)

    logger.info("预加载模型和 BM25 语料...")
    get_model()
    _load_bm25_corpus()
    # 精排模型也必须在**启动时**加载，不能等第一个请求。
    # 实测（2026-10-15）：请求期间首次加载精排模型会得到**半转换的 fp16 模型**
    # （权重 fp16、输入 fp32），首次 forward 抛
    # "mat1 and mat2 must have the same dtype, but got Half and Float"，
    # 且该进程此后**每次**检索都失败（模型停在坏状态，重启才恢复）。
    # 具体触发条件是「加载模型的同时还有其他 CUDA 活动」（请求里的 embed 编码、
    # 或下面那个后台稀疏预热线程），所以这里把它挪到启动阶段，与 get_model 同一批。
    get_reranker()
    # 意图分类模型同理，必须在这一批里加载，不能等第一个请求（原因见上）。
    # 与上面两个不同：它加载失败**不影响可用性**——router 会回退关键词规则，
    # 所以这里不抛异常，只把状态记进日志（漏判变多 vs 服务起不来，后者不可接受）。
    if bert_intent.preload():
        logger.info("意图分类模型预加载完成（INTENT_ROUTER=%s）", INTENT_ROUTER)
    else:
        logger.warning(
            "意图分类模型不可用，入口路由回退关键词规则（INTENT_ROUTER=%s）: %s",
            INTENT_ROUTER, bert_intent.load_info().get("error"),
        )
    # 标记埋点来源：只有经 API 进来的才算「真实流量」，
    # 离线脚本（bench / smoke / 评测）的记录不能被当成线上分布。
    intent_telemetry.set_source("api")
    logger.info("意图路由埋点已启用：%s", intent_telemetry.stats())

    # 索引新鲜度检查：**只告警、不阻断启动**。
    # 过期不该让服务起不来（那是把「数据没更新」升级成「服务不可用」），
    # 但必须留下痕迹——这套失效没有任何自动机制，静默用旧索引是最难查的一类问题。
    # 与上面 bert_intent 的处置原则一致：降级可用 + 日志可查。
    try:
        fresh = index_freshness()
        if fresh["status"] == "fresh":
            logger.info("检索索引新鲜度: fresh（%s）", fresh["reason"])
        else:
            logger.warning(
                "检索索引新鲜度: %s（%s）—— 重建命令：\n"
                "    uv run python src/rag_demo/tools/build_search_index.py",
                fresh["status"], fresh["reason"],
            )
    except Exception as e:  # noqa: BLE001  检查失败不影响启动
        logger.warning("索引新鲜度检查跳过: %s: %s", type(e).__name__, e)

    logger.info("预加载完成")

    # 稀疏索引放后台预热：不拖慢启动，但让首个 sparse 请求即热态
    if sparse_search is not None:
        threading.Thread(target=_warmup_sparse, daemon=True).start()
        logger.info("稀疏索引正在后台预热...")

    yield
    close_conn()


app = FastAPI(
    title="千客引擎 (Qianke Engine)",
    lifespan=lifespan,
    # 生产环境关掉：/docs 与 /openapi.json 会一次性暴露所有接口与字段结构
    **({} if ENABLE_API_DOCS else {
        "docs_url": None, "redoc_url": None, "openapi_url": None,
    }),
)


@app.middleware("http")
async def _attach_account(request: Request, call_next):
    """
    每个请求先把 Cookie 会话解析成账号，放进 contextvar

    为什么用 contextvar 而不是给每个端点加参数：向导那条线（mvp/app.py）
    有 10 个端点，它们要的是「当前企业库」而不是「HTTP 身份」。把身份解析
    放在入口一次，业务层统一读 current_account()，不必逐个改签名。

    `/static` 不解析：静态资源不需要身份，而每次读库/sqlite 都是白花。
    """
    if auth.AUTH_ENABLED and not request.url.path.startswith("/static"):
        try:
            account = auth.resolve_session(request.cookies.get(auth.SESSION_COOKIE))
        except Exception:  # noqa: BLE001 账号库异常不能把整站打成 500
            logger.exception("会话解析失败，按未登录处理")
            account = None
        auth.set_current_account(account)
    try:
        return await call_next(request)
    finally:
        auth.set_current_account(None)


# ================= 请求 / 响应模型 =================
class QueryRequest(BaseModel):
    question: str
    dept: str | None = None
    # 「返回多少个用户」= 画像池的全局名额。None = 用 config 默认值 TOP_K_PROFILE(3)。
    # 只有运营及以上角色能生效，其余角色的传值会被静默忽略（见 permissions.clamp_top_k）。
    #
    # 改造前这个字段是 `top_k: int = 5` 但**整条链路没有任何地方用它**——
    # 收了参数却完全忽略，比不收更糟：调用方以为生效了。
    top_k: int | None = None
    retriever: str | None = None  # 关键词召回方式：bm25 / sparse / both；缺省用 config
    # 深度思考：只作用于**最后一个生成调用**（规划 / Text2SQL 恒不思考）。
    # 所有角色都能开——它是用户自选的代价（实测慢 5.5 倍、token 7.2 倍，
    # 忠实度 95.7%→100%，见 tools/ab_deep_thinking.py），不做权限收窄。
    # None/False = 关（也是全局默认），True = 开。
    deep_thinking: bool | None = None


class SearchRequest(BaseModel):
    question: str
    top_k: int = 10
    retriever: str | None = None


class EvalQuestionSetIn(BaseModel):
    name: str | None = None
    questions: list[dict]


class EvalRunIn(BaseModel):
    set_id: str


class MarketingCopyIn(BaseModel):
    question: str
    user_ids: list[str] = []


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


# ---------- 权限配置（管理员） ----------
class PermissionConfigIn(BaseModel):
    """整份保存：等级→能力 + 角色→等级（+ 可选的人员覆盖）"""

    levels: dict[str, list[str]]
    role_levels: dict[str, str]
    # None = 保留现有的人员授权（页面只管矩阵与角色，人员授权走 grant 接口）
    user_levels: dict[str, str] | None = None


class GrantIn(BaseModel):
    """单点授权/提权：给某个角色或某个人员设定等级"""

    target_type: str  # "role" | "user"
    target: str
    level: str
    note: str | None = None


# ---------- 账号（管理员） ----------
class ApproveIn(BaseModel):
    role: str = "cs"


class UserRoleIn(BaseModel):
    role: str


class UserStatusIn(BaseModel):
    status: str


# ================= 静态资源与页面 =================
# 向导（M3 收口后）：`/wizard` 页面 302 到 Vue 新版 `/v2/#/setup`，
# `/api/wizard/*` 接口照旧；本模块已不再挂 `/static/wizard`（老静态资源只在
# 8002 独立调试服务里保留），所以下面这个注册顺序不再敏感——但保持原位置，
# 避免以后再加静态挂载点时又踩「先通用后特殊」的坑。
# 接口实现见 rag_demo/mvp/app.py，页面接管见 web/src/views/Setup.vue。
register_wizard(app)

# 企业后台（M3）：/api/kb/* 与 /admin/enterprises、邀请码重置。
# 实现见 rag_demo/api/kb.py；这里只注册路由（不挂静态），与向导一起排在
# 既有静态挂载之前，保持「先特殊、后通用」的注册顺序。
register_kb(app)

# Vue 3 新界面（M3）：把构建产物挂到 /v2。
# 项目根从本文件位置向上推导（api/main.py → api → rag_demo → src → 项目根），
# 不写死盘符、不 import config 拿路径。dist 不存在时**跳过而不是报错**：
# 只跑后端、或 Vue 还没构建的环境必须能正常启动。
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
WEB_DIST = os.path.join(_PROJECT_ROOT, "web", "dist")
if os.path.isdir(WEB_DIST):
    app.mount("/v2", StaticFiles(directory=WEB_DIST, html=True), name="web-v2")
    logger.info("Vue 3 新界面已挂载: /v2 -> %s", WEB_DIST)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> Response:
    """主入口：M3 收口后统一进 Vue 新版（`/v2/`），旧单页只作兜底

    为什么直接 302 到 `/v2/`：新旧两套界面并存时，从旧首页点「数据导入/新版界面」
    会突然换皮肤，体验是割裂的；主入口直接落到新版后，登录页之后的每一跳都在
    Vue 路由内，只有确实没有构建产物时才退回旧单页。

    - `web/dist` 存在（正常部署）→ 302 `/v2/`；未登录由 Vue 路由守卫跳 `/login`，
      服务端不再重复判断一次登录态（两套口径容易不一致）。
    - `web/dist` 缺失（本地没 `npm run build`）→ 仍返回旧单页——总比 404 好。
    """
    if os.path.isdir(WEB_DIST):
        return RedirectResponse("/v2/", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    """登录 / 注册页（唯一不需要登录的页面）"""
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/whoami")
def whoami(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """
    当前身份的能力清单——**前端据此决定渲染什么**

    为什么不让前端硬编码权限表：那会变成两份真源，改一处漏一处。
    前端只认这个接口返回的 `can`，与后端 permissions.py 是同一份定义。

    返回里带 `level`（L1~L4）：管理员改完配置，这里立刻反映新等级与新能力。
    """
    account = auth.current_account()
    role, user = _role(x_role), _user(x_user)
    info = permissions.describe(role, user)
    info["authenticated"] = account is not None
    info["topk_range"] = {"min": TOP_K_PROFILE_MIN, "max": TOP_K_PROFILE_MAX}
    # 「可用」按角色默认等级算：管理员把某个角色提到 L1 以上，它就会出现在下拉框里
    info["roles"] = [
        {
            "value": r,
            "label": permissions.ROLE_LABELS[r],
            "usable": permissions.has(r, permissions.CAP_ANSWER),
            "level": permissions.resolve_level(r),
        }
        for r in permissions.ROLE_SELECTOR_ORDER
    ]
    info["default_role"] = permissions.DEFAULT_UI_ROLE
    info["levels"] = [
        {"value": lv, "label": permissions.LEVEL_LABELS[lv]} for lv in permissions.LEVELS
    ]

    # 账号信息：页面据此显示"我是谁/哪家企业/什么状态"。
    # 待审核账号在这里就能看到原因，不用去猜"为什么点了没反应"。
    if account is not None:
        ent = account.get("enterprise") or None
        can_see_code = bool(account.get("is_system_admin") or account.get("is_enterprise_admin"))
        info["account"] = {
            "id": account["id"],
            "username": account["username"],
            "display_name": account["display_name"],
            "account_type": account["account_type"],
            "account_type_label": account["account_type_label"],
            # 用**解析后的角色**（管理员身份按账号标记判定），而不是库里的 role 列：
            # 早期审核出来的企业账号 role 可能还停在 cs，页面不该显示成销售。
            "role": role,
            "role_label": permissions.ROLE_LABELS.get(role, role),
            "status": account["status"],
            "status_label": account["status_label"],
            "is_system_admin": account["is_system_admin"],
            "is_enterprise_admin": account["is_enterprise_admin"],
            "enterprise": (
                {
                    "id": ent["id"],
                    "name": ent["name"],
                    "dataset": ent.get("dataset"),
                    # 邀请码只给企业管理员看：普通员工拿到了也没用，反而是泄露面
                    "invite_code": ent["invite_code"] if can_see_code else None,
                }
                if ent
                else None
            ),
        }
    info["auth"] = {"enabled": auth.AUTH_ENABLED, "enforced": _auth_enforced()}
    info["note"] = (
        "已启用登录：身份来自账号，请求头不再生效。"
        "企业账号审核通过后会生成企业库与邀请码；员工用邀请码加入企业。"
        if _auth_enforced()
        else "当前未强制登录（离线脚本模式），身份由请求头自报，不是安全边界。"
    )
    return info


# ================= 登录 / 注册（M3） =================
class RegisterIn(BaseModel):
    username: str
    password: str
    contact: str = ""               # 手机号或邮箱（登录标识）
    account_type: str = auth.ACCOUNT_EMPLOYEE
    display_name: str = ""
    invite_code: str | None = None
    captcha_id: str = ""
    captcha_code: str = ""
    agree_terms: bool = False


class LoginIn(BaseModel):
    # account：手机号 / 邮箱 / 用户名；username 保留给历史脚本
    account: str | None = None
    username: str | None = None
    password: str
    remember: bool = False


# ---------- 图形验证码 ----------
# 为什么自己画 SVG：不引入 PIL / 验证码库，一个接口就能返回可直接 <img> 的图。
# 存内存（单进程）；多进程部署时应换成 Redis——这里与 auth 的 SQLite 定位一致，
# 演示环境不为此加依赖。
_CAPTCHA_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 去掉 0/O/1/I
_CAPTCHA_TTL_SECONDS = 300
_CAPTCHA_MAX_ITEMS = 5000
_captchas: dict[str, tuple[str, float]] = {}
_captcha_lock = threading.Lock()
_captcha_last_gc = 0.0


def _new_captcha() -> tuple[str, str]:
    """生成一次性验证码：返回 (id, 明文)。明文只在服务端，出网的是图片。"""
    global _captcha_last_gc
    code = "".join(secrets.choice(_CAPTCHA_ALPHABET) for _ in range(4))
    cid = secrets.token_urlsafe(12)
    now = time.time()
    with _captcha_lock:
        if now - _captcha_last_gc > 60:
            for key, (_, expires) in list(_captchas.items()):
                if expires < now:
                    _captchas.pop(key, None)
            _captcha_last_gc = now
        _captchas[cid] = (code, now + _CAPTCHA_TTL_SECONDS)
        while len(_captchas) > _CAPTCHA_MAX_ITEMS:
            _captchas.pop(next(iter(_captchas)))
    return cid, code


def _verify_captcha(cid: str, code: str) -> bool:
    """校验并**立即作废**（无论对错）：否则可以拿同一个 id 一直猜。"""
    item = _captchas.pop((cid or "").strip(), None)
    if item is None:
        return False
    expected, expires = item
    if expires < time.time():
        return False
    return secrets.compare_digest(expected, (code or "").strip().upper())


def _captcha_svg(code: str) -> str:
    """
    极简 SVG 验证码：4 个字符 + 干扰线 + 轻微旋转。字符集无特殊符号，无需转义。

    尺寸 120×48 与前端按钮**完全一致**：不一致会被 object-fit 裁掉最后一个字符，
    用户看到 "TYE" 却要输入 "TYEE"。
    """
    width, height = 120, 48
    rng = random.SystemRandom()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" rx="8" fill="#F3F4F6"/>',
    ]
    for _ in range(3):
        parts.append(
            f'<path d="M{rng.randint(0, 16)},{rng.randint(6, height - 6)} '
            f'Q{rng.randint(30, 90)},{rng.randint(0, height)} '
            f'{rng.randint(width - 20, width)},{rng.randint(6, height - 6)}" '
            f'fill="none" stroke="rgba(148,163,184,0.55)" stroke-width="1"/>'
        )
    for i, ch in enumerate(code):
        x = 18 + i * 26
        y = 33 + rng.randint(-2, 2)
        angle = rng.randint(-14, 14)
        parts.append(
            f'<text x="{x}" y="{y}" font-family="ui-monospace,Consolas,monospace" '
            f'font-size="25" font-weight="700" fill="#334155" '
            f'transform="rotate({angle} {x} {y})">{ch}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


@app.get("/auth/captcha")
def auth_captcha() -> dict:
    """发一张验证码（base64 data URL，前端直接塞给 <img>，不涉及 innerHTML）"""
    cid, code = _new_captcha()
    svg = _captcha_svg(code)
    return {
        "id": cid,
        "image": "data:image/svg+xml;base64,"
        + base64.b64encode(svg.encode("utf-8")).decode("ascii"),
        "expires_in": _CAPTCHA_TTL_SECONDS,
    }


@app.post("/auth/register")
def register(payload: RegisterIn) -> dict:
    """
    开放注册，但**一律进待审核**：

    自助注册解决的是"不用管理员手工建号"，不是"注册即可用"。审核这一步
    同时承担两件事：确认企业身份（企业账号审核通过才建库、发邀请码），
    以及给员工分配角色（角色决定等级，等级决定能看什么）。

    前置三道闸：同意条款、图形验证码、手机号/邮箱。
    验证码**校验一次即作废**，失败要刷新——这是为了不让"猜验证码"变成可行路径。
    """
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="当前未启用登录")
    if not payload.agree_terms:
        raise HTTPException(status_code=400, detail="请先阅读并同意服务条款")
    if not (payload.contact or "").strip():
        raise HTTPException(status_code=400, detail="请填写手机号或邮箱")
    if not _verify_captcha(payload.captcha_id, payload.captcha_code):
        raise HTTPException(status_code=400, detail="验证码不正确或已过期，请刷新后重试")
    try:
        user = auth.create_user(
            username=payload.username,
            password=payload.password,
            account_type=payload.account_type,
            display_name=payload.display_name,
            invite_code=payload.invite_code,
            contact=payload.contact,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "status": auth.STATUS_PENDING,
        "message": (
            "注册成功，等待系统管理员审核"
            if user["account_type"] == auth.ACCOUNT_ENTERPRISE
            else "注册成功，等待企业管理员审核"
        ),
        "username": user["username"],
        "account_type": user["account_type"],
        "status_label": user["status_label"],
    }


@app.post("/auth/login")
def login(payload: LoginIn, response: Response) -> dict:
    """登录：校验密码 → 发会话 Cookie。

    待审核账号**允许登录**：登录后能看到「等待审核」。
    拦在登录这一步，用户只会以为自己的密码记错了。

    `account` 支持手机号 / 邮箱 / 用户名；`remember=true` 时发 30 天持久 Cookie，
    否则是浏览器会话 Cookie（关掉浏览器就需要重新登录）。
    """
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="当前未启用登录")
    account_id = (payload.account or payload.username or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="请输入手机号、邮箱或用户名")
    try:
        user = auth.authenticate(account_id, payload.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    ttl = auth.REMEMBER_TTL_SECONDS if payload.remember else auth.SESSION_TTL_SECONDS
    token = auth.create_session(user["id"], ttl)
    account = auth.resolve_session(token)
    if account is None:  # 理论上不可能，除非账号在两步之间被停用
        raise HTTPException(status_code=403, detail="该账号不可用")
    auth.set_current_account(account)
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        # 不勾「记住登录状态」= 不写 max_age：浏览器关掉即失效
        max_age=ttl if payload.remember else None,
        httponly=True,
        samesite="lax",
        path="/",
    )
    logger.info("登录成功: %s（%s）", account["username"], account["status"])
    return {
        "status": "ok",
        "username": account["username"],
        "display_name": account["display_name"],
        "role": account["role"],
        "account_status": account["status"],
        "status_label": account["status_label"],
        "is_system_admin": account["is_system_admin"],
        "is_enterprise_admin": account["is_enterprise_admin"],
    }


@app.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    """退出：删服务端会话 + 清 Cookie（只清 Cookie 不算退出，令牌仍可用）"""
    auth.revoke_session(request.cookies.get(auth.SESSION_COOKIE))
    auth.set_current_account(None)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


# ================= 接口 =================
@app.post("/qa")
def qa(
    req: QueryRequest,
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
):
    """
    统一问答入口

    内部按意图路由：闲聊走固定回复、聚合/统计类走 Text2SQL、其余走 RAG 混合检索。
    返回中 route 字段标明实际走向：chitchat / rag / error / llm_error

    retriever 可按请求覆盖关键词召回方式（bm25 / sparse / both）；不传则用 config。
    top_k 是「返回多少个用户」，只有运营及以上角色能生效，其余角色静默忽略。
    响应**按角色裁剪**后才返回（见 permissions.render 与 README 权限矩阵）。
    """
    _require_login()
    role, user = _role(x_role), _user(x_user)
    _require(role, permissions.CAP_ANSWER, user)

    limit = permissions.clamp_top_k(
        role, req.top_k, TOP_K_PROFILE_MAX, TOP_K_PROFILE_MIN, user
    )

    # dept 不接受调用方自报：它决定召回范围，等同越权口子（ODD-09 暴露的正是这一点）。
    # 目前只有管理员能显式覆盖，其余角色一律走默认过滤；接入电商系统后应改为
    # 「由登录身份推导部门」，届时这个参数应整体从请求模型里删掉。
    dept = req.dept if permissions.has(role, permissions.CAP_OPS, user) else None

    # 读哪个库由账号决定（_tenant_scope 内部校验并切换），前端无权指定
    with _tenant_scope():
        result = answer_question(
            req.question, dept, keyword_mode=req.retriever, profile_limit=limit,
            deep_thinking=req.deep_thinking,
        )
    return permissions.render(result, role, user)


@app.post("/api/marketing/copy")
def marketing_copy(
    req: MarketingCopyIn,
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """按当前数据空间生成 3 种营销短信；文档硬指标由后端二次校验。"""
    _require_login()
    role, user = _role(x_role), _user(x_user)
    _require(role, permissions.CAP_ANSWER, user)
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="缺少原始问题，无法定位营销场景")
    with _tenant_scope() as dataset:
        try:
            data = marketing.generate_copy(question, req.user_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("营销文案生成失败 dataset=%s", dataset)
            raise HTTPException(status_code=502, detail=f"营销文案生成失败：{exc}") from exc
    return {"dataset": dataset, **data}


@app.post("/search")
def search(
    req: SearchRequest,
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """
    仅召回、不生成 —— 用于对比 BM25 与 BGE-M3 稀疏向量召回了什么

    相当于 A/B 实验的在线版：同一问题分别走两条关键词通路并排返回，
    让「为什么 A 找到了而 B 没找到」变得可见。不跑精排与生成，所以很快。

    ⚠ 这是**最敏感**的接口：它绕过精排与生成，直接吐出知识库原文片段，
    等于"不经过任何加工地扒库"。只对系统管理员开放。
    """
    _require_login()
    role, user = _role(x_role), _user(x_user)
    _require(role, permissions.CAP_RAW_SEARCH, user)

    question = (req.question or "").strip()
    if not question:
        return {"error": "问题不能为空"}

    k = max(1, min(req.top_k, 50))
    with _tenant_scope():
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
def stats(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """
    数据概况，供首页展示（画像规模 / 知识库规模 / 会员等级分布）

    ⚠ 它等价于「免 SQL 的聚合统计」：会员等级分布、钻石占比直接给出，
    还附带画像表的字段数（等于泄露 schema 规模）。故只对系统管理员开放。
    """
    _require_login()
    _require(_role(x_role), permissions.CAP_STATS, _user(x_user))

    # 概况只统计「当前账号的库」：企业管理员看到的是自己企业的规模，
    # 而不是 demo 的 8110 —— 这里不切库，首页那张卡就在说谎。
    with _tenant_scope():
        return _stats_snapshot()


def _stats_snapshot() -> dict:
    """在「当前数据集」上取一次概况（切库由调用方负责，见 _tenant_scope）"""
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
        # 丢掉 NULL 档：member_level 可能整列为空（用户未映射等级列；第五轮起取消
        # 「按金额推导等级」，未映射就是未知），那不该显示成「null 占比 xx%」
        levels = {k: v for k, v in cur.fetchall() if k is not None}

        cur.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'user_profile_vectors'"
        )
        columns = cur.fetchone()[0]
    finally:
        conn.rollback()  # 清理查询事务，避免连接停在 idle in transaction
        cur.close()

    total = users or 1
    return {
        "users": users,
        "chunks": chunks,
        "docs": docs,
        "cities": cities,
        "categories": categories,
        "member_levels": levels,
        "profiles_columns": columns,
        # 各等级占比（键就是数据里的真实等级名）。
        # 改前是写死的 diamond_ratio：用户等级叫「黑卡/金卡」时恒为 0.0%，
        # 且 total=0 时会除零。等级名属于数据，不属于接口。
        "level_ratio": {k: f"{v / total * 100:.1f}%" for k, v in levels.items()},
    }


@app.get("/admin/index-status")
def index_status(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """
    检索索引新鲜度：索引是否已经落后于源表

    为什么不做进 /health：
        /health 是**不鉴权**的存活探针，要求快、且不依赖数据库；
        而本检查要扫三张表做 md5 聚合、还会暴露画像与文档规模，
        所以放在需要 CAP_STATS 的管理端点上（与 /stats 同级）。

    为什么需要它：索引与源表之间没有自动失效机制，画像重导后不重建索引
    会**静默**用旧索引检索（详见 data/new-dianshuang/README.md 6.4）。
    status: fresh（一致）/ stale（源表变了）/ unknown（无基线指纹）
    """
    _require_login()
    _require(_role(x_role), permissions.CAP_STATS, _user(x_user))
    return index_freshness()


def _sse(event: str, data: dict) -> str:
    """构造一条 SSE 消息"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _dataset_pinned_stream(dataset: str, inner):
    """
    让同步生成器的**每一次恢复**都跑在同一个数据集上（M3 修跨租户串数据）

    为什么需要它：StreamingResponse 迭代同步生成器走的是 iterate_in_threadpool，
    而 anyio 每次 to_thread.run_sync 都会 copy_context() —— 生成器每 next() 一次
    都在一个**全新的 Context 副本**里执行。所以在生成器内部 `use_dataset()` 只对
    第一段代码生效：从第二段开始（检索 prepare）读的又是默认数据集 demo，
    企业账号的流式回答会引用 demo 的文档，且 `reset_dataset(token)` 在最后一段
    必然抛 "Token was created in a different Context"。

    这里在每次 next 之前重新 pin（见 db.connection.pin_dataset）：每次 Context
    都是一次性的，pin 完不需要（也不可能）配对 reset。
    """
    iterator = iter(inner)
    while True:
        pin_dataset(dataset)
        try:
            item = next(iterator)
        except StopIteration:
            return
        yield item


@app.post("/qa/stream")
def qa_stream(
    req: QueryRequest,
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
):
    """
    流式问答（SSE）

    解决的问题：一次问答 9~17s，其中 92~96% 花在生成。此前用户要「盯着转圈」
    十几秒才看到第一个字；改为流式后，前置检索（约 3~6s）一完成，文字就开始
    逐字出现。**总耗时基本不变，但感知延迟大幅下降。**

    事件类型：
        stage     阶段提示（retrieving / generating）
        meta      元信息（route / sources / cached / deep_thinking），**按角色裁剪后才发出**
        delta     回答正文片段
        reasoning 思维链片段（仅开启深度思考时出现）——**不属于回答**：
                  推理先于正文到达，独立一条通道，不参与 [来源N]、不进「数据来源」
        done      结束
        error     错误

    权限说明（重要）：本函数有 **4 个 meta 出口**（缓存命中 / 检索不可用 / 闲聊 /
    正常生成），每个都单独构造 payload。**每一处都必须过 permissions.render()**——
    漏一个就是一次越权，而这类漏在 code review 里极难发现，因为四个分支长得不像。
    缓存里存的是**完整结果**，裁剪只发生在发出前，所以角色不进缓存键。
    """
    _require_login()
    role, user = _role(x_role), _user(x_user)
    _require(role, permissions.CAP_ANSWER, user)

    limit = permissions.clamp_top_k(
        role, req.top_k, TOP_K_PROFILE_MAX, TOP_K_PROFILE_MIN, user
    )
    # 与 /qa 同一口径：dept 不接受自报，仅管理员可覆盖
    dept = req.dept if permissions.has(role, permissions.CAP_OPS, user) else None
    # 读哪个库由账号推导，且在**请求线程**里先算好：生成器每次恢复都在新的
    # Context 副本里（见 _dataset_pinned_stream），不能指望它自己切库。
    dataset = _tenant_dataset()

    def meta(payload: dict, **extra) -> str:
        """构造 meta 事件：先裁剪再序列化，避免各处漏裁剪"""
        return _sse("meta", permissions.render(payload, role, user) | extra)

    def event_stream():
        # 读哪个库由账号决定（与 /qa 同一口径）：dataset 已在请求线程里算好，
        # 生成器自己**不再切库**——它每次恢复都在一个新的 Context 里，
        # 由 `_dataset_pinned_stream` 在每次 next 之前重新钉住（见其 docstring）。
        if not _tenant_ready(dataset):
            yield _sse("error", {"message": _TENANT_EMPTY})
            return
        try:
            # 命中缓存时直接吐完，不用走生成。
            # 键里带 deep_thinking：开与不开是两份不同的答案，不能互相命中。
            # 缓存里**不存思维链**——它只是展示物、不进答案，存下来让缓存翻倍不划算；
            # 代价是命中缓存时前端拿不到思维链（此时下面也不会发 reasoning 事件）。
            key = answer_cache.make_key(req.question, dept, req.retriever, limit,
                                        req.deep_thinking, dataset=dataset)
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
            # deep_thinking 走 **extra 而不是放进 payload：
            # payload 要过 permissions.render()（只复制白名单字段，这是防越权的关键），
            # 而本字段是**请求方自己发过来的**、不含知识库内容，属「非裁剪项」——
            # 与 cached 同类。（实测：放进 payload 会被 render 静默丢掉。）
            yield meta(
                {"route": route_name, "sources": ctx["sources"], **sql_payload},
                deep_thinking=bool(req.deep_thinking),
            )
            yield _sse("stage", {"stage": "generating"})

            # 推理段与答案段走两个事件：思维链要单独展示，不能混进回答正文
            # （混进去会污染 [来源N] 与「事实/推断」的呈现）
            chunks = []
            for kind, text in generate_events(
                req.question, ctx["candidates"], sql_result,
                deep_thinking=req.deep_thinking,
            ):
                if kind == EVENT_REASONING:
                    yield _sse("reasoning", {"delta": text})
                else:
                    chunks.append(text)
                    yield _sse("delta", {"delta": text})

            # 生成后审查：提示词只是约束，模型仍可能编造未来数据。
            # 流式的 token 已经发出去了，收不回来——所以命中时补一个 replace 事件，
            # 让前端把已经渲染的正文整体覆盖成固定文案（非流式的 /qa 直接在
            # pipeline 层替换，见 _plan_and_retrieve）。
            answer = "".join(chunks)
            guard = answer_guard.inspect(req.question, answer)
            if guard:
                logger.warning("流式答案被后置审查替换：%s", answer_guard.summarize(guard))
                answer = PREDICTION_BLOCKED_REPLY
                yield _sse("replace", {"answer": answer, "guard": guard})

            yield _sse("done", {})
            # 写缓存的是**完整结果**（不裁剪）：否则低权角色先问一次，
            # 高权角色再问就只剩被裁过的版本
            # 答案用审查后的版本：下次同一个问题直接就是固定文案，不会再走一遍生成
            answer_cache.set(key, {
                "answer": answer,
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
        _dataset_pinned_stream(dataset, event_stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/cache/stats")
def cache_stats(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """问答缓存命中情况——用于验证缓存是否真的生效（运维信息，仅管理员）"""
    _require_system_admin()
    return answer_cache.stats()


@app.post("/admin/clear-cache")
def clear_cache(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> StatusResponse:
    """数据或配置更新后清空问答缓存（写操作，仅管理员）"""
    _require_system_admin()
    answer_cache.clear()
    logger.info("问答缓存已清空")
    return {"status": "cleared"}


@app.get("/health")
def health() -> StatusResponse:
    """存活探针：不鉴权。监控系统需要它，且它不泄露任何业务信息"""
    return {"status": "ok"}


# ================= 官网公开 demo 展示（匿名只读） =================
# 首屏星云把「每个光点 = 一位 demo 用户」关联起来，并提供悬停/点选画像、
# 以及真实统计的结果卡数字。安全边界见 api/demo_showcase.py 顶部说明：
# 固定读仓库自带的合成 demo 数据集，接口不接受 dataset/tenant 参数，
# 不返回 profile_text / embedding / 联系方式；企业库不会经过这里。
@app.get("/api/public/demo/users")
def public_demo_users(limit: int = DEMO_SHOWCASE_LIMIT) -> dict:
    """公开只读：官网首屏星云的 demo 用户样本 + demo 场景的真实统计"""
    limit = clamp_demo_limit(limit)
    conn = get_conn(config.DEFAULT_DATASET)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
        total_profiles = cur.fetchone()[0]

        # demo 场景命中用户（用于首屏高亮与三条数据标签）
        cur.execute(
            f"""SELECT user_id, age, gender, city, member_level, order_count,
                       avg_amount::float8, top_category, days_since_last_buy
                FROM user_profile_vectors
                WHERE {DEMO_QUERY_WHERE}
                ORDER BY avg_amount DESC NULLS LAST"""
        )
        matched_rows = cur.fetchall()

        # 结果卡数字：全部由 SQL 实时统计，不在前端写死
        cur.execute(
            f"""SELECT COUNT(*), AVG(avg_amount)::float8, MIN(age), MAX(age)
                FROM user_profile_vectors WHERE {DEMO_QUERY_WHERE}"""
        )
        matched, avg_amount, age_min, age_max = cur.fetchone()

        # 采样：md5 排序做确定性伪随机，覆盖全量用户而不是永远取前 N 条
        cur.execute(
            """SELECT user_id, age, gender, city, member_level, order_count,
                      avg_amount::float8, top_category, days_since_last_buy
               FROM user_profile_vectors
               ORDER BY md5(user_id || 'demo-showcase')
               LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.rollback()  # 只读查询，清事务，避免连接停在 idle in transaction
        cur.close()

    users = [serialize_demo_user(row) for row in rows]
    matched_users = [serialize_demo_user(row) for row in matched_rows]
    # 保证命中用户都在样本里：首屏高亮节点 / 标签要用到他们
    known = {user["uid"] for user in users}
    users += [user for user in matched_users if user["uid"] not in known]

    return {
        "dataset": config.DEFAULT_DATASET,
        "total_profiles": total_profiles,
        "query": {
            "title": DEMO_QUERY_TITLE,
            "matched": matched,
            "avg_amount": round(float(avg_amount), 2) if avg_amount is not None else None,
            "age_min": age_min,
            "age_max": age_max,
        },
        "users": users,
        "matched_users": matched_users,
        "labels": build_demo_labels(matched_users),
    }


# ================= 企业侧离线评测（题库上传 + 后台运行 + 结果查看） =================
# 评测数据按 dataset 分目录：data/eval/<dataset>/...
# dataset 一律由账号推导；企业管理员只能操作自己的空间，系统管理员走 demo 基线。
_EVAL_ACTIVE_BY_DATASET: dict[str, str] = {}
_EVAL_LOCK = threading.Lock()


def _eval_scope() -> tuple[dict, str]:
    """返回 (account, dataset)；只允许管理员，且目标数据空间已构建。"""
    account = _require_manager()
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    # 表存在但可能还是空库：先明确告诉用户，而不是让它跑 50 道全空题
    conn = get_conn(dataset)
    cur = conn.cursor()
    try:
        cur.execute("SELECT (SELECT COUNT(*) FROM user_profile_vectors), (SELECT COUNT(*) FROM wiki_vectors)")
        profiles, chunks = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        cur.close()
        raise HTTPException(status_code=403, detail=f"数据空间不可用：{exc}") from exc
    finally:
        try:
            conn.rollback()
            cur.close()
        except Exception:  # noqa: BLE001
            pass
    if not profiles and not chunks:
        raise HTTPException(status_code=400, detail="当前数据空间还没有可评测的数据，请先完成数据构建")
    return account, dataset


def _eval_scope_name(account: dict) -> str:
    return "platform" if account.get("is_system_admin") else "enterprise"


def _run_eval_task(dataset: str, run_id: str, qset: dict) -> None:
    """后台线程：显式 use_dataset 由 tenant_eval.run_questions 负责。"""
    tenant_eval.mark_active(run_id)
    try:
        def progress(patch: dict) -> None:
            tenant_eval.update_run_progress(dataset, run_id, {
                "status": "running",
                "phase": patch.get("phase") or "评测中",
                "current": patch.get("current", 0),
                "total": patch.get("total", len(qset.get("questions") or [])),
                "progress": patch.get("progress", 0),
            })

        payload = tenant_eval.run_questions(dataset, qset, progress)
        tenant_eval.persist_run_result(dataset, run_id, payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("企业离线评测失败 run_id=%s dataset=%s", run_id, dataset)
        try:
            tenant_eval.mark_run_failed(dataset, run_id, f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001
            logger.exception("写入评测失败状态失败 run_id=%s", run_id)
    finally:
        tenant_eval.mark_inactive(run_id)
        with _EVAL_LOCK:
            if _EVAL_ACTIVE_BY_DATASET.get(dataset) == run_id:
                _EVAL_ACTIVE_BY_DATASET.pop(dataset, None)


@app.get("/api/eval/question-sets")
def eval_question_sets() -> dict:
    account = _require_manager()
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    return {
        "dataset": dataset,
        "scope": _eval_scope_name(account),
        "sets": tenant_eval.list_question_sets(dataset),
        "judge_model": tenant_eval.JUDGE_MODEL,
    }


@app.post("/api/eval/question-sets")
def eval_question_set_create(payload: EvalQuestionSetIn) -> dict:
    account = _require_manager()
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    try:
        questions = tenant_eval.validate_questions(payload.questions)
        saved = tenant_eval.save_question_set(dataset, payload.name, questions)
    except tenant_eval.EvalInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("离线评测题库已保存 dataset=%s set=%s 题数=%s", dataset, saved["id"], saved["count"])
    return {"dataset": dataset, "scope": _eval_scope_name(account), "set": saved}


@app.get("/api/eval/runs")
def eval_runs(limit: int = 10) -> dict:
    account = _require_manager()
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    return {
        "dataset": dataset,
        "scope": _eval_scope_name(account),
        "runs": tenant_eval.list_runs(dataset, limit=limit),
    }


@app.get("/api/eval/runs/latest")
def eval_latest_run() -> dict:
    account = _require_manager()
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    latest = tenant_eval.latest_run(dataset)
    if latest is None:
        return {"dataset": dataset, "scope": _eval_scope_name(account), "run": None, "summary": None, "modules": [], "failures": []}
    data = tenant_eval.read_run(dataset, latest["id"])
    return {"dataset": dataset, "scope": _eval_scope_name(account), **data}


@app.get("/api/eval/runs/{run_id}")
def eval_run_detail(run_id: str) -> dict:
    account = _require_manager()
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    try:
        data = tenant_eval.read_run(dataset, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except tenant_eval.EvalInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"dataset": dataset, "scope": _eval_scope_name(account), **data}


@app.post("/api/eval/runs")
def eval_run_start(payload: EvalRunIn) -> dict:
    account = _require_manager()
    dataset = _tenant_dataset()
    if not _tenant_ready(dataset):
        raise HTTPException(status_code=403, detail=_TENANT_EMPTY)
    try:
        qset = tenant_eval.load_question_set(dataset, payload.set_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except tenant_eval.EvalInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with _EVAL_LOCK:
        active = _EVAL_ACTIVE_BY_DATASET.get(dataset)
        if active:
            raise HTTPException(status_code=409, detail=f"当前数据空间已有评测在运行：{active}")
        meta = tenant_eval.create_run(dataset, qset)
        _EVAL_ACTIVE_BY_DATASET[dataset] = meta["id"]
    tenant_eval.mark_active(meta["id"])
    tenant_eval.update_run_progress(dataset, meta["id"], {"status": "running", "phase": "启动中"})
    thread = threading.Thread(
        target=_run_eval_task,
        args=(dataset, meta["id"], qset),
        name=f"tenant-eval-{meta['id']}",
        daemon=True,
    )
    thread.start()
    logger.info("企业离线评测已启动 dataset=%s run=%s 题数=%s", dataset, meta["id"], meta["total"])
    return {"dataset": dataset, "scope": _eval_scope_name(account), "run": {**meta, "status": "running", "phase": "启动中"}}


@app.post("/admin/reload")
def admin_reload(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> StatusResponse:
    """数据更新后重建 BM25 内存索引（写操作 + 影响性能，仅管理员）"""
    _require_system_admin()
    reload_bm25()
    return {"status": "reloaded"}


# ================= 权限配置（管理员） =================
# 为什么放在 API 层而不是 permissions.py：
# 权限模块只管"配好之后怎么判"，HTTP 语义、请求模型、错误码属于接口边界。
# 每次写操作都会落盘（var/permissions.json），并对下一个请求立即生效——
# 判定路径每次都会重新解析身份 + 读最新配置，没有"改了要重启"这回事。


def _actor(role: str, user: str | None) -> str:
    """审计用：谁改的（用户 ID 优先，没有就记角色）"""
    return f"{role}:{user}" if user else role


@app.get("/admin/permissions")
def get_permissions(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """
    读取当前权限配置 + 能力/等级/角色目录

    目录由后端给：前端若自己写一份能力清单，加新能力时必然漏改一处。
    """
    role, user = _role(x_role), _user(x_user)
    # 全局权限矩阵只有系统管理员能改：企业管理员改的是本企业的人，不是规则
    _require_system_admin()
    view = permissions.admin_view()
    view["actor"] = {
        "role": role,
        "user": user,
        "level": permissions.resolve_level(role, user),
    }
    return view


@app.put("/admin/permissions")
def put_permissions(
    cfg: PermissionConfigIn,
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """
    整份保存「等级→能力」与「角色→等级」

    校验失败返回 400 且**不落盘**：宁可整体拒绝，也不要写进去一半
    （管理员会以为已经生效，实际某条被静默忽略）。
    """
    role, user = _role(x_role), _user(x_user)
    _require_system_admin()

    def _apply(cur: dict) -> dict:
        cur["levels"] = cfg.levels
        cur["role_levels"] = cfg.role_levels
        if cfg.user_levels is not None:
            cur["user_levels"] = cfg.user_levels
        return cur

    try:
        new = permissions.update(_apply, _actor(role, user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "saved", "config": new}


@app.post("/admin/permissions/grant")
def grant_permission(
    payload: GrantIn,
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """
    单点授权/提权：`target_type=role` 改角色默认等级；`target_type=user` 改指定人员

    典型用法：
        {"target_type": "user", "target": "u_1001", "level": "L4"}
        —— 把某个销售人员从 L1 提到 L4（覆盖角色等级，立刻生效）
        {"target_type": "role", "target": "cs", "level": "L4"}
        —— 让所有销售都能看全部信息
    """
    role, user = _role(x_role), _user(x_user)
    _require_system_admin()

    level = (payload.level or "").strip().upper()
    if level not in permissions.LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"等级非法: {payload.level}（可选 {'/'.join(permissions.LEVELS)}）",
        )

    target_type = (payload.target_type or "").strip().lower()
    actor = _actor(role, user)

    def _apply(cur: dict) -> dict:
        if target_type == "role":
            target = (payload.target or "").strip().lower()
            if target not in permissions.ROLES:
                raise ValueError(f"角色非法: {payload.target}")
            if target == permissions.ROLE_GUEST:
                raise ValueError("未识别身份固定为 L0，不能授予等级")
            cur["role_levels"][target] = level
        elif target_type == "user":
            uid = permissions.normalize_user(payload.target)
            if not uid:
                raise ValueError("用户 ID 不能为空")
            cur["user_levels"][uid] = {
                "level": level,
                "note": payload.note or "",
                "updated_at": permissions._now(),  # noqa: SLF001 内部时间戳，避免重复实现
                "updated_by": actor,
            }
        else:
            raise ValueError(f"target_type 只能是 role / user，收到 {payload.target_type!r}")
        return cur

    try:
        new = permissions.update(_apply, actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "granted", "config": new}


@app.delete("/admin/permissions/user/{user_id}")
def revoke_user_permission(
    user_id: str,
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """撤销某个人员的等级覆盖（回到所属角色的默认等级）"""
    role, user = _role(x_role), _user(x_user)
    _require_system_admin()

    uid = permissions.normalize_user(user_id)
    if not uid:
        raise HTTPException(status_code=400, detail="用户 ID 不能为空")

    def _apply(cur: dict) -> dict:
        if uid in cur["user_levels"]:
            cur["user_levels"].pop(uid)
        return cur

    new = permissions.update(_apply, _actor(role, user))
    return {"status": "revoked", "config": new}


@app.post("/admin/permissions/reset")
def reset_permissions(
    x_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_user: str | None = Header(default=None, alias=USER_HEADER),
) -> dict:
    """恢复默认配置（= 代码里的等级表，与改造前行为一致）"""
    role, user = _role(x_role), _user(x_user)
    _require_system_admin()
    new = permissions.reset_config(_actor(role, user))
    return {"status": "reset", "config": new}


# ================= 账号与企业（管理员） =================
# 两套管理范围，不能混：
#   系统管理员：审核企业账号、管所有账号、改全局权限矩阵；
#   企业管理员：只管本企业的员工（审核 / 改角色 / 停用），不能碰全局规则。
# 企业管理员的能力来自账号标记，不来自等级——等级决定"能看什么"。

# 能分配给员工业务角色（不含 admin / ent_admin：那两个身份由审核产生，
# 不是"等级高低"可以随便勾的）——定义在 permissions.ASSIGNABLE_ROLES，避免两份真源。
_ENTERPRISE_ASSIGNABLE_ROLES = permissions.ASSIGNABLE_ROLES


def _assignable_roles(actor: dict) -> tuple[str, ...]:
    """当前管理员能分配的角色：系统管理员多一个 admin，两边都没有 ent_admin"""
    if actor.get("is_system_admin"):
        return (permissions.ROLE_ADMIN,) + _ENTERPRISE_ASSIGNABLE_ROLES
    return _ENTERPRISE_ASSIGNABLE_ROLES


def _public_user(user: dict | None) -> dict | None:
    """出网前去掉 password_hash —— 不该出现的字段就别出现在响应里"""
    if user is None:
        return None
    keys = (
        "id", "username", "contact", "display_name", "account_type", "account_type_label",
        "role", "role_label", "enterprise_id", "status", "status_label",
        "is_system_admin", "is_enterprise_admin",
        "created_at", "reviewed_at", "reviewed_by", "last_login_at",
    )
    data = {k: user.get(k) for k in keys}
    data["role_label"] = permissions.ROLE_LABELS.get(user.get("role"), user.get("role"))
    return data


def _check_target_scope(actor: dict, target: dict) -> None:
    """统一的越权检查：改谁之前先确认"这是不是你能管的人" """
    if target.get("is_system_admin"):
        raise HTTPException(status_code=403, detail="系统管理员账号不可在此修改")
    if not actor.get("is_system_admin"):
        if target.get("enterprise_id") != actor.get("enterprise_id"):
            raise HTTPException(status_code=403, detail="只能管理本企业的账号")
        if target.get("account_type") == auth.ACCOUNT_ENTERPRISE:
            raise HTTPException(status_code=403, detail="企业账号只能由系统管理员审核")
        if target.get("is_enterprise_admin"):
            # 企业管理员之间是平级：能审核/停用员工，但不能互相改动，
            # 否则同一企业里先被通过的那个人就能把另一个管理员停掉。
            raise HTTPException(status_code=403, detail="企业管理员账号只能由系统管理员调整")


@app.get("/admin/users")
def admin_list_users() -> dict:
    """账号列表：系统管理员看全部，企业管理员看本企业"""
    actor = _require_manager()
    if actor.get("is_system_admin"):
        users = auth.list_users(None)
        enterprises = auth.list_enterprises()
        scope = "all"
    else:
        users = auth.list_users(actor["enterprise_id"])
        ent = auth.enterprise_of(actor)
        enterprises = [ent] if ent else []
        scope = "enterprise"
    return {
        "users": [_public_user(u) for u in users],
        "enterprises": enterprises,
        "scope": scope,
        "me": _public_user(actor),
        # 只给能分配的角色：ent_admin 由企业账号审核产生，不出现在这里
        "roles": [
            {"value": r, "label": permissions.ROLE_LABELS[r], "level": permissions.resolve_level(r)}
            for r in _assignable_roles(actor)
        ],
    }


@app.post("/admin/users/{user_id}/approve")
def admin_approve_user(user_id: int, payload: ApproveIn) -> dict:
    """审核通过 + 分配角色。企业账号通过后会生成企业库与邀请码。"""
    actor = _require_manager()
    target = auth.find_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    _check_target_scope(actor, target)

    if target["account_type"] == auth.ACCOUNT_ENTERPRISE:
        # 企业账号通过后就是本企业的管理员，角色由账号类型决定，不看下拉框
        role = permissions.ROLE_ENT_ADMIN
    else:
        role = (payload.role or "").strip().lower()
        if role not in _assignable_roles(actor):
            raise HTTPException(
                status_code=400,
                detail="角色只能是 管理层 / 分析师 / 运营 / 销售"
                + ("（系统管理员可另选系统管理员）" if actor.get("is_system_admin") else ""),
            )
    try:
        user = auth.approve(user_id, role, actor["username"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 企业账号：把企业库注册进 DATASETS（白名单），否则第一次构建会 UnknownDataset
    if user["account_type"] == auth.ACCOUNT_ENTERPRISE:
        ent = auth.enterprise_of(user)
        if ent:
            config.register_dataset(ent["dataset"], config.enterprise_db_name(ent["id"]))
            logger.info("企业库已注册: %s -> %s", ent["dataset"], config.enterprise_db_name(ent["id"]))
    return {"status": "approved", "user": _public_user(user), "enterprise": auth.enterprise_of(user)}


@app.post("/admin/users/{user_id}/role")
def admin_set_user_role(user_id: int, payload: UserRoleIn) -> dict:
    """改角色（角色 → 默认等级，决定这个账号能看到什么）"""
    actor = _require_manager()
    target = auth.find_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    _check_target_scope(actor, target)

    role = (payload.role or "").strip().lower()
    if role not in _assignable_roles(actor):
        raise HTTPException(
            status_code=400,
            detail="角色只能是 管理层 / 分析师 / 运营 / 销售"
            + ("（系统管理员可另选系统管理员）" if actor.get("is_system_admin") else ""),
        )
    try:
        user = auth.set_role(user_id, role, actor["username"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "ok", "user": _public_user(user)}


@app.post("/admin/users/{user_id}/status")
def admin_set_user_status(user_id: int, payload: UserStatusIn) -> dict:
    """启用 / 停用账号（停用后会话立即失效：鉴权每请求都查状态）"""
    actor = _require_manager()
    target = auth.find_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    _check_target_scope(actor, target)
    try:
        user = auth.set_status(user_id, (payload.status or "").strip().lower(), actor["username"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "ok", "user": _public_user(user)}


@app.post("/admin/users/{user_id}/reject")
def admin_reject_user(user_id: int) -> dict:
    """
    审核拒绝：未通过的申请不进入系统，但**保留账号记录**

    不删号的原因：同一个人可能重新申请，审计也需要"谁在什么时候拒了谁"。
    拒绝后不能登录；管理员可以再调 `/approve` 改判。
    """
    actor = _require_manager()
    target = auth.find_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    _check_target_scope(actor, target)
    try:
        user = auth.reject(user_id, actor["username"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "rejected", "user": _public_user(user)}
