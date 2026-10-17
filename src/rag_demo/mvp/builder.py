#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : builder.py
@Function: 真实构建 —— 把用户上传的文件走完整 ingest 链路写进目标数据集（M2）

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

**② 只重建「本次上传提供了的」那部分**

    CSV 有 → 重导画像（TRUNCATE + 全量重写）
    CSV 无 → 不碰 user_profile_vectors（保留上一批画像），由调用方在任务里说明
    MD  有 → 重导文档；MD 无 → 不碰 wiki_vectors，同样在任务里说明
    索引     只要动了任一部分就重建（它由两者派生，不重建就会落后于源表）

    为什么不做成「上传什么就清空什么以外的东西」：那等于替用户删除他没提的东西。
    真要清空，应该是一个显式的操作，而不是构建的副作用。

**③ 失败时的数据状态要说实话**

    ingest 是「先 TRUNCATE 再分批 commit」，因此**写入过程中失败会留下部分数据**
    （画像表可能只有一半用户）。这是既有 ingest 的语义，本模块不吞掉它，而是把
    「已写入的是部分数据、重试会从头重来」写进任务的错误说明里。
    索引是最后一步，失败时它仍是上一版——所以旧数据仍可查询，不会出现空索引窗口。
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


def is_buildable(dataset: str) -> bool:
    """能否写入这个数据集：user / test，或已注册的企业库"""
    if dataset in BUILDABLE_DATASETS:
        return True
    from rag_demo.config import DATASETS, ENTERPRISE_DATASET_PREFIX

    return dataset.startswith(ENTERPRISE_DATASET_PREFIX) and dataset in DATASETS

EventFn = Callable[[dict], None]


class BuildInputs:
    """一次真实构建的全部输入（都是已经落盘、已解析过的东西）"""

    def __init__(self, dataset: str, csv_paths: list[str], md_paths: list[str],
                 fields: dict[str, str | None], simulate_failure: bool = False):
        self.dataset = dataset
        self.csv_paths = csv_paths
        self.md_paths = md_paths
        self.fields = fields
        self.simulate_failure = simulate_failure


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


def run_build(inputs: BuildInputs, on_event: EventFn) -> dict:
    """
    在**构建线程**里执行一次真实构建；事件流通过 on_event 回给调用方

    on_event 收到的事件（调用方据此更新任务进度）：
        {"kind": "step_start",    "step": key, "total": n}
        {"kind": "step_progress", "step": key, "processed": n, "total": m}
        {"kind": "step_done",     "step": key}
        {"kind": "note",          "text": "…"}     给用户看的一句话说明

    重依赖（torch / sentence-transformers / pandas）**在这里才导入**：
    本包（mvp/）同时被一个「只想看界面」的毫秒级调试服务使用，
    模块级 import 会把它的启动从毫秒级拖到十几秒。
    """
    from rag_demo.cache import answer_cache
    from rag_demo.ingest_data import column_map_from_confirmed, ingest_transactions
    from rag_demo.ingest_docs import ingest_documents
    from rag_demo.mvp import uploads
    from rag_demo.retrieval.hybrid_retriever import get_model, reload_bm25
    from rag_demo.tools.build_search_index import build_index

    dataset = inputs.dataset
    if not is_buildable(dataset):   # 二次确认：调用方可能绕过 resolve_dataset
        raise ValueError(f"数据集 {dataset!r} 不在构建白名单内（user / test / 已注册企业库）")

    def emit(**event) -> None:
        on_event(event)

    # ---------- 锁：整段构建独占该数据集 ----------
    # 用阻塞 acquire：能走到这里说明请求侧已经用非阻塞试探过（拿不到会直接回 409），
    # 所以这里正常是立即拿到；万一有并发构建挤进来，排队等它结束也比两边同时
    # TRUNCATE 同一张表好——那种情况的报错信息（relation is being used）根本无从解释。
    lock = dataset_lock(dataset)
    lock.acquire()
    started = time.time()
    result: dict = {}
    try:
        with writes_to(dataset):
            emit(kind="note", text=f"目标数据集：{dataset}（写操作已显式声明）")
            logger.info("[构建] 开始：数据集=%s CSV=%d 文档=%d",
                        dataset, len(inputs.csv_paths), len(inputs.md_paths))

            # 模型用检索侧的**单例**：另起一份 bge-m3 会多占 2GB 显存（config 已警示）
            model = get_model()

            total_rows = 0
            # None 表示「本次没有重建画像」，与「重建出 0 个用户」是两件事：
            # 报告给用户的那句话不能把它们混成一句（见 app.py 里完成提示的两种写法）
            total_profiles: int | None = None
            # 会员等级这一列的来源：user / derived / none（见 ingest_data.build_profiles）
            level_source: str | None = None
            if inputs.csv_paths:
                emit(kind="step_start", step="clean", total=0)
                emit(kind="step_start", step="profile", total=0)
                emit(kind="step_start", step="embed", total=0)
                if inputs.simulate_failure:
                    # 演示开关：**在写之前**失败。真实 ingest 无法中途打断（打断会留下
                    # 半张表的数据），所以把「模拟失败」放在破坏性操作之前——
                    # 既验证了失败提示与重试，又保证库里一点没动。
                    raise RuntimeError(
                        "生成画像向量时显存不足（CUDA out of memory）。\n"
                        "处理办法：关掉其他占用显卡的程序后重试；"
                        "如果数据量较大，可以先只上传一部分 CSV 再试。"
                    )

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

            # 内存里的 BM25 索引按数据集各存一份，重建后必须刷新，
            # 否则查询仍用旧语料（数据更新了、答案还是旧的，且不报错）
            reload_bm25(dataset)

            # 问答缓存同理，而且它更隐蔽：缓存键是 (数据集, 问题, 检索参数)，
            # **不含任何数据版本**。不在这里清，重建后问同一个问题会秒回上一版数据
            # 算出来的答案——用户刚换了一批数据，看到的却是旧结论，且没有任何提示。
            # 整体清空的代价只是让另一个数据集的缓存重算一遍（见 cache.py 的说明）。
            answer_cache.clear()

            result = {
                "dataset": dataset,
                "rows": total_rows,             # 本次入库的交易行数
                "profiles": total_profiles,     # 画像条数；None = 本次没重建画像
                "member_level_source": level_source,
                "index_total": index_stats["total"],
                "freshness": index_stats["fresh"]["status"],
                "elapsed_s": round(time.time() - started, 1),
            }
            logger.info("[构建] 完成：%s", result)
            return result
    finally:
        lock.release()
        logger.info("[构建] 释放数据集锁: %s（用时 %.1fs）", dataset, time.time() - started)
