#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : app.py
@Function: MVP 向导 —— 四步「上传 → 确认 → 构建 → 查询」的接口实现（M2 迭代区）

本模块对外提供两样东西：

    router —— `/api/wizard/*` 的接口实现。**8000 的正式服务直接挂它**
              （见 api/wizard.py），所以这套向导接口全服务只有一份实现，
              不存在「demo 版一份、正式版一份」的漂移。

    app    —— 一个自包含的独立服务，给「只想看界面」时用：不 import
              config / torch / 数据库，启动毫秒级，离线也能演示。

M2 进度（四步都已接真）：
    第 1 步 上传   **真的**：multipart 落盘 → 统一转 UTF-8 → pandas 真读出行数与列名
    第 2 步 字段   **真的**：同义词字典匹配，key 与入库口径同一套（FIELD_DEFS）
    第 3 步 构建   **真的**：真 ingest 写库（writes_to 守卫 + dataset_lock 互斥 +
                   真实进度事件）。编排在 builder.py，那里有完整说明
    第 4 步 查询   **真的**：走与首页 /qa 同一条 pipeline（检索 → 精排 → 生成），
                   答案与 sources 都来自它；按请求切到用户构建的那个数据集。
                   构建期间谢绝查询由真锁判定（整段问答持锁，原因见 query 的注释）

写库前的纪律（M2 首次真实构建的约束）：
    真实构建只允许写 user / test 两个数据集（builder.BUILDABLE_DATASETS）；
    **demo 永远不在白名单**——它是演示底座 + 评测基线，只由仓库自带数据重建。
    第一次跑真实链路请用 test（`POST /build {"dataset": "test"}`）先验证守卫与并发，
    再动 user。理由见 config.TEST_DB_CONFIG 的注释。

启动（项目根目录下执行；正式入口是 8000 的 `/wizard`，这里只是调试用）：
    uv run uvicorn rag_demo.mvp.app:app --port 8002

访问：
    http://127.0.0.1:8002/          四步向导页
    http://127.0.0.1:8002/health    存活探针

⚠ 8001 不从这里启动（2026-10-16）。内测环境 8001 由冻结快照提供：
      uv run uvicorn m1_mock.app:app --port 8001 --app-dir prototype
  原因：本包是 M2 的迭代区，M2 第一天就会改到这里；冻结一份出去，
  8001 便与 M2 的迭代完全解耦，测试者手上的链接不会断。

路径约定（两个宿主必须完全一致，前端才只有一份）：
    页面  /wizard（8000）或 /（独立调试服务）
    资源  /static/wizard/wizard.{css,js}
    接口  /api/wizard/*
  8000 上 `/static/wizard` 与既有 `/static` 是两个挂载点，注册顺序有讲究，
  见 api/wizard.py 的说明。
"""
import logging
import os
import re
import threading
import time
import uuid
from copy import deepcopy

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag_demo import auth

# 复用现有切分逻辑（无 torch / 无数据库副作用），保证「预估分块数」与真实入库口径一致
from rag_demo.splitter import split_wiki_documents

from rag_demo.mvp import uploads
from rag_demo.mvp.mock_data import (
    BUILD_STEPS,
    EXAMPLE_DOC_TEMPLATE,
    EXAMPLE_TEMPLATES,
    FIELD_DEFS,
    match_column,
)

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ================= 示例数据 =================
# 「用示例数据填满」不再返回一份只有元数据的假清单（M1 那样：文件名与列名是编的，
# 服务端根本没收到文件），而是把**仓库自带的真实数据**复制进上传目录，走与真人上传
# 完全相同的那条路。理由：示例的意义是「不准备文件也能先走一遍真流程」，
# 用假清单走完，到 M4 拿真 CSV 测时才暴露「列名对不上、编码读不出」——那等于没测。
#
# 只取 6 个平台文件的 CSV：`ecommerce_data.csv` 是合并表、在
# ingest_data.NON_PLATFORM_SOURCES 里，放进示例会让用户一上来就看到一条
# 「非平台来源」说明——那是我们在解释自己的数据问题，不是他的问题。
SAMPLE_CSV_NAMES = ("天猫.csv", "淘宝.csv", "京东.csv", "拼多多.csv", "苏宁易购.csv", "1688.csv")
SAMPLE_CSV_DIR = os.path.join(uploads.BASE_DIR, "data", "dianshuang")
SAMPLE_DOC_DIR = os.path.join(uploads.BASE_DIR, "data", "docs")


def _read_sample_files() -> list[tuple[str, bytes]]:
    """读仓库自带的示例数据；文件不在本机就抛 500（这是环境问题，不是用户操作问题）"""
    items: list[tuple[str, bytes]] = []
    for name in SAMPLE_CSV_NAMES:
        path = os.path.join(SAMPLE_CSV_DIR, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                items.append((name, f.read()))
    if os.path.isdir(SAMPLE_DOC_DIR):
        for name in sorted(os.listdir(SAMPLE_DOC_DIR)):
            path = os.path.join(SAMPLE_DOC_DIR, name)
            if os.path.isfile(path) and uploads.kind_of(name) == "md":
                with open(path, "rb") as f:
                    items.append((name, f.read()))
    if not items:
        raise HTTPException(
            status_code=500,
            detail="本机找不到仓库自带的示例数据（data/dianshuang、data/docs），请改用真实文件上传。",
        )
    return items

# 接口前缀只在这里写一次：8000 与独立调试服务共用同一个 router，
# 前端因此只需要认一套路径（见模块 docstring 的路径约定）。
router = APIRouter(prefix="/api/wizard", tags=["wizard"])


# ================= 登录态与企业数据（M3） =================
# 8002 的独立调试服务没有登录态：`auth.current_account()` 为 None 时保持 M2 行为
# （数据集由请求参数决定）。正式服务（8000）上数据集**由账号推导**——
# 前端传什么都不会被采纳，否则「切到别人的库」只是一个请求体字段的距离。
def _account() -> dict | None:
    return auth.current_account()


def _scope_dataset(requested: str) -> str:
    """登录态下：企业账号 → 本企业库；系统管理员 → 调试库；未登录沿用请求值"""
    acct = _account()
    if not acct:
        return requested
    from rag_demo import config

    if acct.get("is_system_admin"):
        return config.ADMIN_DEBUG_DATASET
    dataset = acct.get("dataset")
    if not dataset:
        raise HTTPException(status_code=403, detail="该账号还没有可用数据空间，请联系管理员")
    return dataset


def _require_writer() -> dict | None:
    """
    能改动本企业数据的人：系统管理员或企业管理员

    员工可以提问、可以看自己企业的知识库，但**不能导入 / 重建**：一次构建会
    先清空再重写整个企业库，普通分析师点一下就把全公司的画像重建了。
    独立调试服务（无登录态）保持 M2 行为，不做限制。
    """
    acct = _account()
    if acct is None:
        return None
    if acct.get("is_system_admin") or acct.get("is_enterprise_admin"):
        return acct
    raise HTTPException(
        status_code=403,
        detail="只有企业管理员可以导入或重建数据，请联系本企业管理员",
    )


def _require_upload(upload_id: str) -> dict | None:
    """
    上传批次归属校验：同企业的人可用、系统管理员可用，其余一律 403

    批次号是 12 位随机串，但"猜不到"不能当权限用——同一个企业内也应该
    按批次归属判，而不是"只要知道 id 就能构建"。
    """
    acct = _account()
    if acct is None:
        return None
    if not auth.can_access_upload(acct, upload_id):
        raise HTTPException(status_code=403, detail="无权访问该上传批次")
    return acct

app = FastAPI(title="MVP 向导（独立调试服务）", version="0.2.0")
app.mount("/static/wizard", StaticFiles(directory=STATIC_DIR), name="wizard-static")


# ================= 会话态 =================
# 上传内容已经落盘（uploads.py），磁盘是**数据的真源**；这里只剩两类「流程中间态」：
#   _CONFIRMED_FIELDS：用户在字段确认页选定的列映射（跑完这次构建就没用了）
#   _BUILD_TASKS     ：构建任务的进度快照（前端轮询用）
# 它们仍是进程内字典：丢了的代价是「重新选一次列 / 进度条从头显示」，
# 而不是「上传的数据没了」。M2 接真实构建任务时会随任务表落库。
_STATE_LOCK = threading.Lock()
_CONFIRMED_FIELDS: dict[str, dict] = {}
_BUILD_TASKS: dict[str, dict] = {}
_BUILD_LOCK = threading.Lock()


# ================= 文档结构统计 =================
_HEADING_RE = re.compile(r"^(#{1,3})\s+\S")


def _heading_stats(text: str) -> dict:
    """
    统计 Markdown 标题层级数量（只数 h1/h2/h3，与切分器的 headers_to_split_on 一致）

    只数到 h3 是**对齐切分器口径**：更深的标题不会被切成独立块，
    在结构校验里数出来只会让人误以为「结构很完整」。
    """
    stats = {"h1": 0, "h2": 0, "h3": 0}
    for line in (text or "").splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            stats[f"h{len(m.group(1))}"] += 1
    return stats


def _estimate_chunks(text: str, name: str) -> int:
    """
    预估分块数：直接调真实切分器，而不是拍脑袋估

    mock 里最容易骗自己的就是「用假的数字演示一个真流程」——
    等 M2 接上真切分，预估和实际的落差会变成一堆假 bug。
    这里多花几毫秒换一个可信数字。
    """
    if not (text or "").strip():
        return 0
    try:
        return len(split_wiki_documents(text, name))
    except Exception as e:  # noqa: BLE001 切分失败不该让整个分析接口挂掉
        logger.warning("预估分块数失败（%s）: %s: %s", name, type(e).__name__, e)
        return 0


def _analyze_docs(md_paths: list[str]) -> tuple[list[dict], list[str]]:
    """
    逐篇 .md 统计标题结构与预估分块数，产出文档级警告

    正文从**落盘文件**读（M2）：M1 是前端把整篇正文塞进 JSON 发过来，
    既让服务端看不见真文件，也让大文档白白走一遍序列化。
    """
    results: list[dict] = []
    warnings: list[str] = []

    for path in md_paths:
        name = os.path.basename(path)
        try:
            text = uploads.read_text(path)
        except OSError as e:  # 落盘后被外部删掉/占用，不该让整个分析接口挂掉
            logger.warning("读取文档失败（%s）: %s", path, e)
            warnings.append(f"《{name}》读取失败，已跳过。")
            continue
        size = len(text.encode("utf-8"))
        stats = _heading_stats(text)
        chunks = _estimate_chunks(text, name)
        total_headings = stats["h1"] + stats["h2"] + stats["h3"]

        warn = None
        if total_headings == 0:
            warn = "未检测到 Markdown 标题，这篇文档会被整体切分，检索定位精度可能下降"
            warnings.append(f"《{name}》{warn}")
        elif stats["h1"] == 0:
            warn = "没有一级标题（#），文档结构可能不完整"
            warnings.append(f"《{name}》：{warn}")

        results.append({
            "name": name,
            "size": size,
            "chars": len(text),
            "h1": stats["h1"],
            "h2": stats["h2"],
            "h3": stats["h3"],
            "total_headings": total_headings,
            "est_chunks": chunks,
            "warning": warn,
        })

    return results, warnings


# ================= 字段识别 =================
def _analyze_fields(csv_files: list[dict]) -> tuple[list[dict], list[str]]:
    """
    字段识别：同义词字典匹配（不做 LLM 识别，见 MVP 文档 5.2）

    多文件时的取舍：**先到先得**。
    同一字段若在多个 CSV 里都有对应列，取第一个命中的文件——
    因为 M1 的数据口径是「多份订单表合并」，列在哪个文件不影响识别结果。
    真要做冲突提示，属于 M2 的事（那时才知道用户想以哪份为准）。
    """
    warnings: list[str] = []
    all_columns: list[str] = []
    # 列 → 命中的字段 key / 来源文件。**每个列都要试一遍**，不能只记每个字段的首次命中：
    # 否则第二份 CSV 里同样能认出的 user_id / city 会被当成「没识别的列」报出来，
    # 那是一条假警告，比没有警告更伤人。
    column_hit: dict[str, str] = {}
    column_file: dict[str, str] = {}

    for f in csv_files:
        for col in f.get("columns") or []:
            if col not in all_columns:
                all_columns.append(col)
                column_file[col] = f.get("name") or ""
            if col not in column_hit:
                key = match_column(col)
                if key:
                    column_hit[col] = key

    fields: list[dict] = []
    for spec in FIELD_DEFS:
        hit_column = next((c for c in all_columns if column_hit.get(c) == spec["key"]), None)
        fields.append({
            "key": spec["key"],
            "label": spec["label"],
            "required": spec["required"],
            "hint": spec["hint"],
            "detected": bool(hit_column),
            # 识别到的直接给一个默认选中值；没识别到的留空，等用户手选
            "column": hit_column,
            "from_file": column_file.get(hit_column) if hit_column else None,
            "options": all_columns,
        })

    # 没被任何字段认走的列，提示一下但**不报错**：
    # 多余的列不影响构建（画像聚合只用识别到的字段），说清楚比沉默好。
    matched_columns = set(column_hit)
    unmatched = [c for c in all_columns if c not in matched_columns]
    if unmatched:
        warnings.append(
            "以下列没有被识别为任何字段，构建时会忽略它们："
            + "、".join(unmatched[:8])
            + ("…" if len(unmatched) > 8 else "")
        )

    # 没有 CSV 时**不能**报这条：没有任何列可选，让用户「手动指定」是一句无解的话
    # （他会对着一个空下拉框找「用户ID」）。只传文档时必然命中这种情况——
    # 一条假警告比没有警告更伤人（本函数开头的取舍同理）。
    missed = (
        [f["label"] for f in fields if not f["detected"] and f["required"]]
        if all_columns else []
    )
    if missed:
        warnings.append("关键字段未识别到，建议手动指定：" + "、".join(missed))

    # 金额列决定消费类结论；等级列决定等级是否可用。
    # 第五轮起系统**不再从金额推导等级**（客户底线），所以两条警告各说各的：
    has_amount_col = any(f["key"] == "amount" and f["detected"] for f in fields)
    has_level_col = any(f["key"] == "member_level" and f["detected"] for f in fields)
    if all_columns and not has_amount_col:
        warnings.append("没有识别到「订单金额」：客单价、消费类结论会缺失。")
    if all_columns and not has_level_col:
        warnings.append(
            "没有识别到「会员等级」：该字段将记为未知，系统不会按金额或其他字段推算"
            "（需要等级请在字段确认页选择你数据里的等级列）。"
        )

    return fields, warnings


# ================= 请求模型 =================
# 注意入参里**没有文件内容**：文件走 multipart 上传落到磁盘，接口之间只传
# upload_id（见 uploads.py）。M1 那种「把正文塞进 JSON 一路带着走」的模型已删——
# 它让每个接口都变成「数据搬运工」，也让服务端无法成为数据的真源。
class BuildRequest(BaseModel):
    upload_id: str
    fields: dict[str, str | None] = Field(default_factory=dict)
    # 目标数据集：只接受 builder.BUILDABLE_DATASETS 里的名字（user / test）。
    # 默认 user —— 运营上传的数据进用户库；test 是首跑试验库。demo 不在白名单内。
    dataset: str = "user"
    # 构建模式（第五轮）：
    #   incremental 追加更新（默认）—— 只处理新上传的文件，只更新受影响的用户/文档
    #   full        覆盖重建 —— 清空现有数据后全量重算（M2 的旧行为）
    # 登录态下 dataset 仍由账号推导（红线）；mode 是「怎么算」不是「写哪个库」。
    mode: str = "incremental"
    # 演示用：勾选后在「生成画像向量」这一步故意失败，
    # 用来验证「失败有可读中文提示 + 可重试」这条验收项。
    simulate_failure: bool = False


class RemoveFileRequest(BaseModel):
    upload_id: str
    name: str


class QueryRequest(BaseModel):
    question: str
    # 查询要知道这批上传里有哪些规则文档（答案的引用来源），
    # 但不该由前端把文档清单再报一遍——那是可以伪造的重复信息
    upload_id: str | None = None
    # 查哪个数据集的数据（与构建同一个白名单）：决定「构建期间谢绝查询」这条规则
    # 该对谁生效——构建 user 不该挡住查 demo 的人。
    # 前端会带上**最近一次构建实际写入的那个库**（第 3 步的响应里就有），
    # 否则「构建到 test、查询默认 user」会查到另一个库上，答案对不上数据。
    dataset: str = "user"


# ================= 页面 =================
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """四步向导页"""
    return FileResponse(os.path.join(STATIC_DIR, "wizard.html"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mvp-wizard", "build_tasks": len(_BUILD_TASKS)}


# ================= 1. 上传 =================
def _file_state_map(upload_id: str) -> tuple[dict, dict]:
    """
    上传批次里每个文件的 sha256 与「是否已入库」状态（第 1/2 步展示用）

    返回 ({csv 文件名: {"sha256","state"}}, {md 文件名: {...}})；
    任何一步失败（库还没建 / 清单不可读 / 文件被删）都返回空映射**而不是报错**：
    文件状态只是展示信息，不能让它把上传页打成 500。
    """
    empty: tuple[dict, dict] = ({}, {})
    try:
        from rag_demo.mvp import uploads
        from rag_demo.mvp.builder import load_incremental_baseline

        # 和构建同一个口径：登录态下数据集由账号推导（系统管理员→调试库，企业→本企业库）
        dataset = _scope_dataset("user")
        csv_paths, md_paths = uploads.paths(upload_id)
        baseline = load_incremental_baseline(dataset)
        manifest = baseline["manifest"] if baseline["available"] else None
        csv_entries = [uploads.file_entry(p) for p in csv_paths]
        md_entries = [uploads.file_entry(p) for p in md_paths]
        classified = uploads.classify_files(csv_entries, md_entries, manifest)
        return (
            {
                e["name"]: {"sha256": e["sha256"], "state": e["state"]}
                for e in classified["csv_files"]
            },
            {
                e["name"]: {"sha256": e["sha256"], "state": e["state"]}
                for e in classified["md_files"]
            },
        )
    except Exception as e:  # noqa: BLE001 状态不可用就降级，不阻断上传页
        logger.info("上传批次文件状态不可用（%s）: %s", upload_id, e)
        return empty


def _state_payload(upload_id: str) -> dict:
    """
    该上传批次的完整状态：文件清单 + 字段识别 + 文档结构

    上传、删文件、示例填满、刷新页面恢复状态——四个场景返回**同一个结构**，
    前端因此只写一个渲染函数，不必区分「刚上传」和「恢复到一半」。

    第五轮起每个文件补 `sha256` 与 `state`（new / ingested / changed，判断不了为 null）：
    用户在第 1/2 步就能看到「这个文件已经入库了/是新文件」，而不是到第 3 步才发现。
    """
    csv_files = []
    md_paths = []
    try:
        scanned = uploads.scan(upload_id)
        csv_files = scanned["csv_files"]
        md_paths = uploads.paths(upload_id)[1]
    except uploads.UploadError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    state_csv, state_md = _file_state_map(upload_id)
    for item in csv_files:
        extra = state_csv.get(item["name"]) or {}
        item["sha256"] = extra.get("sha256")
        item["state"] = extra.get("state")

    fields, field_warnings = _analyze_fields(csv_files)
    docs, doc_warnings = _analyze_docs(md_paths)

    md_files = []
    for d in docs:
        extra = state_md.get(d["name"]) or {}
        md_files.append(
            {
                "name": d["name"],
                "size": d["size"],
                "chars": d["chars"],
                "sha256": extra.get("sha256"),
                "state": extra.get("state"),
            }
        )

    return {
        "upload_id": upload_id,
        "csv_files": csv_files,
        # md 只回元信息（名字/大小/字符数），正文留在服务端——前端渲染文件列表用不到
        # 正文，而它可能有几万字，来回搬运只会让响应变大、还多一份可以不一致的副本
        "md_files": md_files,
        "fields": fields,
        "docs": docs,
        "warnings": field_warnings + doc_warnings,
        "summary": {
            "csv_count": len(csv_files),
            "md_count": len(md_paths),
            # 这里是**服务端真读出来的行数**（M1 是前端按换行数估的，只能写「约」）
            "total_rows": sum(f["row_count"] for f in csv_files),
            "total_chunks": sum(d["est_chunks"] for d in docs),
            "detected_fields": sum(1 for f in fields if f["detected"]),
            "total_fields": len(fields),
        },
    }


def _empty_state(upload_id: str) -> dict:
    """批次里一个文件都不剩时的状态（删完最后一个文件后前端仍要能渲染）"""
    return {
        "upload_id": upload_id, "csv_files": [], "md_files": [],
        "fields": [], "docs": [], "warnings": [],
        "summary": {"csv_count": 0, "md_count": 0, "total_rows": 0,
                    "total_chunks": 0, "detected_fields": 0, "total_fields": 0},
    }


@router.post("/upload")
async def upload(
    files: list[UploadFile] = File(default=[]),
    upload_id: str = Form(default=""),
) -> dict:
    """
    上传文件（multipart）：落盘转 UTF-8 → 解析 → 返回批次状态

    不传 upload_id 就是新批次；传了就是往同一批里追加（前端按「一次选择」一批，
    所以不存在「必须先建批次」的时序问题）。

    解析失败的文件**只跳过并说明原因**，不让整次上传失败：用户拖进来 6 个文件，
    其中一个编码坏了，不该导致另外 5 个也白传。
    """
    _require_writer()
    if not files:
        raise HTTPException(status_code=400, detail="还没有选择任何文件。")

    payload: list[tuple[str, bytes]] = []
    for f in files:
        payload.append((f.filename or "未命名", await f.read()))

    try:
        uid, rejected = uploads.save(upload_id or None, payload)
    except uploads.UploadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 记住这批数据属于谁：构建/查询/读取状态都要按它校验
    acct = _account()
    if acct:
        auth.bind_upload(uid, acct)

    state = _state_payload(uid)
    state["rejected"] = rejected
    if rejected and not (state["csv_files"] or state["md_files"]):
        # 一个都没成功：这不该表现为「上传好了但列表是空的」
        raise HTTPException(status_code=400, detail="；".join(rejected))
    logger.info("[上传] 批次 %s：CSV %d 个 / 文档 %d 篇（拒绝 %d 个）",
                uid, state["summary"]["csv_count"], state["summary"]["md_count"], len(rejected))
    return state


@router.post("/upload/remove")
def remove_file(req: RemoveFileRequest) -> dict:
    """从批次里移除一个文件（服务端删盘上的那份，前端不用重传剩下的）"""
    _require_writer()
    _require_upload(req.upload_id)
    try:
        uploads.remove(req.upload_id, req.name)
        csv_paths, md_paths = uploads.paths(req.upload_id)
    except uploads.UploadError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 删光了就连批次一起消失（uploads.remove 已经清了目录），返回空状态让前端能继续渲染
    if not csv_paths and not md_paths:
        auth.unbind_upload(req.upload_id)
        return _empty_state(req.upload_id)
    return _state_payload(req.upload_id)


@router.get("/upload/{upload_id}")
def upload_state(upload_id: str) -> dict:
    """取批次当前状态（页面刷新后恢复用）"""
    _require_upload(upload_id)
    return _state_payload(upload_id)


@router.get("/sample")
def sample() -> dict:
    """用仓库自带的真实数据填满（走与真人上传完全相同的那条落盘/解析路径）"""
    _require_writer()
    uid, rejected = uploads.save(None, _read_sample_files())
    acct = _account()
    if acct:
        auth.bind_upload(uid, acct)
    state = _state_payload(uid)
    state["rejected"] = rejected
    logger.info("[上传] 示例数据已填满：批次 %s", uid)
    return state


# ================= 2. 一键构建 =================
def _build_step_state() -> list[dict]:
    return [
        {"key": s["key"], "label": s["label"], "unit": s["unit"],
         "status": "pending", "percent": 0, "processed": 0, "total": 0}
        for s in BUILD_STEPS
    ]


_STEP_INDEX = {s["key"]: i for i, s in enumerate(BUILD_STEPS)}


def _recalc_percent(task: dict) -> int:
    """
    按步骤权重折算总进度

    跳过的步骤按完成算：本次没上传 CSV 时，清洗/聚合/向量化三步永远不会执行，
    若按 0% 算，进度条在最末尾会卡在 78% 而任务已经 done——那种「完成了但没到 100%」
    比不准更让人怀疑。
    上限压到 99：真正的 100% 只由「任务状态变 done」给出，
    否则最后一步刚跑完 99% 与「索引还没重建」会看起来一样。
    """
    total = 0.0
    for spec, st in zip(BUILD_STEPS, task["steps"]):
        if st["status"] in ("done", "skipped"):
            frac = 1.0
        elif st["status"] == "running":
            frac = (st["processed"] / st["total"]) if st["total"] else 0.0
        else:
            frac = 0.0
        total += spec["weight"] * frac
    return min(99, int(total))


def _apply_event(task: dict, event: dict) -> None:
    """
    把构建线程的事件翻译成任务状态

    这一层存在的意义：前端只认一份结构（steps/percent/note），而构建线程只知道
    「哪个阶段跑完了、多少条」。翻译只在这里做一次，前端与 ingest 层因此互不知道对方。
    """
    kind, key = event.get("kind"), event.get("step")
    if kind == "note":
        with _BUILD_LOCK:
            task["note"] = event["text"]
        return

    i = _STEP_INDEX.get(key)
    if i is None:
        return

    with _BUILD_LOCK:
        st = task["steps"][i]
        if kind == "step_start":
            task["step_index"] = i
            st["status"] = "running"
            if event.get("total"):
                st["total"] = event["total"]
            task["note"] = f"{st['label']}…"
        elif kind == "step_progress":
            st["status"] = "running"
            if event.get("total") is not None:
                st["total"] = event["total"]
            if event.get("processed") is not None:
                st["processed"] = event["processed"]
            st["percent"] = round(100 * st["processed"] / st["total"]) if st["total"] else 0
        elif kind == "step_done":
            if event.get("total") is not None:
                st["total"] = event["total"]
            st["processed"] = st["total"]
            st["percent"] = 100
            st["status"] = "done"
            task["note"] = (f"{st['label']}：完成（{st['processed']:,} {st['unit']}）"
                            if st["total"] else f"{st['label']}：完成")
        elif kind == "step_skip":
            st["status"] = "skipped"
            st["percent"] = 100
            task["note"] = event.get("text") or f"{st['label']}：已跳过"

        task["percent"] = _recalc_percent(task)
        running = next((s for s in task["steps"] if s["status"] == "running"), None)
        task["processed"] = running["processed"] if running else 0
        task["total"] = running["total"] if running else 0


def _run_build(task_id: str, req: BuildRequest, csv_paths: list[str], md_paths: list[str]) -> None:
    """
    真实构建线程：写作用域、数据集锁、ingest 编排全在 builder.run_build 里

    这里只做三件事：转发事件、把异常翻译成人话、把没跑到的步骤收尾成「跳过」。
    builder.run_build 的模块 docstring 里有完整说明（含「失败会留下部分数据」这条）。
    """
    from rag_demo.mvp.builder import BuildInputs, run_build

    task = _BUILD_TASKS[task_id]
    try:
        inputs = BuildInputs(
            dataset=req.dataset,
            csv_paths=csv_paths,
            md_paths=md_paths,
            fields=req.fields,
            simulate_failure=req.simulate_failure,
            # 把批次号带进构建线程：成功后落盘 meta.last_build，
            # 概况页拿它 + fields 就能一键重建（企业库清空后尤其重要）
            upload_id=req.upload_id,
            # 第五轮：incremental=只处理新增文件；full=覆盖重建
            mode=req.mode,
        )
        result = run_build(inputs, lambda ev: _apply_event(task, ev))
    except Exception as e:  # noqa: BLE001 构建失败必须变成任务状态，而不是打死线程
        logger.exception("构建任务 %s 失败", task_id)
        with _BUILD_LOCK:
            task["status"] = "failed"
            failed = next((s for s in task["steps"] if s["status"] == "running"), None)
            if failed:
                failed["status"] = "failed"
                failed["note"] = str(e)
            task["error"] = str(e)
            if req.mode == "incremental":
                # 增量是分批 commit 的：失败时可能已合并了一部分用户，
                # 重试同一批会再累加一次（订单数翻倍，且不报错）——必须说清楚。
                task["note"] = (
                    "增量构建失败。注意：合并是边写边提交的，失败时**可能已有部分用户被合并**；"
                    "重试同一批会把这些用户再累加一次。请改用「覆盖重建」恢复后再继续追加。"
                )
            else:
                task["note"] = (
                    "构建失败。注意：画像/文档是**边写边提交**的，失败时库里可能是部分数据；"
                    "重试会先清空再重写，所以直接重试即可。检索索引是最后一步，本次没重建，"
                    "查询仍会看到上一版结果。"
                )
    else:
        with _BUILD_LOCK:
            for st in task["steps"]:
                if st["status"] == "pending":
                    st["status"] = "skipped"   # 兜底：没参与本次构建的步骤不该停在待处理
            task["status"] = "done"
            task["percent"] = 100
            task["step_index"] = len(BUILD_STEPS)
            idx = result.get("index_total", 0)
            tail = (
                f"索引 {idx:,} 条，用时 {result.get('elapsed_s')}s，"
                f"数据状态 {result.get('freshness')}。可以开始提问了"
            )
            if result.get("mode") == "incremental":
                # 增量模式的「画像 X 个」是本次受影响用户数，不是总用户数——
                # 说成「画像 X 个」会让用户以为数据只剩这么点（10 万变几百）
                docs_changed = int(result.get("docs_new", 0)) + int(result.get("docs_updated", 0))
                task["note"] = (
                    f"增量构建完成：更新/新增 {result.get('profiles', 0):,} 个用户、"
                    f"{docs_changed} 篇文档，其余数据未改动。{tail}"
                )
            elif result.get("profiles") is None:
                task["note"] = f"构建完成：本次只更新了文档（未重建画像，上一批画像保持不变），{tail}"
            else:
                task["note"] = (
                    f"构建完成：画像 {result['profiles']:,} 个用户"
                    f"（来自 {result.get('rows', 0):,} 行交易），{tail}"
                )
            task["result"] = result


# ================= 第 3 步：构建计划（增量判定，只读） =================
def _dataset_plan_files(upload_id: str, dataset: str) -> tuple[dict, dict]:
    """
    当前批次的「文件清单 + 清单判定 + 增量基线」（plan 与 build 预检共用，只读）

    返回 (classified, baseline)。异常原样上抛，由调用方翻译成 HTTP 语义：
    上传内容不在 → 404；库/清单不可读不会抛（load_incremental_baseline 内部降级）。
    """
    from rag_demo.mvp import uploads
    from rag_demo.mvp.builder import load_incremental_baseline

    csv_paths, md_paths = uploads.paths(upload_id)
    baseline = load_incremental_baseline(dataset)
    manifest = baseline["manifest"] if baseline["available"] else None
    csv_entries = [uploads.file_entry(p) for p in csv_paths]
    md_entries = [uploads.file_entry(p) for p in md_paths]
    classified = uploads.classify_files(csv_entries, md_entries, manifest)
    return classified, baseline


def _incremental_precheck(upload_id: str, dataset: str) -> dict:
    """
    增量构建前的只读预检：明确做到「不建任务就给出人话错误」

    三道闸（与 builder._build_incremental 的判定同一套规则，这里只是提前拦）：
        1. 没有基线（旧库/空库）→ 400，文案说明「先覆盖重建」
        2. 没有新增/变更文件 → 400 契约原文
    返回值是 classify_files 的结果（build 用它算进度初始总量）。
    """
    from rag_demo.mvp import uploads

    try:
        classified, baseline = _dataset_plan_files(upload_id, dataset)
    except uploads.UploadError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    existing = baseline["existing"]
    if not baseline["available"]:
        if existing["profiles"] or existing["chunks"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    "该数据空间由旧版本构建，无法判断哪些文件已入库；"
                    "请先做一次「覆盖重建」以启用增量更新"
                ),
            )
        raise HTTPException(
            status_code=400,
            detail="当前数据空间还没有构建过（或数据已清空），无法增量更新；请选择「覆盖重建」",
        )
    if not classified["new_csv"] and not classified["new_md"] and not classified["changed_md"]:
        detail = "本批次没有新增文件可追加；要重算全部数据请选「覆盖重建」"
        skipped = classified["skipped_changed_csv"]
        if skipped:
            detail += (
                "（同名 CSV 内容有变化已跳过："
                + "、".join(skipped[:3])
                + ("…" if len(skipped) > 3 else "")
                + "；请改名后再上传）"
            )
        raise HTTPException(status_code=400, detail=detail)
    return classified


def _public_file_entries(entries: list[dict]) -> list[dict]:
    """文件条目出网：去掉内部 mtime，只留 name/size/sha256/state"""
    return [
        {
            "name": e["name"],
            "size": e.get("size"),
            "sha256": e.get("sha256"),
            "state": e.get("state"),
        }
        for e in entries
    ]


@router.get("/plan")
def build_plan(upload_id: str = "", dataset: str = "user") -> dict:
    """
    第 3 步的构建计划（**只读**）：告诉前端「增量能处理什么、已有数据多大」

    响应（契约 B）：
        dataset / mode_default / csv_files[{name,size,sha256,state}] /
        md_files[...] / new_csv_count / new_md_count / changed_md_count /
        skipped_changed_csv / existing{profiles,docs,chunks,built_at,last_mode,
        last_elapsed_s,last_rows,last_full_elapsed_s} /
        manifest{available,seeded_from} / can_incremental / incremental_block_reason / hint

    `dataset` 只在 8002 独立调试服务（无登录态）下生效；8000 由账号推导。
    """
    from rag_demo.mvp import uploads
    from rag_demo.mvp.builder import resolve_dataset

    if not upload_id:
        raise HTTPException(status_code=400, detail="缺少 upload_id：请先在第一步上传文件。")
    _require_upload(upload_id)

    try:
        target = resolve_dataset(_scope_dataset(dataset), action="构建")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        scanned = uploads.scan(upload_id)
        classified, baseline = _dataset_plan_files(upload_id, target)
    except uploads.UploadError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    existing = baseline["existing"]
    manifest_available = bool(baseline["available"])
    if manifest_available:
        can_incremental = True
        block_reason = None
    elif existing["profiles"] or existing["chunks"]:
        can_incremental = False
        block_reason = (
            "该数据空间由旧版本构建，无法判断哪些文件已入库；"
            "请先做一次「覆盖重建」以启用增量更新"
        )
    else:
        can_incremental = False
        block_reason = "当前数据空间还没有构建过（或数据已清空），第一次构建请选择「覆盖重建」"

    rows_by_name = {f["name"]: int(f.get("row_count") or 0) for f in scanned["csv_files"]}
    new_csv_rows = sum(rows_by_name.get(e["name"], 0) for e in classified["new_csv"])
    new_md_count = len(classified["new_md"])
    changed_md_count = len(classified["changed_md"])
    hint = uploads.plan_hint(
        len(classified["new_csv"]),
        new_csv_rows,
        new_md_count,
        changed_md_count,
        existing["profiles"],
        classified["skipped_changed_csv"],
    )

    return {
        "dataset": target,
        "mode_default": "incremental" if can_incremental else "full",
        "csv_files": _public_file_entries(classified["csv_files"]),
        "md_files": _public_file_entries(classified["md_files"]),
        "new_csv_count": len(classified["new_csv"]),
        "new_md_count": new_md_count,
        "changed_md_count": changed_md_count,
        "skipped_changed_csv": classified["skipped_changed_csv"],
        "existing": {
            "profiles": existing["profiles"],
            "docs": existing["docs"],
            "chunks": existing["chunks"],
            "built_at": existing["built_at"],
            "last_mode": existing["last_mode"],
            "last_elapsed_s": existing["last_elapsed_s"],
            "last_rows": existing["last_rows"],
            "last_full_elapsed_s": existing["last_full_elapsed_s"],
        },
        "manifest": {
            "available": manifest_available,
            "seeded_from": baseline["seeded_from"],
        },
        "can_incremental": can_incremental,
        "incremental_block_reason": block_reason,
        "hint": hint,
    }


@router.post("/build")
def build(req: BuildRequest) -> dict:
    """
    启动**真实构建**任务，返回 task_id；前端随后轮询 /build/{id}

    第五轮起有**两种模式**（BuildRequest.mode）：
        incremental（默认）追加更新：只处理新增文件、只更新受影响数据；
                   进线程前先做只读预检（无基线/无新增文件直接 400，不建任务）
        full        覆盖重建：清空后全量重算（旧行为）

    共同的前置检查：
      1. 目标数据集必须在白名单内（demo 永远不在）——防「写错库」；
      2. 该数据集当前没有构建在跑——同一时刻两路写会被锁挡住，与其让用户
         看着进度条不动，不如立刻说清楚。
    """
    from rag_demo.db.connection import dataset_lock
    from rag_demo.mvp.builder import resolve_dataset

    _require_writer()
    _require_upload(req.upload_id)

    # 构建模式校验（契约 B）：只认 incremental / full，其它一律 400
    mode = (req.mode or "").strip().lower()
    if mode not in ("incremental", "full"):
        raise HTTPException(status_code=400, detail="构建模式只能是 incremental 或 full")
    req.mode = mode

    # 登录态下数据集由账号推导（企业库 / 管理员调试库），前端传的 dataset 不采纳
    req.dataset = _scope_dataset(req.dataset)
    try:
        dataset = resolve_dataset(req.dataset)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    req.dataset = dataset

    # 企业库在**第一次构建**时才真正 CREATE DATABASE（见 db/provision.py）：
    # 审核通过只是登记数据集名，建库这种重操作不该挂在一次点击上。
    from rag_demo.config import ENTERPRISE_DATASET_PREFIX
    if dataset.startswith(ENTERPRISE_DATASET_PREFIX):
        from rag_demo.db.provision import ensure_dataset_ready
        try:
            ensure_dataset_ready(dataset)
        except Exception as e:  # noqa: BLE001 建库失败要说人话，而不是 500 裸栈
            logger.exception("企业库准备失败: %s", dataset)
            raise HTTPException(
                status_code=500, detail=f"数据空间准备失败：{e}"
            ) from e

    try:
        csv_paths, md_paths = uploads.paths(req.upload_id)
    except uploads.UploadError as e:
        # 上传内容没了（清过盘 / 批次号是编的）：明确让用户回第 1 步，
        # 而不是给一个「构建成功但查不到东西」的空任务
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not csv_paths and not md_paths:
        raise HTTPException(status_code=400, detail="没有可构建的数据，请回到第 1 步上传文件。")

    # 增量模式先做只读预检：没有基线 / 没有新增文件在这里就 400，
    # 不要把「注定失败」的任务丢进后台线程让用户等一轮轮询。
    classified: dict | None = None
    if mode == "incremental":
        classified = _incremental_precheck(req.upload_id, dataset)

    # 必填但没映射的字段：**只警告不拦截**——MVP 明确要求「允许跳过不重要字段」，
    # 用户的判断优先于我们去替他决定。真正拦下来只会让人卡在这一步。
    # 唯一硬性的是 user_id：没有它就没有「一个用户」这个聚合单位（ingest 会自己报错）。
    #
    # ⚠ 这道检查只在**本次真的要合并新 CSV** 时才做。没有 CSV 就没有任何列可选，
    #   此时要求 user_id 是一道无解的关卡（第 2 步的下拉框是空的）；
    #   增量模式下只追加了文档时同理，画像合并不发生，不需要 user_id。
    new_csv_exists = bool(csv_paths) if classified is None else bool(classified["new_csv"])
    if new_csv_exists:
        missing = [
            spec["label"] for spec in FIELD_DEFS
            if spec["required"] and not req.fields.get(spec["key"])
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"「{missing[0]}」还没选对应的列。没有它就无法把订单聚合到人身上，请回到上一步选择。",
            )
    else:
        logger.info("构建任务不含需要合并的 CSV，仅文档更新")

    # 非阻塞试探：拿不到锁说明该数据集有别的活在干（构建，或有人正在提问——
    # 第 4 步起一次问答也整段持锁，它要真读库十几秒）。
    # 这里**只试探不放锁**——RLock 只能由持有它的线程释放，
    # 请求线程替构建线程放锁会直接抛 RuntimeError。真正的持锁发生在构建线程里。
    lock = dataset_lock(dataset)
    if not lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail=(
                f"数据集 {dataset} 正忙：要么有一次构建在进行，"
                f"要么有人正在提问（一次问答要十几秒）。等这次结束再开始新的构建。"
            ),
        )
    lock.release()

    # 起始总量只用**已知的真值**（清洗的行数、文档篇数）：剩下的（用户数/画像数/索引条数）
    # 必须等 ingest 真跑出来才知道，事件到达时再填——不预估、不假装。
    # 清洗与聚合是一次性操作（一次读全部、一次聚合全部），没有可切分的进度，
    # 因此这两步只在完成时跳变，这是它们的真实粒度，不是显示问题。
    scanned = uploads.scan(req.upload_id)
    if mode == "incremental" and classified is not None:
        # 增量：只把**本次要处理的新文件**算进进度总量，已入库文件不参与本轮
        fresh_names = {e["name"] for e in classified["new_csv"]}
        rows = sum(f["row_count"] for f in scanned["csv_files"] if f["name"] in fresh_names)
        md_total = len(classified["new_md"]) + len(classified["changed_md"])
    else:
        rows = sum(f["row_count"] for f in scanned["csv_files"])
        md_total = len(md_paths)

    task_id = uuid.uuid4().hex[:12]
    with _BUILD_LOCK:
        _BUILD_TASKS[task_id] = {
            "task_id": task_id,
            "upload_id": req.upload_id,
            "dataset": dataset,
            "mode": mode,
            "status": "running",
            "percent": 0,
            "step_index": 0,
            "steps": _build_step_state(),
            "processed": 0,
            "total": 0,
            "note": "正在准备…",
            "error": None,
            "started_at": time.time(),
        }
        # 起始总量只用**已知的真值**：清洗几行（落盘时 pandas 读过）
        if rows:
            _BUILD_TASKS[task_id]["steps"][_STEP_INDEX["clean"]]["total"] = rows
        if md_total:
            _BUILD_TASKS[task_id]["steps"][_STEP_INDEX["chunk"]]["total"] = md_total
        # 只保留最近的任务，避免长时间开着进程内存无限涨
        for old in sorted(_BUILD_TASKS, key=lambda k: _BUILD_TASKS[k]["started_at"])[:-5]:
            _BUILD_TASKS.pop(old, None)
        with _STATE_LOCK:
            _CONFIRMED_FIELDS[req.upload_id] = dict(req.fields)

    threading.Thread(target=_run_build, args=(task_id, req, csv_paths, md_paths), daemon=True).start()
    logger.info(
        "构建任务已启动: %s（数据集 %s，模式 %s，批次 %s：CSV %d 个 / 文档 %d 篇，本轮清洗 %d 行）",
        task_id, dataset, mode, req.upload_id, len(csv_paths), len(md_paths), rows,
    )
    return {"task_id": task_id, "dataset": dataset, "mode": mode}


@router.get("/build/active")
def build_active() -> dict:
    """
    当前数据空间下最近一个**还在跑**的构建任务（页面离开后回来恢复进度用）

    没有则返回 {"task": null}。task 结构与 GET /build/{task_id} 完全一致，
    前端因此复用同一套渲染/轮询逻辑。

    ⚠ 必须定义在 `/build/{task_id}` **之前**：Starlette 按注册顺序匹配，
    否则 "active" 会被当成一个 task_id 捕获。
    """
    account = _account()
    try:
        dataset = _scope_dataset("user")
    except HTTPException:
        raise

    candidates: list[dict] = []
    with _BUILD_LOCK:
        for task in _BUILD_TASKS.values():
            if task.get("status") != "running":
                continue
            if task.get("dataset") != dataset:
                continue
            candidates.append(task)
    candidates.sort(key=lambda t: t.get("started_at") or 0, reverse=True)

    for task in candidates:
        # 任务可能属于同一企业的其他人：按 upload 归属再校验一次，
        # 不能因为「同一个库」就能看到别人的构建进度
        if account is None or auth.can_access_upload(account, task.get("upload_id", "")):
            with _BUILD_LOCK:
                return {"task": deepcopy(task)}
    return {"task": None}


@router.get("/build/{task_id}")
def build_progress(task_id: str) -> dict:
    task = _BUILD_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="构建任务不存在或已过期，请回到第 3 步重新点击「开始构建」。")
    # 任务 id 也是可猜的：进度里带着数据集名与条数，仍然按批次归属校验
    _require_upload(task.get("upload_id", ""))
    with _BUILD_LOCK:
        return deepcopy(task)


# ================= 4. 查询（真实问答） =================
@router.post("/query")
def query(req: QueryRequest) -> dict:
    """
    第 4 步：**真实问答**（M2）

    与首页问答（/qa）走**同一条 pipeline**：意图路由 → 多路检索 → 精排 → 生成，
    答案与 sources 都是现成链路产出的，这里不另写一套。

    向导比 /qa 只多做两件事：

    **① 切数据集**。pipeline / 检索 / SQL 里几十处 get_conn() 都不传参数，
    靠 contextvar 决定去哪个库（分库改造为什么这么做，见 db/connection.py）。
    所以「查用户自己刚构建的数据」在这里就是一句 use_dataset —— 切换只在本次
    请求内生效，请求结束就还原（同步端点跑在线程池里，contextvar 跟着请求走）。

    **② 整段问答持锁**。构建期间谢绝查询这条规则从 M1 就在，但当时答案是一段
    内存里的假文本，试探一下就放锁没有代价；现在一次问答要**真读库十几秒**，
    「试探完就放锁」会留下一个十几秒的窗口——这期间有人点「重新构建」，
    两条线程就会共用同一条 psycopg2 连接（它非线程安全），
    报错是在用户点击的瞬间随机炸的「another command is already in progress」。
    而且画像与索引正在被重写时，答出来的东西对应的是「改到一半的数据」，
    说不清是新的还是旧的。锁按数据集分：构建 user 不影响查 demo 的人。

    ⚠ 本接口**不做按角色的裁剪**（permissions.render）：向导是一条独立的业务线，
    操作者是「这批数据的主人」——他手里本来就有 CSV 和 .md 原件，来源片段对他是
    自查凭据而不是越权信息。等向导接入正式登录态时再统一收口。
    """
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入一个问题再提交。")
    if len(question) > 200:
        raise HTTPException(status_code=400, detail="问题太长了（超过 200 字），请精简后再问。")

    from rag_demo.db.connection import (
        dataset_lock,
        reset_dataset,
        use_dataset,
    )
    from rag_demo.mvp.builder import resolve_dataset
    from rag_demo.pipeline import answer_question

    if req.upload_id:
        _require_upload(req.upload_id)
    # 和构建同一个口径：查哪个库由账号决定，前端传值只在未登录（8002）时生效
    try:
        dataset = resolve_dataset(_scope_dataset(req.dataset), action="提问")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    lock = dataset_lock(dataset)
    if not lock.acquire(blocking=False):
        return {
            "answer": (
                "数据集正在重建（画像与检索索引都在重写），构建期间不提供查询。\n"
                "这样避免回答到「改到一半的数据」。等第 3 步的进度到 100% 再问即可。"
            ),
            "sources": [],
            "route": "busy",
            "busy": True,
            "cached": False,
            "dataset": dataset,
            "elapsed_ms": 0,
        }

    started = time.time()
    token = use_dataset(dataset)
    try:
        result = answer_question(question)
    except Exception as e:  # noqa: BLE001 问答失败要给用户一句人话，不能是 500 裸栈
        # 典型触发：这个数据集从来没构建过（检索索引表为空，BM25 语料加载直接抛）。
        # 那是「该做的事没做」，不是系统故障，所以原样说清楚 + 指出下一步。
        logger.exception("向导问答失败（数据集 %s）", dataset)
        return {
            "answer": (
                f"这次没能答出来：{e}\n\n"
                "如果这个数据集还没构建过（或上次构建失败），请回到第 3 步重新构建一次。"
            ),
            "sources": [],
            "route": "error",
            "busy": False,
            "cached": False,
            "dataset": dataset,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    finally:
        reset_dataset(token)
        lock.release()

    return {
        "answer": result.get("answer", ""),
        # sources 直接用生成层的产出（编号 + 来源名 + 片段），
        # 正文里的 [来源N] 与它的下标一一对应，前端据此做「点引用跳出处」
        "sources": result.get("sources", []),
        "route": result.get("route"),
        "busy": False,
        "cached": bool(result.get("cached")),
        "dataset": dataset,
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def _sample_values(csv_paths: list[str], column: str, limit: int = 1) -> list[str]:
    """
    从上传文件里取某个原始列的真实取值（去重、保持出现顺序）

    为什么读盘而不是查库：这个接口在第 2 步（字段确认页）被调用，此时用户
    还没点构建，数据库里没有他的数据。写死取值（改前的「深圳/钻石/美妆」）
    就是把 demo 的取值塞进他自己的界面——字段映射对了，示例却指着一个
    他库里根本不存在的值。

    pandas 局部 import：本模块顶层刻意不引重依赖（见文件头注释），
    读 500 行 CSV 是毫秒级，不值得为它把服务启动拖到十几秒。
    """
    import pandas as pd

    for path in csv_paths:
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", nrows=500)
        except Exception:  # noqa: BLE001 读不出来就当这列没取值
            continue
        if column not in df.columns:
            continue
        values: list[str] = []
        for raw in df[column].dropna():
            text = str(raw).strip()
            if text and text not in values:
                values.append(text)
            if len(values) >= limit:
                break
        if values:
            return values
    return []


@router.get("/examples")
def examples(upload_id: str = "") -> dict:
    """
    示例问题：根据**已确认的字段**与**上传文件里的真实取值**动态生成

    只出检索类问句。统计类问句（"有多少高价值客户"）MVP 答不上来，
    示例里放出来等于挖坑（见 docs/MVP产品目标.md 第六条）。

    取值来源有三档，依次退让、绝不编造：
        1. 字段映射到了某列 -> 读该列的真实取值填进模板
        2. 读不到取值 -> 用不含具体值的通用问法
        3. 连字段都没映射 -> 这一条不出
    """
    csv_paths: list[str] = []
    doc_names: list[str] = []
    if upload_id:
        _require_upload(upload_id)
        try:
            csvs, mds = uploads.paths(upload_id)
            csv_paths = csvs
            doc_names = [os.path.basename(p) for p in mds]
        except uploads.UploadError:
            pass

    with _STATE_LOCK:
        fields = {
            k: v for k, v in (_CONFIRMED_FIELDS.get(upload_id) or {}).items() if v
        }

    questions: list[str] = []
    for key, (template, fallback) in EXAMPLE_TEMPLATES.items():
        column = fields.get(key)
        if not column:
            continue
        if "{v}" not in template:
            questions.append(template)
            continue
        values = _sample_values(csv_paths, column, limit=1)
        # 商品名可能很长，示例里只留一个能看懂的短前缀
        questions.append(template.format(v=values[0][:12]) if values else fallback)

    # 文档类示例：只有真的上传了文档才给，且只说「里是怎么规定的」，
    # 不猜这篇讲什么（主题从文件名推不出来，猜错等于把人往空答案上引）
    if doc_names:
        questions.append(EXAMPLE_DOC_TEMPLATE.format(doc=doc_names[0]))

    # 去重后截断：示例问题超过 5 个就不再是「示例」，而是一面墙
    seen, result = set(), []
    for q in questions:
        if q not in seen:
            seen.add(q)
            result.append(q)

    return {
        "questions": result[:5],
        "based_on_fields": sorted(fields),
        "doc_count": len(doc_names),
    }


# ================= 5. 拒答文案配置（数据集级） =================
# 只开放「助手名」与「示例问句」两项。能力清单（支持哪几类问题）是只读的：
# 用户可以决定系统怎么称呼自己、举什么例子，但不能承诺系统做不到的事
# （写一句「支持预测」，问起来答不了，比不给引导更伤）。
class UiConfigRequest(BaseModel):
    dataset: str = "user"
    assistant_name: str | None = None
    sample_question: str | None = None
    # 逗号分隔、高档在前、最后一个是兜底档，例如「黑卡,金卡,银卡,普通」
    member_level_names: str | None = None


@router.get("/ui-config")
def get_ui_config(dataset: str = "user") -> dict:
    """读当前数据集的文案配置；没配过就是空 dict，由前端显示默认值"""
    from rag_demo.db.connection import reset_dataset, use_dataset
    from rag_demo.db.schema import read_ui_config
    from rag_demo.mvp.builder import resolve_dataset

    try:
        target = resolve_dataset(_scope_dataset(dataset), action="配置")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    token = use_dataset(target)
    try:
        cfg = read_ui_config()
    finally:
        reset_dataset(token)
    return {"dataset": target, "config": cfg}


@router.put("/ui-config")
def put_ui_config(req: UiConfigRequest) -> dict:
    """
    写文案配置（值为空串表示恢复默认）

    写操作走 writes_to 守卫：不声明数据集就写会落到默认的 demo（评测基线），
    这条守卫在 ingest 上已经踩过坑，配置接口不例外。
    """
    _require_writer()
    from rag_demo.db.connection import writes_to
    from rag_demo.db.schema import read_ui_config, write_ui_config
    from rag_demo.mvp.builder import resolve_dataset

    try:
        target = resolve_dataset(_scope_dataset(req.dataset), action="配置")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    values: dict[str, str | None] = {}
    if req.assistant_name is not None:
        name = req.assistant_name.strip()
        if len(name) > 30:
            raise HTTPException(status_code=400, detail="助手名太长了（超过 30 字）。")
        values["assistant_name"] = name or None
    if req.sample_question is not None:
        question = req.sample_question.strip()
        if len(question) > 100:
            raise HTTPException(status_code=400, detail="示例问句太长了（超过 100 字）。")
        values["sample_question"] = question or None
    if req.member_level_names is not None:
        # DEPRECATED（第五轮）：会员等级不再由系统推导，档位名**不再参与构建/检索**。
        # 保留这个字段只为兼容旧前端与历史配置（读得出、写得进，旧页面不会 400）；
        # 但不再校验档位数量，也不再有任何代码读它来分档。
        names = [
            n.strip()
            for n in req.member_level_names.replace("，", ",").split(",")
            if n.strip()
        ]
        if req.member_level_names.strip():
            logger.warning(
                "member_level_names 已废弃（第五轮取消会员等级推导），"
                "本次写入不影响构建结果"
            )
        values["member_level_names"] = ",".join(names) if names else None

    if not values:
        raise HTTPException(status_code=400, detail="没有要修改的配置项。")

    with writes_to(target):
        write_ui_config(values)
        cfg = read_ui_config()
    return {"dataset": target, "config": cfg}


# 接口在**文件末尾**统一挂到独立调试服务上：router 上的路由是靠上面的 @router.xxx
# 装饰器在导入期逐个注册的，include 必须发生在它们之后。
# 8000 的正式服务不走这里，而是自己 include 同一个 router（见 api/wizard.py）——
# 两个宿主共用一份实现，这是本模块拆出 router 的全部意义。
app.include_router(router)
