#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : permissions.py
@Function: 等级 / 角色 / 能力——访问控制的唯一真源（含运行时配置的持久化）

为什么要集中在一个模块
--------------------
权限最容易做错的地方不是"能不能判断"，而是**判断散布在多个出口**：
一次问答有 3 个响应出口（`/qa` 直接返回、`/qa/stream` 的 meta、缓存命中直吐），
任何一处忘了裁剪就是一次越权。所以这里提供**唯一**的 `render()`，
所有出口都必须过它。

两级模型：等级（L1~L4）→ 能力（capability）
------------------------------------------
管理员配的是「**某个等级能干什么**」，业务代码只判「**有没有某个能力**」：

    L1 基础 → 回答
    L2 依据 → + 来源列表 / 返回用户数
    L3 内部 → + 检索过程（检索式 / 原文片段 / 精排分数）
    L4 完全 → + SQL 原文 / 融合与精排 / 数据概况 / 召回对比 / 运维接口

这样做的好处：管理员调权限不需要改代码，业务代码也不会出现「判角色名」这种
绕过等级的写法。`L0` 固定给未识别身份（guest），**不参与配置**——
允许配置等于给匿名开口子。

身份 = 角色 + 可选用户
--------------------
- 角色（`X-Role`）：一组成员的上限，管理员按角色配默认等级
  （如「销售人员 = L1」）。
- 用户（`X-User`，可选）：对**指定人员**的覆盖，优先于角色等级
  （如「把销售张三从 L1 提到 L4」）。

⚠ Demo 阶段两者都由请求头自报，**不是安全边界**；接入电商系统后必须改成
「登录态 → 角色/用户」，届时删掉 API 层的 Header 依赖即可，本模块接口不用动。

实时生效与持久化
----------------
配置写在 `var/permissions.json`（`RAG_PERMISSIONS_PATH` 可覆盖）：

- 写入用「临时文件 + `os.replace`」原子替换，进程崩在中间也不会留下半个 JSON；
- 读取前先 `stat` 比对 mtime/size，变了就重载 —— 管理员保存后**不用重启**，
  多进程（`uvicorn --workers`）也能各自感知到变化；
- 文件不存在 = 用代码里的默认配置（与改造前的静态表完全一致，行为不变）；
- 文件损坏 = 记错误日志 + 回退默认配置。宁可回到默认（严格），也不要放行。

设计原则（四条，都来自实际踩过的坑）
----------------------------------
1. **裁剪只发生在响应序列化那一刻**，缓存里存的始终是完整结果。
2. **角色/用户不能由调用方自报**——生产环境必须从登录态取（见上）。
3. **普通角色用不了的功能直接不提供**：接口层 403、前端不渲染入口，
   不做"点一下告诉我没权限"那种交互。
4. **`route == "error"` 必须对所有人透出**：数据库挂掉若被裁成普通回复，
   用户会把"服务坏了"当成"资料里没有"（本仓库为此专门加过兜底文案）。
"""
import copy
import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable

from rag_demo import media

logger = logging.getLogger(__name__)

# ==================== 角色 ====================

ROLE_ADMIN = "admin"        # 系统管理员
ROLE_ENT_ADMIN = "ent_admin"  # 企业管理员（企业账号审核通过后的身份，只管本企业）
ROLE_EXEC = "exec"          # 管理层
ROLE_ANALYST = "analyst"    # 数据分析师 / 产品
ROLE_OPS = "ops"            # 运营 / 市场
ROLE_CS = "cs"              # 销售 / 客服
ROLE_GUEST = "guest"        # 未识别身份（非法或缺失角色一律降级到这里）

ROLES = (ROLE_ADMIN, ROLE_ENT_ADMIN, ROLE_EXEC, ROLE_ANALYST, ROLE_OPS, ROLE_CS, ROLE_GUEST)

ROLE_LABELS = {
    ROLE_ADMIN: "系统管理员",
    ROLE_ENT_ADMIN: "企业管理员",
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
CAP_SQL = "sql"                # 能看到 SQL 原文与执行报错（结果行不算，见 render）
CAP_INTERNALS = "internals"    # 能看到 trace / 原文片段 / 精排分数 / 检索式
CAP_TRACE_FLOW = "trace_flow"  # 能看到「融合与精排」汇总：融合条数 / 各池名额 / 画像池基数
CAP_STATS = "stats"            # 能看到 /stats 数据概况
CAP_RAW_SEARCH = "raw_search"  # 能调用 /search（只召回不生成，最敏感）
CAP_OPS = "ops"                # 能调用 /admin/*（清缓存、重建索引、改权限）
CAP_TOPK = "topk"              # 能调整"返回多少个用户"
# 企业空间管理：管本企业的成员（审核/角色/停用）。
# **不在等级矩阵里**——它是「身份自带」的能力（企业管理员这个角色），
# 不是"看到多少信息"的等级；允许管理员把它勾给 L1 只会让所有人都能管人。
CAP_TENANT = "tenant"

# 顺序即前端权限矩阵的列顺序：从"人人需要"到"最敏感"
CAP_ORDER = (
    CAP_ANSWER, CAP_SOURCES, CAP_TOPK, CAP_INTERNALS,
    CAP_TRACE_FLOW, CAP_SQL, CAP_STATS, CAP_RAW_SEARCH, CAP_OPS,
)

CAP_LABELS = {
    CAP_ANSWER: "回答",
    CAP_SOURCES: "来源列表",
    CAP_TOPK: "返回用户数",
    CAP_INTERNALS: "检索过程",
    CAP_TRACE_FLOW: "融合与精排",
    CAP_SQL: "SQL 原文",
    CAP_STATS: "数据概况",
    CAP_RAW_SEARCH: "召回对比",
    CAP_OPS: "运维 / 权限管理",
    CAP_TENANT: "本企业成员管理",
}

CAP_DESCRIPTIONS = {
    CAP_ANSWER: "能提业务问题并拿到回答（关掉等于禁止使用系统）",
    CAP_SOURCES: "回答的「数据来源」列表（编号 + 来源名）",
    CAP_TOPK: "可调整「返回多少个用户」",
    CAP_INTERNALS: "各路检索式、原文片段、精排分数（走的路径）",
    CAP_TRACE_FLOW: "融合与精排链路：召回 / 池名额 / 合并去重",
    CAP_SQL: "生成的 SQL 原文与执行报错（查询结果行不受此项控制）",
    CAP_STATS: "/stats 数据概况",
    CAP_RAW_SEARCH: "/search 召回对比（绕过生成直接吐原文）",
    CAP_OPS: "/admin/* 运维接口 + 本页的权限配置",
    CAP_TENANT: "审核本企业员工、改角色、停用（不能碰全局规则）",
}

# ==================== 等级（L1~L4） ====================

LEVEL_L1 = "L1"
LEVEL_L2 = "L2"
LEVEL_L3 = "L3"
LEVEL_L4 = "L4"
LEVEL_NONE = "L0"   # 未识别身份：不参与配置，且没有任何能力

LEVELS = (LEVEL_L1, LEVEL_L2, LEVEL_L3, LEVEL_L4)

LEVEL_LABELS = {
    LEVEL_NONE: "L0 未识别（无权限）",
    LEVEL_L1: "L1 基础",
    LEVEL_L2: "L2 依据",
    LEVEL_L3: "L3 内部",
    LEVEL_L4: "L4 完全",
}

LEVEL_DESCRIPTIONS = {
    LEVEL_L1: "只能提问并看到回答",
    LEVEL_L2: "追加来源列表与「返回用户数」",
    LEVEL_L3: "追加检索过程：检索式、原文片段、精排分数",
    LEVEL_L4: "全部信息 + 运维与权限管理接口",
}

# 默认等级 → 能力。**与改造前的静态权限表一一对应**（升级不应改变任何人看到的东西）：
#   admin=L4  exec=L3（有过程、无 SQL/链路）  analyst/ops=L2  cs=L1  guest=L0
DEFAULT_LEVEL_CAPS: dict[str, tuple[str, ...]] = {
    LEVEL_L1: (CAP_ANSWER,),
    LEVEL_L2: (CAP_ANSWER, CAP_SOURCES, CAP_TOPK),
    LEVEL_L3: (CAP_ANSWER, CAP_SOURCES, CAP_TOPK, CAP_INTERNALS),
    LEVEL_L4: (
        CAP_ANSWER, CAP_SOURCES, CAP_TOPK, CAP_INTERNALS,
        CAP_TRACE_FLOW, CAP_SQL, CAP_STATS, CAP_RAW_SEARCH, CAP_OPS,
    ),
}

DEFAULT_ROLE_LEVELS: dict[str, str] = {
    ROLE_ADMIN: LEVEL_L4,
    # 企业管理员：自己企业的经营者，默认与「管理层」同档（L3），
    # 能看到检索过程但拿不到 SQL 原文 / 运维接口——那些属于平台方。
    ROLE_ENT_ADMIN: LEVEL_L3,
    ROLE_EXEC: LEVEL_L3,
    ROLE_ANALYST: LEVEL_L2,
    ROLE_OPS: LEVEL_L2,
    ROLE_CS: LEVEL_L1,
    ROLE_GUEST: LEVEL_NONE,
}

# ==================== 身份自带能力 ====================

# 由「这个身份是什么」决定的能力，与等级矩阵**并行**：既不能被等级授予，
# 也不会被等级升降影响。目前只有一条——企业管理员管本企业成员。
# 判「能管谁」靠的是账号标记（auth 的 is_enterprise_admin）与租户范围校验，
# 这里补齐的是权限层的一致性：`/whoami` 的 `can.tenant` 与企业管理员身份对得上。
IDENTITY_CAPS: dict[str, tuple[str, ...]] = {
    ROLE_ENT_ADMIN: (CAP_TENANT,),
}

# 管理员**能分配给别人的**业务角色：
# - 不含 admin：那是系统管理员，只能由系统管理员的审核入口产生；
# - 不含 ent_admin：企业管理员由「企业账号审核通过」产生，
#   把它当普通角色发出去，等于随手发一个「能管人」的身份。
ASSIGNABLE_ROLES = (ROLE_EXEC, ROLE_ANALYST, ROLE_OPS, ROLE_CS)

# ==================== 配置文件（持久化 + 实时生效） ====================

# 单独算基目录，不 import config：那个模块会拉起 torch，
# 而权限判定被单测/脚本直接调用，不该为此付几秒的导入代价。
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.environ.get("RAG_PERMISSIONS_PATH") or os.path.join(
    _BASE_DIR, "var", "permissions.json"
)

_LOCK = threading.RLock()
_cache: dict[str, Any] | None = None
_cache_sig: tuple[int, int] | None = None


def _now() -> str:
    """本地时间 ISO 串：管理员看的是"我几点改的"，不是 UTC"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _default_config() -> dict[str, Any]:
    return {
        "version": 0,
        "levels": {lv: list(DEFAULT_LEVEL_CAPS[lv]) for lv in LEVELS},
        "role_levels": dict(DEFAULT_ROLE_LEVELS),
        "user_levels": {},
        "updated_at": None,
        "updated_by": None,
    }


def _file_sig() -> tuple[int, int] | None:
    try:
        st = os.stat(CONFIG_PATH)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """
    校验并归一化一份配置，非法输入一律抛 ValueError（由调用方转成 400）

    为什么不"尽力修复"：配置错一半比整体拒绝更危险——
    管理员以为已经生效，实际某条被静默忽略。
    """
    if not isinstance(raw, dict):
        raise ValueError("权限配置必须是对象")

    default = _default_config()

    # 1) 等级 → 能力
    levels: dict[str, list[str]] = {}
    raw_levels = raw.get("levels") or {}
    if not isinstance(raw_levels, dict):
        raise ValueError("levels 必须是 {等级: [能力]} 结构")
    for lv in LEVELS:
        caps = raw_levels.get(lv, default["levels"][lv])
        if not isinstance(caps, (list, tuple)):
            raise ValueError(f"{lv} 的能力清单必须是数组")
        unknown = [c for c in caps if c not in CAP_LABELS]
        if unknown:
            raise ValueError(f"{lv} 含未知能力: {', '.join(map(str, unknown))}")
        if CAP_TENANT in caps:
            # 企业成员管理不按等级授予：它是企业管理员这个身份自带的。
            # 放进来要么被下面的 CAP_ORDER 过滤静默丢掉（管理员以为配上了），
            # 要么所有人勾一下 L1 就都能管人——两种都不可接受，直接拒绝。
            raise ValueError(
                "「本企业成员管理」由企业管理员身份自带，不能按等级授予或撤销"
            )
        # 按 CAP_ORDER 归一：同一份配置两次保存得到完全相同的文件，便于比对
        levels[lv] = [c for c in CAP_ORDER if c in caps]

    # 2) 角色 → 等级
    role_levels: dict[str, str] = {}
    raw_roles = raw.get("role_levels") or {}
    if not isinstance(raw_roles, dict):
        raise ValueError("role_levels 必须是 {角色: 等级} 结构")
    for role in ROLES:
        lv = raw_roles.get(role, default["role_levels"][role])
        lv = str(lv).strip().upper()
        if role == ROLE_GUEST:
            # guest 恒为 L0：给匿名身份配等级等于把门敞开
            if lv not in (LEVEL_NONE, ""):
                logger.warning("忽略 guest 的等级配置 %s（匿名身份恒为 L0）", lv)
            role_levels[role] = LEVEL_NONE
            continue
        if lv not in LEVELS:
            raise ValueError(f"角色 {role} 的等级非法: {lv}（可选 {'/'.join(LEVELS)}）")
        role_levels[role] = lv

    # 3) 用户 → 等级（覆盖角色等级）
    user_levels: dict[str, dict[str, Any]] = {}
    raw_users = raw.get("user_levels") or {}
    if not isinstance(raw_users, dict):
        raise ValueError("user_levels 必须是 {用户ID: 等级} 结构")
    for uid, item in raw_users.items():
        uid = str(uid).strip()
        if not uid:
            continue
        if len(uid) > 64:
            raise ValueError(f"用户 ID 过长（>64）: {uid[:20]}…")
        if isinstance(item, dict):
            lv = str(item.get("level", "")).strip().upper()
            note = str(item.get("note") or "")
            updated_at = item.get("updated_at")
            updated_by = item.get("updated_by")
        else:
            lv = str(item).strip().upper()
            note, updated_at, updated_by = "", None, None
        if lv not in LEVELS:
            raise ValueError(f"用户 {uid} 的等级非法: {lv}（可选 {'/'.join(LEVELS)}）")
        user_levels[uid] = {
            "level": lv,
            "note": note,
            "updated_at": updated_at,
            "updated_by": updated_by,
        }

    # 4) 自锁保护：管理员必须保留 CAP_OPS
    #    否则管理员把自己降成 L1 之后，没有任何人还能打开权限页——只能去改文件。
    admin_level = role_levels[ROLE_ADMIN]
    if CAP_OPS not in levels[admin_level]:
        raise ValueError(
            f"管理员角色当前是 {admin_level}，该等级没有「运维 / 权限管理」能力："
            "保存后将没有人能再修改权限。请先给该等级勾上 CAP_OPS，或调高管理员等级。"
        )

    return {
        "version": int(raw.get("version") or 0),
        "levels": levels,
        "role_levels": role_levels,
        "user_levels": user_levels,
        "updated_at": raw.get("updated_at"),
        "updated_by": raw.get("updated_by"),
    }


def _write(cfg: dict[str, Any]) -> None:
    """原子写：先写 tmp 再 replace，避免写到一半被读到 / 崩溃留下坏文件"""
    directory = os.path.dirname(CONFIG_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{CONFIG_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CONFIG_PATH)


def _load() -> dict[str, Any]:
    """读配置：先比 stat，文件没变就直接用缓存（每次鉴权都要读，不能每次解析 JSON）"""
    global _cache, _cache_sig
    sig = _file_sig()
    with _LOCK:
        if _cache is not None and sig == _cache_sig:
            return _cache
        if sig is None:
            _cache, _cache_sig = _default_config(), None
            return _cache
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _cache = _normalize(json.load(f))
        except Exception as e:  # noqa: BLE001 配置坏了不能把服务带崩
            logger.error("权限配置读取失败，回退默认配置（%s）: %s", CONFIG_PATH, e)
            _cache = _default_config()
        _cache_sig = sig
        return _cache


def current_config() -> dict[str, Any]:
    """当前生效的配置（深拷贝：调用方改了也影响不到缓存）"""
    return copy.deepcopy(_load())


def update(mutator: Callable[[dict[str, Any]], dict[str, Any] | None], actor: str) -> dict[str, Any]:
    """
    读-改-写一次配置（授权 / 撤销 / 恢复默认都走它）

    整个读改写过程持锁：否则两个管理员同时保存，后写的会覆盖前一个的改动。
    """
    global _cache, _cache_sig
    with _LOCK:
        cfg = copy.deepcopy(_load())
        new = mutator(cfg) or cfg
        new = _normalize(new)
        new["version"] = int(cfg.get("version") or 0) + 1
        new["updated_at"] = _now()
        new["updated_by"] = actor
        _write(new)
        _cache, _cache_sig = new, _file_sig()
        logger.info(
            "权限配置已更新 v%s by %s: roles=%s users=%s",
            new["version"], actor,
            {r: lv for r, lv in new["role_levels"].items() if lv != LEVEL_NONE},
            {u: v["level"] for u, v in new["user_levels"].items()},
        )
        return copy.deepcopy(new)


def reset_config(actor: str) -> dict[str, Any]:
    """恢复默认配置（默认 = 代码里那张表，与改造前行为一致）"""
    def _reset(_cfg: dict[str, Any]) -> dict[str, Any]:
        return _default_config()

    return update(_reset, actor)


# ==================== 角色 / 等级解析 ====================


def resolve_role(value: str | None, default: str = ROLE_GUEST) -> str:
    """
    把外部传入的角色标识解析成合法角色

    - **请求头缺失**（value 为 None 或空白）→ 返回 `default`
    - **请求头是非法值**（如 "root"、"admin2"）→ 一律降级为 guest，不放行

    两种情况必须区分开：缺失代表"调用方没带身份"，非法代表"调用方编了一个身份"。
    后者按 guest 处理，绝不允许落到有权限的角色上。

    ⚠ Demo 阶段角色由请求头 `X-Role` 传入，**调用方可以自报**——这在生产是不可接受的
    （等同于 ODD-09 那个"dept 由调用方自报"的越权口子）。接入电商系统后必须改为
    「登录态 → 角色」，并把 `default` 从 admin 改成 guest。
    """
    if value is None or not str(value).strip():
        return default
    role = str(value).strip().lower()
    return role if role in ROLES else ROLE_GUEST


def normalize_user(value: str | None) -> str | None:
    """
    规范化请求头里的用户 ID（空白 → None，超长截断）

    不做字符白名单：ID 是外部系统的标识，本模块只负责"按字符串匹配"，
    真正该校验的是用户是否存在——那属于登录态，不归这里管。
    """
    if value is None:
        return None
    uid = str(value).strip()
    return uid[:64] if uid else None


def resolve_level(role: str, user: str | None = None) -> str:
    """
    有效等级 = 用户覆盖 > 角色默认

    `L0` 表示没有任何能力，只会出现在 guest（或未配置的角色）上。
    """
    cfg = _load()
    if user:
        override = cfg["user_levels"].get(user)
        if override:
            return override["level"]
    return cfg["role_levels"].get(role, LEVEL_NONE)


def capabilities(role: str, user: str | None = None) -> frozenset[str]:
    """
    当前身份的能力集合（每次请求都重新算，管理员改完立刻生效）

    = 等级授予的能力 ∪ 身份自带的能力。后者（`IDENTITY_CAPS`）不受等级影响：
    企业管理员被降成 L1，也只是"少看些信息"，不会因此失去管本企业成员的身份。
    """
    caps = set(IDENTITY_CAPS.get(role, ()))
    level = resolve_level(role, user)
    if level != LEVEL_NONE:
        caps |= set(_load()["levels"].get(level, ()))
    return frozenset(caps)


def has(role: str, cap: str, user: str | None = None) -> bool:
    return cap in capabilities(role, user)


def allowed_topk_roles() -> list[str]:
    """能调 top_k 的角色（按选择器顺序，供前端展示）"""
    return [r for r in ROLE_SELECTOR_ORDER if CAP_TOPK in capabilities(r)]


# ==================== 给前端的自描述 ====================

# `can` 的键名是前端用的短名（历史原因：`ask` 对应 CAP_ANSWER），
# 直接回传能力名会迫使前端跟着改一遍，没必要。
_CAN_KEYS = {
    "ask": CAP_ANSWER,
    "sources": CAP_SOURCES,
    "sql": CAP_SQL,
    "internals": CAP_INTERNALS,
    "trace_flow": CAP_TRACE_FLOW,
    "stats": CAP_STATS,
    "raw_search": CAP_RAW_SEARCH,
    "ops": CAP_OPS,
    "topk": CAP_TOPK,
    "tenant": CAP_TENANT,
}


def describe(role: str, user: str | None = None) -> dict[str, Any]:
    """
    给前端的自描述：前端据此决定渲染什么，不在前端硬编码权限表

    传 `user` 是为了让「指定人员提权」在页面上立刻可见——
    同一个角色 + 不同用户，返回的能力可能完全不同。
    """
    level = resolve_level(role, user)
    caps = capabilities(role, user)
    return {
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "user": user,
        "level": level,
        "level_label": LEVEL_LABELS.get(level, level),
        "capabilities": sorted(caps),
        "can": {key: cap in caps for key, cap in _CAN_KEYS.items()},
    }


def admin_view() -> dict[str, Any]:
    """
    权限配置页需要的全部素材：当前配置 + 能力/等级/角色目录 + 默认值

    目录也在后端给：前端若自己写一份能力清单，加新能力时必然漏改一处。
    """
    cfg = current_config()
    return {
        "config": cfg,
        "path": CONFIG_PATH,
        "levels": [
            {"value": lv, "label": LEVEL_LABELS[lv], "description": LEVEL_DESCRIPTIONS[lv]}
            for lv in LEVELS
        ],
        "capabilities": [
            {"value": cap, "label": CAP_LABELS[cap], "description": CAP_DESCRIPTIONS[cap]}
            for cap in CAP_ORDER
        ],
        # 用 ROLES 而不是 ROLE_SELECTOR_ORDER：企业管理员也要能在这里看到并调整
        # 默认等级（它决定企业管理员能看到多少业务信息），但它不出现在问答页的
        # 身份下拉里——那不是可以「切换成」的身份，是由账号审核产生的。
        "roles": [
            {"value": r, "label": ROLE_LABELS[r], "level": cfg["role_levels"].get(r, LEVEL_NONE)}
            for r in ROLES
        ],
        "defaults": _default_config(),
    }


# ==================== 响应裁剪（唯一出口） ====================

# 「无权限时的统一文案」——接口层 403 用。
# 刻意不透露"有什么功能被挡住了"：普通角色用不了的能力是**不设计**，
# 而不是"设计了再告诉他没权限"（那样等于把内部功能清单报给每个人）。
FORBIDDEN_DETAIL = "当前身份无权访问该接口"

# 「来源N」引用标记：低权角色看不到来源列表时，留着这些标记反而像坏了
_CITE_RE = re.compile(r"\[来源\s*\d+\]")


def answer_for(text: str, role: str, user: str | None = None) -> str:
    """
    按角色处理回答正文

    看不到来源列表的角色，正文里的 `[来源N]` 指向一个他看不见的东西——
    留着比去掉更糟（看着像功能坏了）。这里只去掉**编号引用**，
    `[来源：结构化查询结果]` 这类散文式标注不去（它本身自解释）。

    注意：流式接口不用这个函数。delta 是逐片吐的，引用标记可能被切成两片，
    服务端按片正则匹配会漏；那一路改由前端按 `can.sources` 处理（见 app.js）。
    """
    if CAP_SOURCES in capabilities(role, user):
        return text or ""
    return _CITE_RE.sub("", text or "")


def _render_source(src: dict, caps: frozenset[str]) -> dict:
    """层级：L2 只给编号与来源名；L3 才给原文片段、分数、命中路径与图片"""
    out = {"index": src.get("index"), "source": src.get("source")}
    if CAP_INTERNALS in caps:
        out.update({
            "text": src.get("text", ""),
            "origin_query": src.get("origin_query", ""),
            "from_query": src.get("from_query", ""),
            "strategies": src.get("strategies", []),
            "rerank_score": src.get("rerank_score"),
            "expanded": src.get("expanded", False),
            "expand_scope": src.get("expand_scope", ""),
            "parent_key": src.get("parent_key", ""),
            # 图片与原文片段同级：能看到正文才看得到配图。
            # 签名必须在**响应时**做（缓存里只存 key），所以放在这个唯一出口，
            # 而不是 pipeline 组装 sources 的地方——见 media.sign_images 的说明。
            "images": media.sign_images(src.get("images")),
        })
    return out


# 「融合与精排」靠这几个汇总字段渲染：融合条数 / 各池名额 / 画像池基数。
# 它们是 trace 的一部分，但权限级别比「各路检索式」更高（L4），
# 所以单独挑出来，而不是把整个 trace 一起裁掉——否则 L3 连「走的路径」都没了。
_TRACE_FLOW_KEYS = ("fused_count", "limits", "profile_pool_count", "wiki_doc_dedup")


def _render_trace(trace: dict, caps: frozenset[str]) -> dict:
    """trace 内部再分级：L3 拿各路明细，L4 额外拿融合汇总"""
    out = dict(trace)
    if CAP_TRACE_FLOW not in caps:
        for key in _TRACE_FLOW_KEYS:
            out.pop(key, None)
    return out


def render(payload: dict, role: str, user: str | None = None) -> dict:
    """
    按等级裁剪一次问答的响应（**所有出口都必须过这里**）

    被裁掉的字段不是"置空"，而是**整键移除**——前端拿不到就不会渲染，
    也不会有人误以为"有值但没显示"。

    `route` 无条件保留：error / chitchat 这两种走向本身就是用户必须知道的信息。
    """
    caps = capabilities(role, user)
    out: dict[str, Any] = {"route": payload.get("route")}

    if "answer" in payload:
        out["answer"] = answer_for(payload.get("answer") or "", role, user)

    if "cached" in payload:
        out["cached"] = payload["cached"]

    if CAP_SOURCES in caps and payload.get("sources") is not None:
        out["sources"] = [_render_source(s, caps) for s in payload["sources"]]

    # 本轮检索到的用户池卡片：业务事实，和来源列表同级（L2+ 可见）。
    if CAP_SOURCES in caps and payload.get("user_cards") is not None:
        out["user_cards"] = list(payload["user_cards"])[:30]

    # 查询结果行是**业务事实**（与回答里的数字同源），所有能提问的身份都能看；
    # 只有 SQL 原文与执行报错属于实现细节（L4）。二者不能捆在同一个能力上：
    # 捆在一起会让「不想给 SQL 语句」连带把用户已经能从回答里看到的数字也藏掉。
    for key in ("rows_count", "sql_rows"):
        if key in payload:
            out[key] = payload[key]

    if CAP_SQL in caps:
        for key in ("sql", "sql_error"):
            if key in payload:
                out[key] = payload[key]

    if CAP_INTERNALS in caps and payload.get("trace") is not None:
        out["trace"] = _render_trace(payload["trace"], caps)

    return out


# ==================== top_k 的权限收窄 ====================


def clamp_top_k(
    role: str, value: int | None, max_value: int, min_value: int = 1,
    user: str | None = None,
) -> int | None:
    """
    收窄用户传的 top_k

    - 无权限的角色：**忽略**传值，返回 None（走系统默认），而不是报错——
      报错等于告诉对方"这里有个参数你能用"，属于多余的信息暴露
    - 有权限的角色：夹到 [min_value, max_value]，超出上限按上限处理
    """
    if value is None or not has(role, CAP_TOPK, user):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return max(min_value, min(n, max_value))
