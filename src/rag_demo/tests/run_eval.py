import argparse
import os
import json
import statistics
import time
from collections import defaultdict
from datetime import date

from rag_demo.config import BASE_DIR
from rag_demo.pipeline import answer_question

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")
QUESTIONS_PATH = os.path.join(TESTS_DIR, "eval_questions.json")
RESULTS_PATH = os.path.join(TESTS_DIR, "eval_results.json")

# SQL 失败的典型措辞（旧归档无 rows_count 字段时的启发式依据）
SQL_FAIL_HINTS = ("没有符合", "查询未能完成", "查询失败", "无法确定", "无法判断")


def parse_args() -> argparse.Namespace:
    """命令行参数"""
    parser = argparse.ArgumentParser(description="用户画像 RAG 评测")
    parser.add_argument(
        "--tag", default="",
        help="归档标签，如 gpu_v3；指定后额外输出 eval_results_<tag>_<日期>.json",
    )
    parser.add_argument(
        "--recalc", default="",
        help="对已有结果文件重算指标（不调用模型），传文件名或绝对路径",
    )
    parser.add_argument(
        "--repeat", type=int, default=1,
        help="每道题重复跑几轮（默认 1）。取中位数为准，并输出 min/中位/max 分布 —— "
             "单次测量不可信：LLM 耗时波动很大，改配置后只跑一遍分不清是优化还是抽样。",
    )
    return parser.parse_args()


def evaluate_result(r: dict) -> None:
    """
    就地计算一条结果的指标，区分 SQL 与 RAG 两种路由。

    - RAG 题：source_match / wiki_hit 有意义
    - SQL 题：expect_sources 是按 RAG 设计的，套用会恒为失败，
             故改用 sql_ok（是否真的拿到结构化结果）
    - 负样本（expect_sources 为空）：无自动判定依据，passed 置 None 留给人工
    """
    route = r.get("route", "rag")
    expect = set(r.get("expect_sources") or [])
    actual = set(r.get("actual_sources") or [])
    answer = r.get("answer") or ""

    # 来源交集
    r["source_match"] = sorted(expect & actual)

    # 期望的 wiki 文档是否命中
    expect_md = {s for s in expect if s.endswith(".md")}
    r["wiki_hit"] = bool(expect_md & actual)

    if route == "sql":
        rows = r.get("rows_count")
        if rows is None:
            # 兼容旧归档：用 answer 措辞启发式判断
            r["sql_ok"] = bool(answer) and not any(h in answer for h in SQL_FAIL_HINTS)
            r["sql_ok_source"] = "heuristic"
        else:
            r["sql_ok"] = bool(rows) and not r.get("error")
            r["sql_ok_source"] = "rows_count"
        r["passed"] = r["sql_ok"]
    else:
        r["sql_ok"] = None
        r["passed"] = bool(r["source_match"]) if expect else None


def run_one(item: dict, repeat: int = 1) -> dict:
    q = item["question"]
    times: list[float] = []
    result: dict = {}

    for _ in range(max(1, repeat)):
        t0 = time.time()
        # 走统一问答入口（含意图路由：聚合/统计类问题会走 Text2SQL）
        #
        # ⚠️ use_cache=False 是必须的，不能省。
        #    answer_question 默认 use_cache=True，而缓存是**进程级**的：
        #    同一个进程里重复问同一题，第二轮起会直接命中（0 秒），
        #    测出来的耗时就没有任何意义。此前没暴露，只是因为每次
        #    `uv run python` 都是新进程、且 20 道题互不重复。
        result = answer_question(q, use_cache=False)
        times.append(time.time() - t0)

    sources = [s["source"] for s in result.get("sources", [])]
    unique_sources = list(dict.fromkeys(sources))

    return {
        "id": item["id"],
        "module": item.get("module", "unknown"),
        "route": result.get("route", "unknown"),
        "question": q,
        "type": item["type"],
        "expect_wiki": item["expect_wiki"],
        "expect_sources": item["expect_sources"],
        "actual_sources": unique_sources,
        "sql": result.get("sql", ""),
        "rows_count": result.get("rows_count"),
        "error": result.get("error"),
        "answer": result.get("answer", ""),
        "sources_count": len(result.get("sources", [])),
        # 向后兼容：仍是单值，但取中位数而非「最后那一次」
        "elapsed_sec": round(statistics.median(times), 2),
        # 各轮原始值，用于看分布（repeat=1 时只有一个元素）
        "elapsed_all": [round(t, 2) for t in times],
        "acceptance": item["acceptance"],
        "manual_score": None,  # 人工填 0/1
        "note": ""
    }


def print_timing_spread(results: list[dict]) -> None:
    """
    耗时分布（min / 中位 / max）

    只报平均值会掩盖波动：实测同一配置下同一道题能差数倍
    （历史上出现过输出更短反而慢 10 倍的情况，根因是思考长度波动）。
    看 min 与 max 才知道「这次快了」是真改善还是抽样偏差。
    """
    all_times: list[float] = []
    per_item: list[tuple[str, float, float, float, int]] = []
    for r in results:
        ts = r.get("elapsed_all") or (
            [r["elapsed_sec"]] if r.get("elapsed_sec") is not None else []
        )
        # 闲聊（chitchat）不调模型、耗时 0 秒，混进来会把极差撑到几百个百分点，
        # 掩盖真实波动，这里剔除
        ts = [t for t in ts if t and t > 0.1]
        if not ts:
            continue
        all_times.extend(ts)
        per_item.append(
            (r.get("id", "?"), statistics.median(ts), min(ts), max(ts), len(ts))
        )

    if not all_times:
        return

    med = statistics.median(all_times)
    lo, hi = min(all_times), max(all_times)

    print(f"\n=== 耗时分布（{len(all_times)} 次测量）===")
    print(f"  全局: min {lo:.2f}s | 中位 {med:.2f}s | max {hi:.2f}s")

    rounds = max(t[4] for t in per_item)
    if rounds > 1:
        print(f"\n  最慢 5 题（中位，共 {rounds} 轮）:")
        for qid, m, t_lo, t_hi, _ in sorted(per_item, key=lambda x: -x[1])[:5]:
            inner = (t_hi - t_lo) / m * 100 if m else 0
            print(f"    {qid:10s} 中位 {m:5.2f}s   [{t_lo:.2f} ~ {t_hi:.2f}]  题内波动 {inner:.0f}%")

        # 关键指标是「同一题内的波动」，不是「全局极差」——
        # 后者把「题目之间的天然差异」也算进去了：OPT-05 本来就比 EDGE-03 慢，
        # 那是难度差异，不是测量噪声。判断「单次测量可不可信」要看题内波动。
        inner_spreads = [
            (t_hi - t_lo) / m * 100 for _, m, t_lo, t_hi, _ in per_item if m
        ]
        if inner_spreads:
            mid_inner = statistics.median(inner_spreads)
            worst = max(per_item, key=lambda x: (x[3] - x[2]) / x[1] * 100 if x[1] else 0)
            worst_pct = (worst[3] - worst[2]) / worst[1] * 100
            print(f"\n  题内波动: 中位 {mid_inner:.0f}% | 最大 {worst_pct:.0f}%（{worst[0]}）")
            if mid_inner > 15:
                # 不用 emoji：Windows 默认 GBK 控制台打印非 ASCII 符号会
                # UnicodeEncodeError 直接崩掉 summarize（2026-10-14 v16 实测踩中）
                print(f"  [!] 题内波动偏大，单次测量不足以判断优化是否生效；"
                      f"对比配置请用 --repeat 3 并比较中位数")
            else:
                print(f"  [OK] 题内波动 {mid_inner:.0f}%，测量可信；"
                      f"对比配置时比较中位数即可")
    else:
        print("  （单轮结果，看不出题内波动；加 --repeat 3 可看分布）")


def summarize(results: list[dict]) -> None:
    """汇总：按路由拆分，避免 SQL 题被 RAG 指标误判"""
    sql_items = [r for r in results if r.get("route") == "sql"]
    rag_items = [r for r in results if r.get("route") != "sql"]
    auto_pass = [r for r in results if r.get("passed") is True]
    undecided = [r for r in results if r.get("passed") is None]
    manual = [r for r in results if r.get("manual_score") is not None]

    print("\n=== 汇总 ===")
    print(f"成功执行: {len(results)}/{len(results)}")
    print(f"自动判定通过: {len(auto_pass)}/{len(results)}（另有 {len(undecided)} 条需人工判定）")
    if manual:
        print(f"人工评分通过: {sum(1 for r in manual if r['manual_score'] == 1)}/{len(manual)}")

    print("\n--- 按路由拆分 ---")
    if sql_items:
        print(f"SQL 路由: {len(sql_items)} 条 | 成功 {sum(1 for r in sql_items if r.get('sql_ok'))}")
    print(
        f"RAG 路由: {len(rag_items)} 条 | 来源命中 {sum(1 for r in rag_items if r.get('source_match'))}"
        f" | 期望文档命中 {sum(1 for r in rag_items if r.get('wiki_hit'))}"
    )
    print(f"平均耗时: {sum(r.get('elapsed_sec', 0) for r in results) / max(len(results), 1):.2f}s")

    # 耗时分布：只看平均值不够 —— LLM 耗时波动大，必须看最小值与最大值，
    # 才知道「这次快了」是真改善还是抽样偏差。
    print_timing_spread(results)

    # 分板块统计（自动判定）
    by_module = defaultdict(lambda: {"total": 0, "pass": 0, "undecided": 0})
    for r in results:
        m = r.get("module", "unknown")
        by_module[m]["total"] += 1
        if r.get("passed") is True:
            by_module[m]["pass"] += 1
        elif r.get("passed") is None:
            by_module[m]["undecided"] += 1

    print("\n=== 分板块统计（自动判定） ===")
    for m, s in by_module.items():
        extra = f" | 待人工 {s['undecided']}" if s["undecided"] else ""
        print(f"{m}: {s['pass']}/{s['total']}{extra}")


def recalc(path: str) -> None:
    """对已有结果文件重算指标（不调用模型）"""
    if not os.path.isabs(path):
        path = os.path.join(TESTS_DIR, path)
    with open(path, "r", encoding="utf-8") as f:
        results = json.load(f)

    for r in results:
        evaluate_result(r)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"已重算指标并写回: {path}")
    heuristic = [r for r in results if r.get("sql_ok_source") == "heuristic"]
    if heuristic:
        print(f"注意: {len(heuristic)} 条 SQL 结果无 rows_count 字段，采用 answer 措辞启发式判定")
    summarize(results)


def main() -> None:
    args = parse_args()

    if args.recalc:
        recalc(args.recalc)
        return

    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        questions = json.load(f)

    # TODO(perf): [P6] 逐题串行执行，20 题约 8 分钟。并发会撞 GPU（见 P3），
    #             若要并发建议限流为 2 并先解决 P3。详见 bug/性能隐患台账.md
    rounds = max(1, args.repeat)
    suffix = f"，每题跑 {rounds} 轮（取中位数）" if rounds > 1 else ""
    print(f"共 {len(questions)} 条评测问题{suffix}\n")

    # 预热：首次调用要把 bge-m3 与 reranker 加载进显存（十几秒），
    # 不预热的话这笔一次性开销会算在第一道题的第一轮上，把统计带偏。
    # 实测（--repeat 2）：OPT-01 第一轮 38.26s vs 第二轮 5.03s，差 7.6 倍 ——
    # 看着像「LLM 不稳定」，实际是模型加载。
    # 用真实业务问题（不是「预热一下」那种短句），否则会被判成闲聊直接返回，
    # 根本走不到检索与精排，等于没预热。
    print("[预热] 加载模型与索引（不计入统计）...")
    warm_t0 = time.time()
    answer_question("高价值用户怎么定义", use_cache=False)
    print(f"[预热] 完成，耗时 {time.time() - warm_t0:.1f}s\n")
    results = []
    for i, item in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {item['id']} | {item['question']}")
        try:
            r = run_one(item, repeat=rounds)
            evaluate_result(r)
            results.append(r)
            times = r.get("elapsed_all") or []
            timing = (
                f"{r['elapsed_sec']}s"
                if rounds == 1
                else f"中位 {r['elapsed_sec']}s [{' / '.join(str(t) for t in times)}]"
            )
            print(
                f"  → route={r['route']} | passed={r['passed']} "
                f"| 来源={r['actual_sources']} | 耗时={timing}"
            )
        except Exception as e:
            print(f"  [FAIL] {e}")
            results.append({**item, "error": str(e)})

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 带 tag 时额外输出归档快照，便于对比不同配置
    archive_path = ""
    if args.tag:
        archive_path = os.path.join(
            TESTS_DIR, f"eval_results_{args.tag}_{date.today().isoformat()}.json"
        )
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    summarize(results)

    print(f"\n结果已保存: {RESULTS_PATH}")
    if archive_path:
        print(f"归档快照: {archive_path}")
    print("\n下一步：给每条填 manual_score（0/1），负样本与语义正确性需人工判断")


if __name__ == "__main__":
    main()
