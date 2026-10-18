#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : builder.py
@Function: 真实构建 —— 把用户上传的文件走完整 ingest 链路写进目标数据集（M2/M3）

两种构建模式（M3 第五轮：增量更新是客户底线）
----------------------------------------------
    full        覆盖重建：清空目标数据集后全量重算（行为与 M2 完全一致）
    incremental 追加更新：**只处理本次新增/变更的文件**，只更新受影响的用户/文档，
                其余数据一行都不动。10 万行数据追加一个小文件不再重跑 2 小时。

增量模式为什么安全（三层判定，缺一不可）：
    ① 文件清单 manifest（meta: ingested_csv / ingested_docs，含 sha256）——
       判断一个文件是 new / ingested / changed；判断错了要么漏数据、
       要么把同一份订单重复累加（用户订单数直接翻倍，且不报错）。
    ② 旧库引导：manifest 为空时用 `last_build`（upload_id + at）+ 文件 mtime 推导入库状态，
       让 M3 及更早构建的库也能直接增量，不必再等一次 1.6 小时全量重建。
    ③ 用户级合并：只有新 CSV 里出现的 user_id 会被 SELECT→合并→UPDATE/INSERT，
       未出现的用户一行都不动（合并规则是纯函数 merge_profile_row，单测逐条锁住）。

链路（全部在**一个后台线程**里跑完）：
    清洗交易数据 → 聚合画像 → 生成画像向量 → 切分规则文档 → 建立检索索引

三件必须先说清楚的事
--------------------

**① 写作用域与并发锁：两个正交的保护，缺一不可**

    writes_to(dataset)      声明「这一段的写属于谁」。写操作末端是 TRUNCATE，
                            没有声明时 require_write_scope 会直接抛 UnsafeWriteError。
                            它管的是**写错库**。
    dataset_lock(dataset)   构建期间独占该数据集。它管的是**同一时刻只能有一路
                            在动这条连接**——psycopg2 连接非线程安全，构建每批
                            INSERT + commit 时另一个线程查询会撞
                            「another command is already in progress」，而且在用户
                            点查询的瞬间随机炸。

    两者不重叠：拿了锁不代表写对了库，声明了作用域也不代表别人不会同时用这条连接。
    构建线程是 `threading.Thread` 起的，**不继承 contextvar**，所以 writes_to 必须
    在这里显式进入（不能指望请求线程的设置传下来）。

**② 只重建「本次上传提供了的」那部分**（full 模式）

    CSV 有 → 重导画像（TRUNCATE + 全量重写）
    CSV 无 → 不碰 user_profile_vectors（保留上一批画像），由调用方在任务里说明
    MD  有 → 重导文档；MD 无 → 不碰 wiki_vectors，同样在任务里说明
    索引     只要动了任一部分就重建（它由两者派生，不重建就会落后于源表）

    为什么不做成「上传什么就清空什么以外的东西」：那等于替用户删除他没提的东西。
    真要清空，应该是一个显式的操作，而不是构建的副作用。

**③ 失败时的数据状态要说实话**

    full：ingest 是「先 TRUNCATE 再分批 commit」，写入过程中失败会留下部分数据
    （画像表可能只有一半用户）。重试会从头重来，所以直接重试即可。
    incremental：合并是「分批 commit」的，中途失败会留下**部分已合并**的用户；
    重试同一批会把那部分再累加一次（订单数翻倍）。所以增量失败后**必须用
    「覆盖重建」恢复**——这条提示写进任务错误说明里，不能让用户以为重试无害。
    索引是最后一步，失败时它仍是上一版——旧数据仍可查询，不会出现空索引窗口。
"""
import logging
import os
import time
from typing import Callable

from rag_demo.db.connection import dataset_lock, writes_to

logger = logging.getLogger(__name__)

# 允许构建写入的数据集白名单。
# **demo 不在里面**：它是演示底座 + 评测基线（33 题评测都跑在这份上），只能由仓库
# 自带数据经脚本重建。用户上传的数据一律进 user；test 是首跑用的试验库。
# 白名单写在服务端而不是让前端传任意库名：否则「写错库」这件事就只剩一个输入框
# 的距离——那正是 writes_to 要防的东西。
#
# M3 起多了企业库（ent_<企业ID>）：它们由账号体系在运行时注册进 config.DATASETS。
# 判断放在 `is_buildable()` 里，**只认已注册的名字**——库名不能由请求里编，
# 否则「写错库」的防线就退化成一次字符串前缀检查。
BUILDABLE_DATASETS = ("user", "test")

# 构建模式（与 mvp.app.BuildRequest.mode 同一套取值）
MODE_FULL = "full"
MODE_INCREMENTAL = "incremental"
BUILD_MODES = (MODE_INCREMENTAL, MODE_FULL)


def is_buildable(dataset: str) -> bool:
    """能否写入这个数据集：user / test，或已注册的企业库"""
    if dataset in BUILDABLE_DATASETS:
        return True
    from rag_demo.config import DATASETS, ENTERPRISE_DATASET_PREFIX

    return dataset.startswith(ENTERPRISE_DATASET_PREFIX) and dataset in DATASETS


EventFn = Callable[[dict], None]


def normalize_mode(mode: str | None) -> str:
    """
    归一构建模式：缺省算 full（兼容旧调用方/脚本），非法值明确报错

    注意 API 层默认是 incremental（第五轮的需求），而 BuildInputs 默认 full：
    脚本与测试直接构造 BuildInputs 时沿用「覆盖重建」语义，避免悄悄改变旧行为。
    """
    value = (mode or MODE_FULL).strip().lower()
    if value not in BUILD_MODES:
        raise ValueError("构建模式只能是 incremental 或 full")
    return value


class BuildInputs:
    """一次真实构建的全部输入（都是已经落盘、已解析过的东西）"""

    def __init__(self, dataset: str, csv_paths: list[str], md_paths: list[str],
                 fields: dict[str, str | None], simulate_failure: bool = False,
                 upload_id: str = "", mode: str = MODE_FULL):
        self.dataset = dataset
        self.csv_paths = csv_paths
        self.md_paths = md_paths
        self.fields = fields
        self.simulate_failure = simulate_failure
        # 这次构建用了哪个上传批次（写入 meta.last_build，供概况页一键重建）。
        # 默认空串是为了兼容既有的脚本/测试构造方式——没有批次号时仍能构建，
        # 只是概况页不会给出「重建」入口。
        self.upload_id = upload_id
        # full = 覆盖重建（旧行为）；incremental = 追加更新（第五轮新增）
        self.mode = normalize_mode(mode)


def resolve_dataset(name: str | None, action: str = "构建") -> str:
    """
    校验目标数据集；不在白名单就拒绝（含 demo）

    action 只影响报错里的措辞：查询侧也要过同一道白名单，但「不能构建到 demo」
    对提问的人来说是句错话——用户会以为自己点错了按钮。
    """
    target = (name or "user").strip() or "user"
    if not is_buildable(target):
        raise ValueError(
            f"向导只服务 {list(BUILDABLE_DATASETS)} 与企业库（ent_*），不能{action} {target!r}。"
            f"demo 是演示底座与评测基线，它自己的问答在首页（/qa），不走向导；"
            f"企业库在账号审核通过后自动注册，不能手写库名。"
        )
    return target


# ==================== 增量基线（plan 与 build 共用，只读） ====================
def load_incremental_baseline(dataset: str) -> dict:
    """
    读取增量更新所需的全部基线（**只读**，不上锁、不落盘）

    返回：
        manifest      {"csv": {...}, "docs": {...}}：已入库文件清单（可能是 mtime 引导出来的）
        available     清单是否可用于判定（False = 无法增量）
        seeded_from   "meta"（库里已有清单）/ "last_build_mtime"（旧库按 mtime 引导）/ None
        last_build    最近一次构建记录（原始 dict，可能 None）
        existing      当前规模与上次构建信息：
                      profiles / docs / chunks / built_at /
                      last_mode / last_elapsed_s / last_rows /
                      last_full_elapsed_s / last_full_rows

    所有异常都降级成「空库 + 不可用」：这是给页面用的只读查询，
    库还没建 / 连接失败都不该让 plan 接口 500。
    """
    from rag_demo.db.connection import get_conn, reset_dataset, use_dataset
    from rag_demo.db.schema import (
        read_fingerprint,
        read_ingest_manifest,
        read_last_build,
        read_last_full_build,
    )
    from rag_demo.mvp import uploads

    existing = {
        "profiles": 0,
        "docs": 0,
        "chunks": 0,
        "built_at": None,
        "last_mode": None,
        "last_elapsed_s": None,
        "last_rows": None,
        "last_full_elapsed_s": None,
        "last_full_rows": None,
    }
    baseline = {
        "manifest": {"csv": {}, "docs": {}},
        "available": False,
        "seeded_from": None,
        "last_build": None,
        "existing": existing,
    }

    token = None
    try:
        token = use_dataset(dataset)

        # 当前规模：表可能不存在（未构建的企业库），按 0 处理但继续读清单
        try:
            conn = get_conn()
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
                existing["profiles"] = int(cur.fetchone()[0] or 0)
                cur.execute("SELECT COUNT(*), COUNT(DISTINCT doc_name) FROM wiki_vectors")
                chunks, docs = cur.fetchone()
                existing["chunks"] = int(chunks or 0)
                existing["docs"] = int(docs or 0)
            finally:
                conn.rollback()  # 只读，清理事务
                cur.close()
        except Exception as e:  # noqa: BLE001 库/表不存在都只是「还没有数据」
            logger.info("增量基线：当前规模不可读（%s）: %s", dataset, e)

        # 构建时间
        try:
            fingerprint = read_fingerprint()
            existing["built_at"] = (fingerprint or {}).get("built_at")
        except Exception as e:  # noqa: BLE001
            logger.info("增量基线：指纹不可读（%s）: %s", dataset, e)

        # 清单 / 上次构建记录
        try:
            manifest = read_ingest_manifest()
        except Exception as e:  # noqa: BLE001
            logger.info("增量基线：清单不可读（%s）: %s", dataset, e)
            manifest = {"csv": {}, "docs": {}}

        try:
            last_build = read_last_build()
        except Exception as e:  # noqa: BLE001
            logger.info("增量基线：last_build 不可读（%s）: %s", dataset, e)
            last_build = None

        try:
            last_full = read_last_full_build()
        except Exception as e:  # noqa: BLE001
            logger.info("增量基线：last_full_build 不可读（%s）: %s", dataset, e)
            last_full = None

        existing["last_mode"] = (last_build or {}).get("mode")
        existing["last_elapsed_s"] = (last_build or {}).get("elapsed_s")
        existing["last_rows"] = (last_build or {}).get("rows")
        existing["last_full_elapsed_s"] = (last_full or {}).get("elapsed_s")
        existing["last_full_rows"] = (last_full or {}).get("rows")
        baseline["last_build"] = last_build

        # 数据为空（新库 / 刚清空）时不存在「增量」：必须先覆盖重建一次。
        # 清空数据空间会保留 last_build（round3 契约：重建依据），如果这时还按
        # mtime 引导出「文件已入库」，增量会误以为没有新增文件——而库里其实一条都没有。
        has_data = existing["profiles"] > 0 or existing["chunks"] > 0
        if has_data and (manifest.get("csv") or manifest.get("docs")):
            baseline["manifest"] = manifest
            baseline["available"] = True
            baseline["seeded_from"] = "meta"
        elif has_data and last_build:
            seeded = _seed_manifest_from_last_build(last_build, uploads)
            if seeded and (seeded.get("csv") or seeded.get("docs")):
                baseline["manifest"] = seeded
                baseline["available"] = True
                baseline["seeded_from"] = "last_build_mtime"
    except Exception as e:  # noqa: BLE001 数据集未注册 / 连不上库
        logger.info("增量基线不可读（%s）: %s", dataset, e)
    finally:
        if token is not None:
            reset_dataset(token)

    return baseline


def _seed_manifest_from_last_build(last_build: dict, uploads_module) -> dict | None:
    """
    旧库引导：用 last_build 的 upload_id + at 从磁盘 mtime 反推「哪些文件已入库」

    失败一律返回 None（目录没了 / 时间格式坏 / 文件读不了）：
    引导不了就只能要求用户先做一次覆盖重建——宁可不给增量，也不猜。
    """
    upload_id = last_build.get("upload_id")
    built_at = last_build.get("at")
    if not upload_id or not built_at:
        return None
    try:
        csv_paths, md_paths = uploads_module.paths(str(upload_id))
    except Exception as e:  # noqa: BLE001 目录不存在/批次号非法
        logger.info("旧库引导失败：上传目录不可用（%s）: %s", upload_id, e)
        return None
    try:
        csv_entries = [uploads_module.file_entry(p) for p in csv_paths]
        md_entries = [uploads_module.file_entry(p) for p in md_paths]
    except OSError as e:
        logger.warning("旧库引导失败：读取上传文件失败（%s）: %s", upload_id, e)
        return None
    seeded = uploads_module.seed_manifest_from_mtime(csv_entries, md_entries, str(built_at))
    logger.info(
        "旧库引导（mtime <= %s）：CSV %d 个 / 文档 %d 篇视为已入库，manifest 将在本次构建时落盘",
        built_at, len(seeded.get("csv") or {}), len(seeded.get("docs") or {}),
    )
    return seeded


def _csv_row_count(path: str) -> int:
    """
    单个 CSV 的真实行数（写增量清单用）

    与上传/解析同一口径（utf-8-sig + pandas），失败返回 0 并告警：
    清单里的 rows 只用于展示，不值得为它让一次已经成功的构建失败。
    """
    import pandas as pd

    try:
        return int(len(pd.read_csv(path, encoding="utf-8-sig")))
    except Exception as e:  # noqa: BLE001
        logger.warning("统计 CSV 行数失败（%s）: %s", path, e)
        return 0


# ==================== 构建执行 ====================
def run_build(inputs: BuildInputs, on_event: EventFn) -> dict:
    """
    在**构建线程**里执行一次真实构建；事件流通过 on_event 回给调用方

    on_event 收到的事件（调用方据此更新任务进度）：
        {"kind": "step_start",    "step": key, "total": n}
        {"kind": "step_progress", "step": key, "processed": n, "total": m}
        {"kind": "step_done",     "step": key}
        {"kind": "step_skip",     "step": key, "text": "…"}
        {"kind": "note",          "text": "…"}     给用户看的一句话说明

    重依赖（torch / sentence-transformers / pandas）**在这里才导入**：
    本包（mvp/）同时被一个「只想看界面」的毫秒级调试服务使用，
    模块级 import 会把它的启动从毫秒级拖到十几秒。
    """
    from rag_demo.cache import answer_cache
    from rag_demo.retrieval.hybrid_retriever import get_model, reload_bm25

    dataset = inputs.dataset
    if not is_buildable(dataset):   # 二次确认：调用方可能绕过 resolve_dataset
        raise ValueError(f"数据集 {dataset!r} 不在构建白名单内（user / test / 已注册企业库）")
    mode = normalize_mode(inputs.mode)

    def emit(**event) -> None:
        on_event(event)

    # ---------- 锁：整段构建独占该数据集 ----------
    # 用阻塞 acquire：能走到这里说明请求侧已经用非阻塞试探过（拿不到会直接回 409），
    # 所以这里正常是立即拿到；万一有并发构建挤进来，排队等它结束也比两边同时
    # TRUNCATE 同一张表好——那种情况的报错信息（relation is being used）根本无从解释。
    lock = dataset_lock(dataset)
    lock.acquire()
    started = time.time()
    try:
        with writes_to(dataset):
            emit(kind="note", text=f"目标数据集：{dataset}（写操作已显式声明）")
            logger.info(
                "[构建] 开始：数据集=%s 模式=%s CSV=%d 文档=%d",
                dataset, mode, len(inputs.csv_paths), len(inputs.md_paths),
            )

            # 模型用检索侧的**单例**：另起一份 bge-m3 会多占 2GB 显存（config 已警示）
            model = get_model()

            if inputs.simulate_failure:
                # 演示开关：**在写之前**失败（两种模式都一样：先炸，保证库里一点没动）
                raise RuntimeError(
                    "生成画像向量时显存不足（CUDA out of memory）。\n"
                    "处理办法：关掉其他占用显卡的程序后重试；"
                    "如果数据量较大，可以先只上传一部分 CSV 再试。"
                )

            if mode == MODE_INCREMENTAL:
                result = _build_incremental(inputs, model, emit)
            else:
                result = _build_full(inputs, model, emit)

            # ---------- 收尾：内存态与构建记录 ----------
            # 内存里的 BM25 索引按数据集各存一份，重建后必须刷新，
            # 否则查询仍用旧语料（数据更新了、答案还是旧的，且不报错）
            reload_bm25(dataset)

            # 问答缓存同理，而且它更隐蔽：缓存键是 (数据集, 问题, 检索参数)，
            # **不含任何数据版本**。不在这里清，重建后问同一个问题会秒回上一版数据
            # 算出来的答案——用户刚换了一批数据，看到的却是旧结论，且没有任何提示。
            # 整体清空的代价只是让另一个数据集的缓存重算一遍（见 cache.py 的说明）。
            answer_cache.clear()

            result["mode"] = mode
            result["elapsed_s"] = round(time.time() - started, 1)
            # last_build 在这里写：它要带**真实总用时**（含索引刷新），且必须仍在
            # writes_to 作用域内——写错库的守卫对元数据同样有效。
            _persist_build_records(inputs, mode, result)
            logger.info("[构建] 完成：%s", result)
            return result
    finally:
        lock.release()
        logger.info("[构建] 释放数据集锁: %s（用时 %.1fs）", dataset, time.time() - started)


def _persist_build_records(inputs: BuildInputs, mode: str, result: dict) -> None:
    """
    落盘 last_build（重建依据）与全量构建记录 / 增量清单

    last_build 的扩展字段（第五轮契约 C）：
        mode / rows / profiles / elapsed_s —— 概况页与 plan 据此显示「上次构建是什么模式、多大、多久」
    """
    from rag_demo.db.schema import write_last_build, write_last_full_build
    from rag_demo.kb_stats import serialize_last_build

    at = time.strftime("%Y-%m-%d %H:%M:%S")
    if mode == MODE_INCREMENTAL:
        csv_count = int(result.get("csv_processed") or 0)
        md_count = int(result.get("md_processed") or 0)
    else:
        csv_count = len(inputs.csv_paths)
        md_count = len(inputs.md_paths)

    payload = serialize_last_build(
        upload_id=inputs.upload_id,
        fields=inputs.fields,
        csv=csv_count,
        md=md_count,
        at=at,
    )
    payload.update(
        {
            "mode": mode,
            "rows": result.get("rows"),
            "profiles": result.get("profiles"),
            "elapsed_s": result.get("elapsed_s"),
        }
    )
    write_last_build(payload)

    if mode == MODE_FULL:
        # 「覆盖重建」卡要显示「上次全量用时 / 行数」，即使最近一次是增量构建也要有值
        write_last_full_build(
            {
                "at": at,
                "elapsed_s": result.get("elapsed_s"),
                "rows": result.get("rows"),
                "profiles": result.get("profiles"),
                "index_total": result.get("index_total"),
            }
        )


def _build_full(inputs: BuildInputs, model, emit) -> dict:
    """覆盖重建：行为与 M2 一致（TRUNCATE + 全量重写），另外维护增量清单"""
    from rag_demo.db.schema import (
        read_ingest_manifest,
        write_ingest_manifest,
    )
    from rag_demo.ingest_data import column_map_from_confirmed, ingest_transactions
    from rag_demo.ingest_docs import ingest_documents
    from rag_demo.mvp import uploads
    from rag_demo.tools.build_search_index import build_index

    dataset = inputs.dataset
    total_rows = 0
    # None 表示「本次没有重建画像」，与「重建出 0 个用户」是两件事：
    # 报告给用户的那句话不能把它们混成一句（见 app.py 里完成提示的两种写法）
    total_profiles: int | None = None
    # 会员等级这一列的来源：user / none（见 ingest_data.build_profiles，第五轮起不推导）
    level_source: str | None = None
    doc_stats: dict | None = None

    if inputs.csv_paths:
        emit(kind="step_start", step="clean", total=0)
        emit(kind="step_start", step="profile", total=0)
        emit(kind="step_start", step="embed", total=0)

        def on_phase(stage: str, info: dict) -> None:
            if stage == "load_done":
                emit(kind="step_done", step="clean", total=info["rows"])
            elif stage == "profile_done":
                emit(kind="step_done", step="profile", total=info["profiles"])
            elif stage == "split_done":
                emit(kind="step_progress", step="embed",
                     processed=0, total=info["documents"])

        def on_progress(done: int, total: int, label: str) -> None:
            emit(kind="step_progress", step="embed", processed=done, total=total)

        stats = ingest_transactions(
            csv_paths=inputs.csv_paths,
            column_map=column_map_from_confirmed(inputs.fields),
            model=model,
            progress=on_progress,
            on_phase=on_phase,
        )
        total_rows = stats["rows"]
        total_profiles = stats["profiles"]
        level_source = stats.get("member_level_source")
        emit(kind="step_done", step="embed", total=stats["profiles"])
    else:
        emit(kind="note", text="本次没有交易数据：跳过画像重建，保留上一批画像。")
        for key in ("clean", "profile", "embed"):
            emit(kind="step_skip", step=key,
                 text="本次没有上传交易数据，这一步已跳过（上一批画像保持不变）")
        logger.info("[构建] 无 CSV，跳过画像重建")

    if inputs.md_paths:
        docs = [(os.path.basename(p), uploads.read_text(p)) for p in inputs.md_paths]
        emit(kind="step_start", step="chunk", total=len(docs))

        def on_doc_progress(done: int, total: int, name: str) -> None:
            emit(kind="step_progress", step="chunk", processed=done, total=total)

        # 传入上传目录：检索层做 Parent Document 全文化时要按它找原文，
        # 只认 data/docs 的话用户上传的文档永远扩展不了
        doc_stats = ingest_documents(
            docs,
            model=model,
            progress=on_doc_progress,
            docs_dir=os.path.dirname(inputs.md_paths[0]),
        )
        emit(kind="step_done", step="chunk", total=doc_stats["docs"])
    else:
        emit(kind="note", text="本次没有规则文档：跳过文档重建，问答仍引用上一批文档。")
        emit(kind="step_skip", step="chunk",
             text="本次没有上传规则文档，这一步已跳过（上一批文档保持不变）")
        logger.info("[构建] 无 MD，跳过文档重建")

    # ---------- 索引：最后一步，也是唯一「一步做完」的步骤 ----------
    emit(kind="step_start", step="index", total=0)

    def on_index_phase(stage: str, info: dict) -> None:
        emit(kind="step_progress", step="index",
             processed=info.get("rows", 0), total=info.get("rows", 0))

    def on_index_progress(done: int, total: int, label: str) -> None:
        emit(kind="step_progress", step="index", processed=done, total=total)

    index_stats = build_index(progress=on_index_progress, on_phase=on_index_phase)
    emit(kind="step_done", step="index", total=index_stats["total"])

    # ---------- 增量清单：覆盖重建 = 清单整体替换成「本批全部文件」 ----------
    # 只更新了画像/文档时，另一部分的清单**保留原值**：
    # 全量构建允许「只传文档」，那不该把画像文件的清单清空（否则下次增量会
    # 把已经入库的 CSV 当新增再合并一遍）。
    at = time.strftime("%Y-%m-%d %H:%M:%S")
    csv_map: dict[str, dict] = {}
    md_map: dict[str, dict] = {}
    try:
        previous = read_ingest_manifest()
        previous_csv = previous.get("csv") or {}
        previous_docs = previous.get("docs") or {}
    except Exception as e:  # noqa: BLE001 清单读失败按空处理，本次能写多少写多少
        logger.warning("读取旧增量清单失败（%s）: %s", dataset, e)
        previous_csv, previous_docs = {}, {}

    if inputs.csv_paths:
        for path in inputs.csv_paths:
            name = os.path.basename(path)
            csv_map[name] = {
                "sha256": uploads.sha256_file(path),
                "rows": _csv_row_count(path),
                "ingested_at": at,
            }
    else:
        csv_map = dict(previous_csv)

    if inputs.md_paths:
        per_doc = (doc_stats or {}).get("docs_detail") or {}
        for path in inputs.md_paths:
            name = os.path.basename(path)
            md_map[name] = {
                "sha256": uploads.sha256_file(path),
                "chunks": int(per_doc.get(name, 0)),
                "ingested_at": at,
            }
    else:
        md_map = dict(previous_docs)

    write_ingest_manifest(csv_map, md_map)

    docs_imported = int((doc_stats or {}).get("docs") or 0)
    return {
        "dataset": dataset,
        "mode": MODE_FULL,
        "rows": total_rows,             # 本次入库的交易行数
        "profiles": total_profiles,     # 画像条数；None = 本次没重建画像
        "profiles_new": int(total_profiles or 0),
        "profiles_updated": 0,
        "docs_new": docs_imported,
        "docs_updated": 0,
        "rows_incremental": total_rows,
        "skipped_changed_csv": [],
        "member_level_source": level_source,
        "index_total": index_stats["total"],
        "freshness": index_stats["fresh"]["status"],
    }


def _build_incremental(inputs: BuildInputs, model, emit) -> dict:
    """
    追加更新：只处理新增/变更文件，只动受影响的用户/文档/索引行

    流程：
        1. 读基线（manifest；旧库用 last_build mtime 引导）
        2. 判文件状态：CSV 新增才合并（同名改内容→跳过并告警），MD 新增/变更→更新
        3. merge_incremental   → 只更新新 CSV 里出现的用户（其余一行不动）
        4. ingest_documents_incremental → 同名文档先删后写（其余文档一行不动）
        5. update_index        → 只重算受影响 user_id / doc_name 的索引行
        6. 合并写回 manifest，落盘 last_build（在 run_build 里统一写）

    没有任何新增文件时**明确报错**（契约 A）：否则会出现「构建成功但什么都没变」，
    用户以为追加生效了、实际数据没进库。
    """
    from rag_demo.db import schema_facts
    from rag_demo.db.schema import write_ingest_manifest
    from rag_demo.ingest_data import column_map_from_confirmed, merge_incremental
    from rag_demo.ingest_docs import ingest_documents_incremental
    from rag_demo.mvp import uploads
    from rag_demo.tools.build_search_index import update_index

    dataset = inputs.dataset
    baseline = load_incremental_baseline(dataset)
    existing = baseline["existing"]

    if not baseline["available"]:
        if existing["profiles"] or existing["chunks"]:
            raise ValueError(
                "该数据空间由旧版本构建，无法判断哪些文件已入库；"
                "请先做一次「覆盖重建」以启用增量更新"
            )
        raise ValueError(
            "当前数据空间还没有构建过（或数据已清空），无法增量更新；请选择「覆盖重建」"
        )

    manifest = baseline["manifest"]
    csv_by_name = {os.path.basename(p): p for p in inputs.csv_paths}
    md_by_name = {os.path.basename(p): p for p in inputs.md_paths}
    try:
        csv_entries = [uploads.file_entry(p) for p in inputs.csv_paths]
        md_entries = [uploads.file_entry(p) for p in inputs.md_paths]
    except OSError as e:
        raise ValueError(f"读取上传文件失败，无法增量更新：{e}") from e

    classified = uploads.classify_files(csv_entries, md_entries, manifest)
    # 处理顺序稳定（按文件名），保证同样输入得到同样结果
    new_csv_names = sorted(e["name"] for e in classified["new_csv"])
    md_entries_to_process = sorted(
        classified["new_md"] + classified["changed_md"], key=lambda e: e["name"]
    )
    md_names = [e["name"] for e in md_entries_to_process]
    skipped_changed_csv = list(classified["skipped_changed_csv"])

    if not new_csv_names and not md_names:
        raise ValueError("本批次没有新增文件可追加；要重算全部数据请选「覆盖重建」")

    logger.info(
        "[增量构建] 数据集=%s 新增CSV=%d 文档(新增/更新)=%d 跳过(同名改内容的CSV)=%d",
        dataset, len(new_csv_names), len(md_names), len(skipped_changed_csv),
    )
    emit(
        kind="note",
        text=(
            f"增量模式：新增 {len(new_csv_names)} 个 CSV、{len(md_names)} 篇文档；"
            f"其余 {existing['profiles']:,} 个用户与已有文档保持不变"
        ),
    )
    if skipped_changed_csv:
        emit(
            kind="note",
            text=(
                "同名 CSV 内容有变化，为避免重复累加已跳过："
                + "、".join(skipped_changed_csv[:3])
                + ("…" if len(skipped_changed_csv) > 3 else "")
                + "（请改名后重新上传，或选择「覆盖重建」）"
            ),
        )

    result: dict = {
        "dataset": dataset,
        "mode": MODE_INCREMENTAL,
        "rows": 0,
        "profiles": 0,
        "profiles_new": 0,
        "profiles_updated": 0,
        "docs_new": 0,
        "docs_updated": 0,
        "rows_incremental": 0,
        "skipped_changed_csv": skipped_changed_csv,
        "member_level_source": None,
        "index_total": 0,
        "freshness": None,
        # last_build 用：本次处理了多少文件（不是整个批次）
        "csv_processed": len(new_csv_names),
        "md_processed": len(md_names),
    }
    affected_user_ids: list[str] = []
    doc_stats: dict | None = None

    # ---------- 1. 画像：只合并新 CSV 里出现的用户 ----------
    if new_csv_names:
        emit(kind="step_start", step="clean", total=0)
        emit(kind="step_start", step="profile", total=0)
        emit(kind="step_start", step="embed", total=0)

        def on_phase(stage: str, info: dict) -> None:
            if stage == "load_done":
                emit(kind="step_done", step="clean", total=info["rows"])
            elif stage == "profile_done":
                emit(kind="step_done", step="profile", total=info["profiles"])

        def on_progress(done: int, total: int, label: str) -> None:
            emit(kind="step_progress", step="embed", processed=done, total=total)

        stats = merge_incremental(
            csv_paths=[csv_by_name[name] for name in new_csv_names],
            column_map=column_map_from_confirmed(inputs.fields),
            model=model,
            progress=on_progress,
            on_phase=on_phase,
        )
        affected_user_ids = list(stats.get("user_ids") or [])
        emit(kind="step_done", step="embed", total=stats["profiles"])
        result.update(
            {
                "rows": stats["rows_incremental"],
                "rows_incremental": stats["rows_incremental"],
                "profiles": stats["profiles"],
                "profiles_new": stats["profiles_new"],
                "profiles_updated": stats["profiles_updated"],
                "member_level_source": stats.get("member_level_source"),
            }
        )
    else:
        emit(kind="note", text="本次没有新增交易数据：跳过画像合并，已有用户数据不变。")
        for key in ("clean", "profile", "embed"):
            emit(kind="step_skip", step=key,
                 text="本次没有新增交易数据，这一步已跳过（已有画像保持不变）")
        logger.info("[增量构建] 无新增 CSV，跳过画像合并")

    # ---------- 2. 文档：新增直接插入，同名（内容变）先删旧分块再写 ----------
    if md_names:
        docs = [(name, uploads.read_text(md_by_name[name])) for name in md_names]
        emit(kind="step_start", step="chunk", total=len(docs))

        def on_doc_progress(done: int, total: int, name: str) -> None:
            emit(kind="step_progress", step="chunk", processed=done, total=total)

        doc_stats = ingest_documents_incremental(
            docs,
            model=model,
            progress=on_doc_progress,
            docs_dir=os.path.dirname(inputs.md_paths[0]) if inputs.md_paths else None,
        )
        emit(kind="step_done", step="chunk", total=len(md_names))
        result["docs_new"] = doc_stats["docs_new"]
        result["docs_updated"] = doc_stats["docs_updated"]
    else:
        emit(kind="note", text="本次没有新增/变更文档：跳过文档更新，已有文档不变。")
        emit(kind="step_skip", step="chunk",
             text="本次没有新增/变更文档，这一步已跳过（已有文档保持不变）")
        logger.info("[增量构建] 无新增/变更 MD，跳过文档更新")

    # ---------- 3. 检索索引：只重算受影响 user_id / doc_name ----------
    emit(kind="step_start", step="index", total=0)
    index_stats = update_index(affected_user_ids, md_names)
    emit(kind="step_progress", step="index",
         processed=index_stats["updated"], total=index_stats["updated"])
    emit(kind="step_done", step="index", total=index_stats["updated"])
    result["index_total"] = index_stats["total"]
    result["freshness"] = (index_stats.get("fresh") or {}).get("status")
    result["index_updated"] = index_stats["updated"]
    result["index_removed"] = index_stats["removed"]

    # ---------- 4. 清单合并：基线 ∪ 本次处理过的文件 ----------
    at = time.strftime("%Y-%m-%d %H:%M:%S")
    sha_by_name = {e["name"]: e["sha256"] for e in csv_entries + md_entries}
    csv_map = dict(manifest.get("csv") or {})
    docs_map = dict(manifest.get("docs") or {})
    for name in new_csv_names:
        csv_map[name] = {
            "sha256": sha_by_name.get(name, ""),
            "rows": _csv_row_count(csv_by_name[name]),
            "ingested_at": at,
        }
    per_doc = (doc_stats or {}).get("docs_chunks") or {}
    for name in md_names:
        docs_map[name] = {
            "sha256": sha_by_name.get(name, ""),
            "chunks": int(per_doc.get(name, 0)),
            "ingested_at": at,
        }
    write_ingest_manifest(csv_map, docs_map)

    # 画像/文档都变了，提示词里的条数与枚举随之过期（merge_incremental 内部已失效一次，
    # 只更新文档时不会经过那里，所以这里统一再失效一次，幂等）
    schema_facts.invalidate()

    emit(
        kind="note",
        text=(
            f"增量构建完成：更新/新增 {result['profiles']} 个用户、"
            f"{result['docs_new'] + result['docs_updated']} 篇文档，"
            f"其余数据未改动"
        ),
    )
    return result
