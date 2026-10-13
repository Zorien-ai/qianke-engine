import argparse
import os
import json
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


def run_one(item: dict) -> dict:
    q = item["question"]
    t0 = time.time()

    # 走统一问答入口（含意图路由：聚合/统计类问题会走 Text2SQL）
    result = answer_question(q)
    elapsed = time.time() - t0

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
        "elapsed_sec": round(elapsed, 2),
        "acceptance": item["acceptance"],
        "manual_score": None,  # 人工填 0/1
        "note": ""
    }


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
    print(f"共 {len(questions)} 条评测问题\n")
    results = []
    for i, item in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {item['id']} | {item['question']}")
        try:
            r = run_one(item)
            evaluate_result(r)
            results.append(r)
            print(
                f"  → route={r['route']} | passed={r['passed']} "
                f"| 来源={r['actual_sources']} | 耗时={r['elapsed_sec']}s"
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
