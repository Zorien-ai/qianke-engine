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

M2 进度（哪一步是真的，哪一步还是假的）：
    第 1 步 上传   **真的**：multipart 落盘 → 统一转 UTF-8 → pandas 真读出行数与列名
    第 2 步 字段   **真的**：同义词字典匹配，key 与入库口径同一套（FIELD_DEFS）
    第 3 步 构建   假的：进度仍是模拟的，但每步的**总量取自真实文件**（行数、分块数）
    第 4 步 查询   假的：答案来自内置样例。接真实检索链路是下一步

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

# 复用现有切分逻辑（无 torch / 无数据库副作用），保证「预估分块数」与真实入库口径一致
from rag_demo.splitter import split_wiki_documents

from rag_demo.mvp import uploads
from rag_demo.mvp.mock_data import (
    ANSWER_BANK,
    BUILD_STEPS,
    EXAMPLE_COMMON,
    EXAMPLE_TEMPLATES,
    FALLBACK_ANSWER,
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
# 只取 6 个登记平台的 CSV：`ecommerce_data.csv` 不在平台清单内
# （见 ingest_data.KNOWN_PLATFORMS），放进示例只会让用户一上来就收到一条
# 「未登记来源」警告，那是我们在解释自己的数据问题，不是他的问题。
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

    missed = [f["label"] for f in fields if not f["detected"] and f["required"]]
    if missed:
        warnings.append("关键字段未识别到，建议手动指定：" + "、".join(missed))

    return fields, warnings


# ================= 请求模型 =================
# 注意入参里**没有文件内容**：文件走 multipart 上传落到磁盘，接口之间只传
# upload_id（见 uploads.py）。M1 那种「把正文塞进 JSON 一路带着走」的模型已删——
# 它让每个接口都变成「数据搬运工」，也让服务端无法成为数据的真源。
class BuildRequest(BaseModel):
    upload_id: str
    fields: dict[str, str | None] = Field(default_factory=dict)
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


# ================= 页面 =================
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """四步向导页"""
    return FileResponse(os.path.join(STATIC_DIR, "wizard.html"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mvp-wizard", "build_tasks": len(_BUILD_TASKS)}


# ================= 1. 上传 =================
def _state_payload(upload_id: str) -> dict:
    """
    该上传批次的完整状态：文件清单 + 字段识别 + 文档结构

    上传、删文件、示例填满、刷新页面恢复状态——四个场景返回**同一个结构**，
    前端因此只写一个渲染函数，不必区分「刚上传」和「恢复到一半」。
    """
    csv_files = []
    md_paths = []
    try:
        scanned = uploads.scan(upload_id)
        csv_files = scanned["csv_files"]
        md_paths = uploads.paths(upload_id)[1]
    except uploads.UploadError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    fields, field_warnings = _analyze_fields(csv_files)
    docs, doc_warnings = _analyze_docs(md_paths)

    return {
        "upload_id": upload_id,
        "csv_files": csv_files,
        # md 只回元信息（名字/大小/字符数），正文留在服务端——前端渲染文件列表用不到
        # 正文，而它可能有几万字，来回搬运只会让响应变大、还多一份可以不一致的副本
        "md_files": [
            {"name": d["name"], "size": d["size"], "chars": d["chars"]} for d in docs
        ],
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
    if not files:
        raise HTTPException(status_code=400, detail="还没有选择任何文件。")

    payload: list[tuple[str, bytes]] = []
    for f in files:
        payload.append((f.filename or "未命名", await f.read()))

    try:
        uid, rejected = uploads.save(upload_id or None, payload)
    except uploads.UploadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

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
    try:
        uploads.remove(req.upload_id, req.name)
        csv_paths, md_paths = uploads.paths(req.upload_id)
    except uploads.UploadError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 删光了就连批次一起消失（uploads.remove 已经清了目录），返回空状态让前端能继续渲染
    if not csv_paths and not md_paths:
        return _empty_state(req.upload_id)
    return _state_payload(req.upload_id)


@router.get("/upload/{upload_id}")
def upload_state(upload_id: str) -> dict:
    """取批次当前状态（页面刷新后恢复用）"""
    return _state_payload(upload_id)


@router.get("/sample")
def sample() -> dict:
    """用仓库自带的真实数据填满（走与真人上传完全相同的那条落盘/解析路径）"""
    uid, rejected = uploads.save(None, _read_sample_files())
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


def _run_build(task_id: str, req: BuildRequest, totals: dict) -> None:
    """
    **仍然是假构建**：按步骤推进进度，节奏刻意放慢到几秒

    但每个步骤的「总量」已经是真的了（`totals` 由 build 从落盘文件算出来）：
    清洗 N 行、切分 M 块都对着用户自己上传的那批文件，不再是前端报上来的数字。
    下一步（真实入库）只需把进度来源从 sleep 换成 ingest 的回调，前端一行不用改。

    totals 由调用方算好再传进来：它要读磁盘、跑切分器，属于「请求线程干的活」，
    不该在构建线程里做——否则「进度 0%」的那几秒其实是在算总量，看着像卡住。
    """
    task = _BUILD_TASKS[task_id]
    # 每步的 tick 数：与权重成正比，让进度条的推进速度看起来均匀
    ticks = {"clean": 11, "profile": 9, "embed": 12, "chunk": 8, "index": 10}
    done_weight = 0

    for i, step in enumerate(BUILD_STEPS):
        key = step["key"]
        total = totals.get(key, 0)
        tick_count = ticks.get(key, 8)

        with _BUILD_LOCK:
            task["step_index"] = i
            task["steps"][i]["status"] = "running"
            task["steps"][i]["total"] = total

        for t in range(tick_count):
            time.sleep(0.12)
            with _BUILD_LOCK:
                if task["status"] == "cancelled":
                    return

            within = (t + 1) / tick_count

            if req.simulate_failure and key == "embed" and within >= 0.6:
                with _BUILD_LOCK:
                    task["status"] = "failed"
                    task["steps"][i]["status"] = "failed"
                    task["error"] = (
                        "生成画像向量时显存不足（CUDA out of memory）。\n"
                        "处理办法：关掉其他占用显卡的程序后重试；"
                        "如果数据量较大，可以先只上传一部分 CSV 再试。"
                    )
                    task["note"] = "构建在第 3 步失败，已处理的数据不会污染索引，可以直接重试。"
                logger.warning("构建任务 %s 按演示开关失败于 %s", task_id, key)
                return

            processed = int(total * within)
            with _BUILD_LOCK:
                task["steps"][i]["percent"] = round(within * 100)
                task["steps"][i]["processed"] = processed
                task["percent"] = round(done_weight + step["weight"] * within)
                task["processed"] = processed
                task["total"] = total
                task["note"] = f"{step['label']}：已处理 {processed:,} {step['unit']}" if total else step["label"]

        with _BUILD_LOCK:
            task["steps"][i]["status"] = "done"
            task["steps"][i]["percent"] = 100
            task["steps"][i]["processed"] = total
        done_weight += step["weight"]

    with _BUILD_LOCK:
        task["status"] = "done"
        task["percent"] = 100
        task["step_index"] = len(BUILD_STEPS)
        task["note"] = "构建完成，可以开始提问了"


@router.post("/build")
def build(req: BuildRequest) -> dict:
    """启动构建任务，返回 task_id；前端随后轮询 /build/{id}"""
    try:
        csv_paths, md_paths = uploads.paths(req.upload_id)
    except uploads.UploadError as e:
        # 上传内容没了（清过盘 / 批次号是编的）：明确让用户回第 1 步，
        # 而不是给一个「构建成功但查不到东西」的空任务
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not csv_paths and not md_paths:
        raise HTTPException(status_code=400, detail="没有可构建的数据，请回到第 1 步上传文件。")

    # 必填但没映射的字段：**只警告不拦截**——MVP 明确要求「允许跳过不重要字段」，
    # 用户的判断优先于我们的规则。真正拦下来只会让人卡在这一步。
    missing = [
        spec["label"] for spec in FIELD_DEFS
        if spec["required"] and not req.fields.get(spec["key"])
    ]
    # 只传文档、没有交易数据：仍允许构建（文档问答本来就不需要画像），
    # 但必须说清楚「这次构建不出画像」，否则用户会以为查不到人群是自己的问题。
    if not csv_paths:
        missing.append("全部交易数据（本次只构建规则文档，无法回答人群类问题）")
        logger.info("构建任务不含 CSV，仅文档问答")

    # 每步的「总量」在这里算好交给构建线程：数字全部来自落盘文件，
    # 不再由前端报上来（前端报的数字是可以被改的，也不该由它负责统计）。
    scanned = uploads.scan(req.upload_id)
    rows = sum(f["row_count"] for f in scanned["csv_files"])
    docs, _ = _analyze_docs(md_paths)
    chunk_total = sum(d["est_chunks"] for d in docs)
    totals = {
        "clean": rows,
        # 用户数是**估**的：真实去重发生在入库那一步（一行用户 = 一条画像），
        # 现在还没走到那里，所以这里带一个明确的经验比例，不假装是真值
        "profile": int(rows * 0.62),
        "embed": int(rows * 0.62),
        "chunk": len(md_paths),
        "index": chunk_total or len(md_paths),
    }

    task_id = uuid.uuid4().hex[:12]
    with _BUILD_LOCK:
        _BUILD_TASKS[task_id] = {
            "task_id": task_id,
            "upload_id": req.upload_id,
            "status": "running",
            "percent": 0,
            "step_index": 0,
            "steps": _build_step_state(),
            "processed": 0,
            "total": 0,
            "note": "正在准备…",
            "error": None,
            "missing_required": missing,
            "started_at": time.time(),
        }
        # 只保留最近的任务，避免长时间开着进程内存无限涨
        for old in sorted(_BUILD_TASKS, key=lambda k: _BUILD_TASKS[k]["started_at"])[:-5]:
            _BUILD_TASKS.pop(old, None)
        with _STATE_LOCK:
            _CONFIRMED_FIELDS[req.upload_id] = dict(req.fields)

    threading.Thread(target=_run_build, args=(task_id, req, totals), daemon=True).start()
    logger.info("构建任务已启动: %s（批次 %s：CSV %d 个 / 文档 %d 篇，清洗 %d 行 / 切分 %d 块）",
                task_id, req.upload_id, len(csv_paths), len(md_paths), rows, chunk_total)
    return {"task_id": task_id}


@router.get("/build/{task_id}")
def build_progress(task_id: str) -> dict:
    task = _BUILD_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="构建任务不存在或已过期，请回到第 3 步重新点击「开始构建」。")
    with _BUILD_LOCK:
        return deepcopy(task)


# ================= 3. 查询 =================
def _pick_answer(question: str) -> dict:
    """关键词命中打分，取命中最多的那条；都没命中走兜底话术"""
    best, best_score = None, 0
    for item in ANSWER_BANK:
        score = sum(1 for kw in item["keywords"] if kw in question)
        if score > best_score:
            best, best_score = item, score
    return best or FALLBACK_ANSWER


@router.post("/query")
def query(req: QueryRequest) -> dict:
    """
    假查询：返回带引用来源的答案

    刻意保留 1 秒以上的耗时——MVP 验收里「5~20 秒内返回」是真实链路的目标，
    原型阶段如果答案瞬间弹出，等待态（加载中、禁用重复提交）就没机会被检验。
    """
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入一个问题再提交。")
    if len(question) > 200:
        raise HTTPException(status_code=400, detail="问题太长了（超过 200 字），请精简后再问。")

    started = time.time()
    time.sleep(1.2)
    picked = _pick_answer(question)

    # 文档清单从**磁盘**取（用户可能刷新过页面、服务可能重启过），
    # 只有「确认过的字段」是流程中间态，才留在内存里
    doc_names: list[str] = []
    if req.upload_id:
        try:
            doc_names = [os.path.basename(p) for p in uploads.paths(req.upload_id)[1]]
        except uploads.UploadError:
            logger.info("查询引用了不存在的上传批次 %s，按「无文档」处理", req.upload_id)
    with _STATE_LOCK:
        configured = {
            k: v for k, v in (_CONFIRMED_FIELDS.get(req.upload_id or "") or {}).items() if v
        }

    # 没有任何文档时，答案里的来源指向空气——提前说清楚，比给一个没有出处的答案诚实
    if not doc_names:
        return {
            "answer": "当前还没有构建任何规则文档，所以只能给出通用说明、无法提供引用来源。",
            "sources": [],
            "kind": "retrieval",
            "elapsed_ms": int((time.time() - started) * 1000),
            "degraded": True,
        }

    return {
        "answer": picked["answer"],
        "sources": picked["sources"],
        "kind": "retrieval",
        "elapsed_ms": int((time.time() - started) * 1000),
        "degraded": False,
        "used_fields": list(configured.keys()),
    }


@router.get("/examples")
def examples(upload_id: str = "") -> dict:
    """
    示例问题：根据**已确认的字段**动态生成

    只出检索类问句。统计类问句（"有多少高价值客户"）MVP 答不上来，
    示例里放出来等于挖坑（见 docs/MVP产品目标.md 第六条）。
    """
    doc_names: list[str] = []
    if upload_id:
        try:
            doc_names = [os.path.basename(p) for p in uploads.paths(upload_id)[1]]
        except uploads.UploadError:
            pass
    with _STATE_LOCK:
        fields = {k for k, v in (_CONFIRMED_FIELDS.get(upload_id) or {}).items() if v}

    questions: list[str] = []
    for key, qs in EXAMPLE_TEMPLATES.items():
        if key in fields:
            questions.extend(qs)
    questions.extend(EXAMPLE_COMMON)

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


# 接口在**文件末尾**统一挂到独立调试服务上：router 上的路由是靠上面的 @router.xxx
# 装饰器在导入期逐个注册的，include 必须发生在它们之后。
# 8000 的正式服务不走这里，而是自己 include 同一个 router（见 api/wizard.py）——
# 两个宿主共用一份实现，这是本模块拆出 router 的全部意义。
app.include_router(router)
