#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RRF 融合参数 k 的消融实验（纯检索口径，不调用 LLM 裁判）

为什么做
--------
`rrf_fusion` 的 k 原来写死在签名里（60）。为了给这个默认值提供**数据依据**——
而不是只留下一句「公式就这么写的」——需要一个**只改 k、其他一切不动**的对照实验：
同一份测试集、同一套检索配置、同一批检索式，只把 k 换成 [10, 30, 60, 100]，看
检索质量（来源命中 / 名次）怎么变。

能证明什么、不能证明什么
------------------------
能满足的是「k 取这些值时表现是否稳定、k=60 是否处在平稳区、k 调小/调大有没有
可见收益或损失」；**不能**凭 23 道有期望来源的题断言「60 是全局最优」——样本量
与指标天花板（RRF 层宏召回可能已 100%）都会限制统计功效。实验结论必须按实际
数字写，不预设「60 一定最好」。

实验设计（控制变量）
--------------------
- 固定测试集：`src/rag_demo/tests/eval_questions.json`（33 题，与 run_eval 同一份）；
- 固定数据集：`--dataset demo`（评测基线库）；
- 固定检索配置：向量 top20 + BM25 top20（config.KEYWORD_RETRIEVER=bm25）→ RRF；
- 唯一变量：RRF 的 k ∈ [10, 30, 60, 100]；
- **不调用大模型**：不跑多路规划、不生成回答、不跑 LLM-as-a-Judge。因此没有 Pass Rate
  （JSON 里显式写 null 并注明原因，不伪造分数）。生成侧与裁判侧完全未参与，
  测试集与 Judge Prompt 天然保持一致（后者根本没被读取）。

两层指标（都是「来源命中」口径，复用 rag_demo.eval_utils 的判定函数）
--------------------------------------------------------------------
1. RRF 融合层（layer="rrf"）：`hybrid_search(q)` 返回的 top-N 候选（默认 30）。
   这是 k 直接作用的一层——决定「哪些候选进入候选池、以什么名次」。
   指标：Source Recall（期望来源在 top-30 中的比例）、Recall@5、
        MRR（第一个命中的期望来源的 1/名次）。
2. 最终上下文层（layer="final"）：`search_variants([(direct, q)])` 走完
   分池取舍 + 精排 + 去重后的最终候选（画像 top-3 + 文档每路 top-3 上限）。
   这是真实链路喂给 LLM 的那份来源；本层不含多路规划（无 LLM），等价于
   `ENABLE_MULTI_QUERY=False` 时的检索路径，保证 4 个 k 的输入完全一致。

为什么只跑单路「直接检索」：多路规划是一次 LLM 调用，输出每次都可能不同，
把它放进消融实验会把「k 的差异」和「改写的随机性」混在一起。消融只回答
「同样一批检索式，k 变了对排序/召回有什么影响」。

缓存
----
本脚本**不经过** `pipeline.answer_question`，所以 `answer_cache` 完全不参与，
不存在跨 k 命中旧结果的可能。同时缓存键已加入 `rrf_k`（cache.AnswerCache.make_key），
即便将来有人改成走问答入口，也不会串结果。

用法（项目根目录）
------------------
    # 全量消融（默认 k=10,30,60,100，结果写 tests/ablation_rrf_k/）
    uv run python scripts/run_ablation_k.py

    # 小规模试跑
    uv run python scripts/run_ablation_k.py --limit 3 --out-dir tmp/ablation_trial

    # 指定 k / 数据集 / 设备
    uv run python scripts/run_ablation_k.py --ks 20,60 --dataset demo --device cpu

产物
----
    <out-dir>/k_<k>.json     每个 k 一份：逐题明细 + 该 k 的汇总指标
    <out-dir>/summary.json   全部 k 的汇总 + 实验元信息（含默认 k 恢复确认）
    <out-dir>/report.md      机械生成的 Markdown 表格（分析结论由人/Lead 另写）

退出前**一定**把运行时 k 恢复默认（config.RRF_K=60），并在 summary.json 里记录
`restored_default_k`，避免实验进程残留状态影响正常系统。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = ROOT / "src" / "rag_demo" / "tests" / "eval_questions.json"
DEFAULT_OUT_DIR = ROOT / "tests" / "ablation_rrf_k"
DEFAULT_KS = (10, 30, 60, 100)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RRF 融合参数 k 消融实验（纯检索口径，不调 LLM）"
    )
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="评测集 JSON 路径")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="结果输出目录")
    parser.add_argument(
        "--ks", default=",".join(str(k) for k in DEFAULT_KS),
        help="要测试的 k 值，逗号分隔（默认 10,30,60,100）",
    )
    parser.add_argument("--dataset", default="demo", help="评测数据集（默认 demo）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（试跑用）")
    parser.add_argument("--only", default=None, help="只跑指定题号，逗号分隔")
    parser.add_argument("--top-k", type=int, default=30, help="RRF 融合层评估的候选数（默认 30）")
    parser.add_argument(
        "--device", choices=("cpu", "cuda"), default="cpu",
        help="推理设备（默认 cpu：本机会与常驻 API 服务抢 6GB 显存，CPU 更稳且可复现）",
    )
    return parser.parse_args()


def _parse_ks(raw: str) -> list[int]:
    ks: list[int] = []
    for piece in str(raw).split(","):
        piece = piece.strip()
        if not piece:
            continue
        value = int(piece)
        if value < 1:
            raise SystemExit(f"k 必须 >= 1：{value}")
        if value not in ks:
            ks.append(value)
    if not ks:
        raise SystemExit("--ks 不能为空")
    return ks


def load_questions(path: Path, limit: int | None, only: str | None) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"评测集不存在：{path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list) or not data:
        raise SystemExit(f"评测集格式不对（应为非空数组）：{path}")
    required = {"id", "question", "expect_sources"}
    for item in data:
        missing = required - set(item)
        if missing:
            raise SystemExit(f"题目 {item.get('id', '?')} 缺字段：{sorted(missing)}")

    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        selected = [q for q in data if q.get("id") in wanted]
        missing = wanted - {q.get("id") for q in selected}
        if missing:
            raise SystemExit(f"--only 里有不存在的题号：{sorted(missing)}")
        return selected
    if limit is not None:
        return data[: max(0, limit)]
    return data


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _aggregate(rows: list[dict], layer: str) -> dict:
    """按层聚合宏/微召回、MRR、Recall@5 与耗时。分母口径见模块文档。"""
    recalls: list[float] = []
    rrs: list[float] = []
    recall_at_5: list[float] = []
    micro_hit = 0
    micro_expected = 0
    hit_cases = 0
    errors = 0
    for row in rows:
        payload = row.get(layer) or {}
        if payload.get("error"):
            errors += 1
        recall = payload.get("recall") or {}
        if recall.get("recall") is not None:
            recalls.append(recall["recall"])
            micro_hit += len(recall.get("hit") or [])
            micro_expected += len(recall.get("expected") or [])
        rank = payload.get("rank") or {}
        if rank.get("rr") is not None:
            rrs.append(rank["rr"])
            if rank.get("rank") is not None:
                hit_cases += 1
        if recall.get("recall") is not None:
            top5_hit = len(
                set(recall.get("expected") or [])
                & set(payload.get("top5_sources") or [])
            )
            recall_at_5.append(top5_hit / len(recall.get("expected") or []))
    elapsed = [
        row.get(layer, {}).get("elapsed_s")
        for row in rows
        if isinstance(row.get(layer, {}).get("elapsed_s"), (int, float))
    ]
    return {
        "n_questions": len(rows),
        "n_with_expected": len(recalls),
        "n_errors": errors,
        "source_recall_macro": _mean(recalls),
        "source_recall_micro": (micro_hit / micro_expected) if micro_expected else None,
        "source_recall_at_5": _mean(recall_at_5),
        "mrr": _mean(rrs),
        "hit_rate": (hit_cases / len(rrs)) if rrs else None,
        "avg_elapsed_s": round(_mean(elapsed), 4) if elapsed else None,
        "p95_elapsed_s": (
            round(sorted(elapsed)[min(len(elapsed) - 1, int(len(elapsed) * 0.95))], 4)
            if elapsed else None
        ),
        "total_elapsed_s": round(sum(elapsed), 3) if elapsed else None,
    }


def _evaluate_question(item: dict, hybrid_search, search_variants, strategy_direct: str,
                       top_k: int, top_k_rrf: int, source_recall, first_hit_rank,
                       unique_sources) -> dict:
    """单题双跑：RRF 融合层 + 最终上下文层，逐题明细写进 JSON 供审计。"""
    question = item.get("question") or ""
    expected = item.get("expect_sources") or []
    row: dict = {
        "id": item.get("id"),
        "module": item.get("module"),
        "type": item.get("type"),
        "question": question,
        "expected_sources": list(expected),
    }

    # ---------- ① RRF 融合层：k 直接作用的一层 ----------
    started = time.perf_counter()
    rrf_error = None
    fused: list[dict] = []
    try:
        fused = hybrid_search(question, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 - 单题失败不能打断整轮消融
        rrf_error = f"{type(exc).__name__}: {exc}"
    rrf_elapsed = time.perf_counter() - started
    rrf_ranked = unique_sources(hit.get("source") for hit in fused)
    row["rrf"] = {
        "sources": rrf_ranked,
        "top5_sources": rrf_ranked[:5],
        "top_ids": [hit.get("id") for hit in fused[: top_k]],
        "recall": source_recall(expected, rrf_ranked),
        "rank": first_hit_rank(expected, rrf_ranked),
        "elapsed_s": round(rrf_elapsed, 4),
        "error": rrf_error,
    }

    # ---------- ② 最终上下文层：真实链路喂给 LLM 的来源 ----------
    started = time.perf_counter()
    final_error = None
    final: list[dict] = []
    try:
        final = search_variants(
            [(strategy_direct, question)], top_k=top_k_rrf, origin_query=question
        )
    except Exception as exc:  # noqa: BLE001
        final_error = f"{type(exc).__name__}: {exc}"
    final_elapsed = time.perf_counter() - started
    final_ranked = unique_sources(cand.get("source") for cand in final)
    row["final"] = {
        "sources": final_ranked,
        "top5_sources": final_ranked[:5],
        "ids": [cand.get("id") for cand in final],
        "recall": source_recall(expected, final_ranked),
        "rank": first_hit_rank(expected, final_ranked),
        "elapsed_s": round(final_elapsed, 4),
        "error": final_error,
    }
    return row


def _fmt(value, digits: int = 1, percent: bool = True) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%" if percent else f"{value:.{digits}f}"


def _render_report(results: list[dict], args: argparse.Namespace,
                   question_count: int, started_at: str) -> str:
    lines: list[str] = []
    lines.append("# RRF 融合参数 k 消融实验报告（纯检索口径）")
    lines.append("")
    lines.append(f"- 实验时间：{started_at}")
    lines.append(f"- 测试集：`{args.questions}`（{question_count} 题，其中 "
                 f"{results[0]['rrf']['n_with_expected']} 题有期望来源，参与召回/MRR）")
    lines.append(f"- 数据集：`{args.dataset}`；RRF 候选数 top-{args.top_k}；"
                 f"检索配置：向量 top20 + BM25 top20")
    lines.append("- 唯一变量：RRF k；**未调用任何大模型**（无多路规划 / 无回答生成 / 无 LLM 裁判），"
                 "故 Pass Rate 不适用（记为 —），不存在测试集或 Judge Prompt 漂移")
    lines.append("- 指标口径：Source Recall = 期望来源命中数/期望数（`eval_utils.source_recall`）；"
                 "MRR = 首个命中的期望来源的 1/名次 的题均值（未命中记 0，"
                 "`eval_utils.first_hit_rank`）；耗时只统计检索本身（预热后）")
    lines.append("")
    lines.append("## 汇总表")
    lines.append("")
    lines.append("| k值 | RRF 来源召回率（宏） | RRF 来源召回率（微） | RRF Recall@5 | RRF MRR "
                 "| 最终上下文召回率（宏） | 最终上下文召回率（微） | 最终上下文 Recall@5 "
                 "| 最终上下文 MRR | 平均耗时/题 | Pass Rate |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for result in results:
        rrf = result["rrf"]
        final = result["final"]
        lines.append(
            f"| {result['k']} "
            f"| {_fmt(rrf['source_recall_macro'])} "
            f"| {_fmt(rrf['source_recall_micro'])} "
            f"| {_fmt(rrf['source_recall_at_5'])} "
            f"| {_fmt(rrf['mrr'], 3, percent=False)} "
            f"| {_fmt(final['source_recall_macro'])} "
            f"| {_fmt(final['source_recall_micro'])} "
            f"| {_fmt(final['source_recall_at_5'])} "
            f"| {_fmt(final['mrr'], 3, percent=False)} "
            f"| {_fmt(final['avg_elapsed_s'], 3, percent=False)}s "
            f"| —（未跑 LLM 裁判） |"
        )
    lines.append("")
    lines.append("> 耗时口径：只统计**最终上下文层**（一次完整检索 + 分池精排）的每题目均耗时。"
                 "RRF 层各 k 的耗时含进程冷启动/缓存影响（第一个 k 明显偏高），"
                 "**不可用于「耗时随 k 变化」的结论**——k 只改变融合的算术，理论上不改变检索成本。")
    lines.append("")
    lines.append("## 逐题明细（RRF 融合层：首个命中名次 / 最终上下文层来源）")
    lines.append("")
    header = "| 题号 | 期望来源 | " + " | ".join(f"k={r['k']} 名次" for r in results) + " |"
    lines.append(header)
    lines.append("| :--- | :--- | " + " | ".join(":---" for _ in results) + " |")
    by_k = {r["k"]: {row["id"]: row for row in r["rows"]} for r in results}
    for row in results[0]["rows"]:
        qid = row["id"]
        expected = "、".join(row["expected_sources"]) or "—（不计入）"
        cells = []
        for result in results:
            rank = (by_k[result["k"]].get(qid) or {}).get("rrf", {}).get("rank") or {}
            cells.append("—" if rank.get("rank") is None else f"#{rank['rank']}")
        lines.append(f"| {qid} | {expected} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    # 设备必须在 import torch / rag_demo 之前定下来（config 在 import 时读 CUDA 可用性）
    if args.device == "cpu":
        import os

        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))

    from rag_demo.config import RRF_K, TOP_K_RRF
    from rag_demo.db.connection import reset_dataset, use_dataset
    from rag_demo.eval_utils import first_hit_rank, source_recall, unique_sources
    from rag_demo.retrieval.hybrid_retriever import (
        get_rrf_k,
        hybrid_search,
        set_rrf_k,
    )
    from rag_demo.retrieval.query_processor import STRATEGY_DIRECT, search_variants

    ks = _parse_ks(args.ks)
    questions = load_questions(Path(args.questions), args.limit, args.only)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(
        f"[开始] 题目={len(questions)} | k={ks} | 数据集={args.dataset} | "
        f"设备={args.device} | RRF 候选=top-{args.top_k} | 输出={out_dir}",
        flush=True,
    )
    print(f"[基线] 默认 RRF_K={RRF_K}，当前生效 get_rrf_k()={get_rrf_k()}", flush=True)

    token = use_dataset(args.dataset)
    results: list[dict] = []
    try:
        # 预热：模型加载 / BM25 索引 / jieba 词典 / reranker 都放在计时之外，
        # 否则第一题的耗时会混进「加载时间」，4 个 k 的首题都异常高。
        print("[预热] 加载 embedding / BM25 / reranker ...", flush=True)
        warm_started = time.perf_counter()
        hybrid_search("预热", top_k=5)
        search_variants([(STRATEGY_DIRECT, "预热")], top_k=TOP_K_RRF)
        print(f"[预热] 完成 {time.perf_counter() - warm_started:.1f}s", flush=True)

        for k in ks:
            set_rrf_k(k)
            print(f"\n========== [k={k}] 开始 ==========", flush=True)
            rows: list[dict] = []
            k_started = time.perf_counter()
            for index, item in enumerate(questions, 1):
                row = _evaluate_question(
                    item, hybrid_search, search_variants, STRATEGY_DIRECT,
                    args.top_k, TOP_K_RRF, source_recall, first_hit_rank, unique_sources,
                )
                rows.append(row)
                rrf_rank = row["rrf"]["rank"]
                rrf_recall = row["rrf"]["recall"]
                print(
                    f"  [{index:02d}/{len(questions)}] {row['id']:<8} "
                    f"rrf_recall={_fmt(rrf_recall['recall'])} "
                    f"rrf_rank={'—' if rrf_rank['rank'] is None else '#' + str(rrf_rank['rank'])} "
                    f"final_sources={row['final']['sources']} "
                    f"{row['final']['elapsed_s']:.2f}s",
                    flush=True,
                )

            rrf_summary = _aggregate(rows, "rrf")
            final_summary = _aggregate(rows, "final")
            payload = {
                "k": k,
                "dataset": args.dataset,
                "questions_path": str(Path(args.questions).resolve()),
                "n_questions": len(rows),
                "rrf_top_n": args.top_k,
                "rrf": rrf_summary,
                "final": final_summary,
                "elapsed_total_s": round(time.perf_counter() - k_started, 2),
                "rows": rows,
            }
            (out_dir / f"k_{k}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            results.append(payload)
            print(
                f"[k={k}] 汇总：RRF 召回(宏)={_fmt(rrf_summary['source_recall_macro'])} "
                f"MRR={_fmt(rrf_summary['mrr'], 3, percent=False)} | "
                f"最终召回(宏)={_fmt(final_summary['source_recall_macro'])} "
                f"MRR={_fmt(final_summary['mrr'], 3, percent=False)} | "
                f"平均耗时={_fmt(final_summary['avg_elapsed_s'], 3, percent=False)}s | "
                f"总耗时={payload['elapsed_total_s']}s",
                flush=True,
            )
    finally:
        # 无论成功失败都必须恢复默认 k=60：这个进程跑完，系统要回到「正常状态」
        set_rrf_k(None)
        reset_dataset(token)

    restored = get_rrf_k()
    if restored != RRF_K:
        raise SystemExit(f"[失败] 运行时 k 恢复默认失败：{restored} != {RRF_K}")

    summary = {
        "started_at": started_at,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": args.dataset,
        "device": args.device,
        "questions_path": str(Path(args.questions).resolve()),
        "n_questions": len(questions),
        "ks": ks,
        "rrf_top_n": args.top_k,
        "default_rrf_k": RRF_K,
        "restored_default_k": restored,
        "pass_rate_note": "纯检索口径：未调用 LLM 裁判，Pass Rate 不适用（不伪造分数）",
        "results": [
            {
                "k": result["k"],
                "rrf": result["rrf"],
                "final": result["final"],
                "elapsed_total_s": result["elapsed_total_s"],
            }
            for result in results
        ],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(
        _render_report(results, args, len(questions), started_at), encoding="utf-8"
    )

    print("\n================ 消融结果 ================", flush=True)
    print(f"{'k':>4} | {'RRF召回(宏)':>12} | {'RRF召回(微)':>12} | {'RRF MRR':>8} | "
          f"{'最终召回(宏)':>12} | {'最终MRR':>8} | {'平均耗时':>8}")
    for result in results:
        rrf = result["rrf"]
        final = result["final"]
        print(
            f"{result['k']:>4} | {_fmt(rrf['source_recall_macro']):>12} | "
            f"{_fmt(rrf['source_recall_micro']):>12} | {_fmt(rrf['mrr'], 3, False):>8} | "
            f"{_fmt(final['source_recall_macro']):>12} | "
            f"{_fmt(final['mrr'], 3, False):>8} | "
            f"{_fmt(final['avg_elapsed_s'], 3, False) + 's':>8}"
        )
    print(f"\n[恢复] 运行时 k 已恢复默认 {restored}（config.RRF_K={RRF_K}）", flush=True)
    print(f"结果目录: {out_dir}", flush=True)
    print(f"汇总: {out_dir / 'summary.json'}", flush=True)
    print(f"报告: {out_dir / 'report.md'}", flush=True)
    return 0


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(run(args))
    except KeyboardInterrupt:
        print("\n[中断] 消融实验被手动停止。", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
