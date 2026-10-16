#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : app.py
@Function: MVP M1 交互原型的**冻结快照** —— 假数据跑通「上传 → 确认 → 构建 → 查询」

启动（项目根目录下执行）：
    uv run uvicorn m1_mock.app:app --port 8001 --app-dir prototype

访问（与冻结前的 URL 完全一致，测试者手上的链接不会断）：
    http://127.0.0.1:8001/          四步向导页
    http://127.0.0.1:8001/health    存活探针

⚠ 这是快照，不是活代码：M1 期间给 3 位技术同事试用过的那个环境。
  8001 从此由它提供，**不要在这里做 M2 的迭代**——M2 改 src/rag_demo/mvp/ 或
  api/ 都行，改不到这里（这正是复制一份出来的目的）。

为什么要独立复制（2026-10-16）：
    mvp/app.py 的原设计是「M2 把本文件里的 mock 实现换成真实实现，前端一行不用改」。
    那意味着 M2 第一天就会改到真人测试环境正在跑的那份文件——测试者会看到页面
    在他们眼皮底下变化，出了问题也分不清是"新代码的 bug"还是"正在改的中间态"。
    所以把 M1 整体冻结一份出来，8001 只认这份快照，M2 在 src/ 里随便动。

为什么连切分器也一起冻结（原先 import rag_demo.splitter）：
    只要还 import 一次 rag_demo.*，M2 在重构那个模块时（改签名、换依赖、
    甚至只是 import 期间抛错）就能把 8001 打挂。冻结的要求是**连依赖也冻**，
    否则"独立"只独立了一半。切分逻辑本身 40 行、无状态，复制过来的代价远小于
    耦合的代价；它只用于「预估分块数」，口径漂移最多让数字对不上真实流水线，
    不影响任何人做界面测试。

与 rag_demo.api.main（8000）的关系：
    并列的两个服务，不是同一份代码的两条路。api/main.py 启动要加载
    bge-m3 / 精排 / 意图模型，还要连库；本快照刻意不 import config / torch /
    数据库 / rag_demo 任何模块，启动是毫秒级的，离线也能演示。
"""
import logging
import os
import re
import threading
import time
import uuid
from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# 切分逻辑的冻结副本（原先 import rag_demo.splitter）。为什么连它也冻：见模块 docstring
from m1_mock.split_estimate import split_wiki_documents

from m1_mock.mock_data import (
    ANSWER_BANK,
    BUILD_STEPS,
    EXAMPLE_COMMON,
    EXAMPLE_TEMPLATES,
    FALLBACK_ANSWER,
    FIELD_DEFS,
    SAMPLE_CSV_FILES,
    SAMPLE_MD_FILES,
    match_column,
)

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="MVP M1 交互原型", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ================= 会话态（MVP 单用户，进程内即可） =================
# 说明：M1 是本地单用户原型，不做多租户，所以这里用一个进程内字典。
# M2 接真实后端时，这里会变成「任务表 + 数据库」。
_STATE_LOCK = threading.Lock()
_SESSION: dict = {"fields": {}, "csv_files": [], "md_files": []}
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


def _analyze_docs(md_files: list[dict]) -> tuple[list[dict], list[str]]:
    """逐篇 .md 统计标题结构与预估分块数，产出文档级警告"""
    results: list[dict] = []
    warnings: list[str] = []

    for f in md_files:
        name = f.get("name") or "未命名.md"
        text = f.get("text") or ""
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
            "size": f.get("size", 0),
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
class CsvFile(BaseModel):
    name: str
    size: int = 0
    encoding: str | None = None
    row_count: int = 0
    columns: list[str] = Field(default_factory=list)


class MdFile(BaseModel):
    name: str
    size: int = 0
    text: str = ""


class AnalyzeRequest(BaseModel):
    csv_files: list[CsvFile] = Field(default_factory=list)
    md_files: list[MdFile] = Field(default_factory=list)


class BuildRequest(BaseModel):
    fields: dict[str, str | None] = Field(default_factory=dict)
    csv_files: list[CsvFile] = Field(default_factory=list)
    md_files: list[MdFile] = Field(default_factory=list)
    # 演示用：勾选后在「生成画像向量」这一步故意失败，
    # 用来验证「失败有可读中文提示 + 可重试」这条验收项。
    simulate_failure: bool = False


class QueryRequest(BaseModel):
    question: str


# ================= 页面 =================
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """四步向导页"""
    return FileResponse(os.path.join(STATIC_DIR, "wizard.html"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mvp-m1-mock", "build_tasks": len(_BUILD_TASKS)}


# ================= 1. 上传 =================
@app.get("/api/mvp/sample")
def sample() -> dict:
    """示例数据 manifest：让运营不用准备文件就能先走一遍流程"""
    return {"csv_files": SAMPLE_CSV_FILES, "md_files": SAMPLE_MD_FILES}


@app.post("/api/mvp/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    """分析上传文件：字段识别 + 文档结构校验（对应步骤 2 的内容）"""
    if not req.csv_files and not req.md_files:
        raise HTTPException(status_code=400, detail="还没有上传任何文件，请先上传 CSV 或 Markdown 文档。")

    fields, field_warnings = _analyze_fields([f.model_dump() for f in req.csv_files])
    docs, doc_warnings = _analyze_docs([f.model_dump() for f in req.md_files])

    with _STATE_LOCK:
        _SESSION["csv_files"] = [f.model_dump() for f in req.csv_files]
        _SESSION["md_files"] = [f.model_dump() for f in req.md_files]

    total_rows = sum(f.row_count for f in req.csv_files)
    return {
        "fields": fields,
        "docs": docs,
        "warnings": field_warnings + doc_warnings,
        "summary": {
            "csv_count": len(req.csv_files),
            "md_count": len(req.md_files),
            "total_rows": total_rows,
            "total_chunks": sum(d["est_chunks"] for d in docs),
            "detected_fields": sum(1 for f in fields if f["detected"]),
            "total_fields": len(fields),
        },
    }


# ================= 2. 一键构建 =================
def _build_step_state() -> list[dict]:
    return [
        {"key": s["key"], "label": s["label"], "unit": s["unit"],
         "status": "pending", "percent": 0, "processed": 0, "total": 0}
        for s in BUILD_STEPS
    ]


def _run_build(task_id: str, req: BuildRequest) -> None:
    """
    假构建：按步骤推进进度，节奏刻意放慢到几秒

    为什么要真线程 + 轮询，而不是前端 setTimeout 演一遍：
    进度条最容易骗人的地方是「它只是动画」。这里让 percent 和 processed
    由服务端算，前端只负责显示——M2 换成真实任务时，前端连轮询间隔都不用改。
    """
    task = _BUILD_TASKS[task_id]
    rows = sum(f.row_count for f in req.csv_files) or 0
    users = int(rows * 0.62) or 0
    doc_count = len(req.md_files)
    chunk_total = sum(
        _estimate_chunks(f.text, f.name) for f in req.md_files
    ) or doc_count

    totals = {"clean": rows, "profile": users, "embed": users, "chunk": doc_count, "index": chunk_total}
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


@app.post("/api/mvp/build")
def build(req: BuildRequest) -> dict:
    """启动构建任务，返回 task_id；前端随后轮询 /api/mvp/build/{id}"""
    if not req.csv_files and not req.md_files:
        raise HTTPException(status_code=400, detail="没有可构建的数据，请回到第 1 步上传文件。")

    # 必填但没映射的字段：**只警告不拦截**——MVP 明确要求「允许跳过不重要字段」，
    # 用户的判断优先于我们的规则。真正拦下来只会让人卡在这一步。
    missing = [
        spec["label"] for spec in FIELD_DEFS
        if spec["required"] and not req.fields.get(spec["key"])
    ]
    # 只传文档、没有交易数据：仍允许构建（文档问答本来就不需要画像），
    # 但必须说清楚「这次构建不出画像」，否则用户会以为查不到人群是自己的问题。
    if not req.csv_files:
        missing.append("全部交易数据（本次只构建规则文档，无法回答人群类问题）")
        logger.info("构建任务不含 CSV，仅文档问答")

    task_id = uuid.uuid4().hex[:12]
    with _BUILD_LOCK:
        _BUILD_TASKS[task_id] = {
            "task_id": task_id,
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
        _SESSION["fields"] = dict(req.fields)

    threading.Thread(target=_run_build, args=(task_id, req), daemon=True).start()
    logger.info("构建任务已启动: %s（CSV %d 个 / 文档 %d 篇）", task_id, len(req.csv_files), len(req.md_files))
    return {"task_id": task_id}


@app.get("/api/mvp/build/{task_id}")
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


@app.post("/api/mvp/query")
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

    with _STATE_LOCK:
        configured = {k: v for k, v in (_SESSION.get("fields") or {}).items() if v}
        doc_names = [f["name"] for f in _SESSION.get("md_files") or []]

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


@app.get("/api/mvp/examples")
def examples() -> dict:
    """
    示例问题：根据**已确认的字段**动态生成

    只出检索类问句。统计类问句（"有多少高价值客户"）MVP 答不上来，
    示例里放出来等于挖坑（见 docs/MVP产品目标.md 第六条）。
    """
    with _STATE_LOCK:
        fields = {k for k, v in (_SESSION.get("fields") or {}).items() if v}
        doc_names = [f["name"] for f in _SESSION.get("md_files") or []]

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
