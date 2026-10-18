#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线评测流水线（Offline Eval Pipeline）

用真实 RAG/SQL 链路跑黄金测试集，再用 LLM-as-a-Judge 按 `acceptance` 判分，
最后产出 Markdown 报告（默认 tests/eval_report.md）。

用法（项目根目录）：
    # 小规模试跑（只跑前 3 题，报告/原始结果写到 trial 文件，避免覆盖正式报告）
    uv run python run_eval.py --limit 3 --report tests/eval_report_trial.md --results tests/eval_results_trial.json

    # 全量
    uv run python run_eval.py

    # 只跑指定题
    uv run python run_eval.py --only OPT-01,EDGE-01

环境变量：
    DEEPSEEK_API_KEY    必需（裁判与回答生成共用；Windows 下会尝试从用户环境变量补齐）
    DEEPSEEK_BASE_URL   可选，默认 https://api.deepseek.com/v1
    DEEPSEEK_MODEL      可选，回答生成用的模型（由 generator 读取）
    EVAL_JUDGE_MODEL    可选，裁判模型，默认 deepseek-chat
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = ROOT / "src" / "rag_demo" / "tests" / "eval_questions.json"
DEFAULT_REPORT = ROOT / "tests" / "eval_report.md"
DEFAULT_RESULTS = ROOT / "tests" / "eval_results_llm.json"


def _bootstrap_windows_env() -> None:
    """离线脚本直接跑时，补上当前进程缺失的 DeepSeek 环境变量。

    服务启动脚本会把用户级环境变量注入进程；离线评测/脚本同样需要。
    这里只在 Windows 下、且变量确实缺失时，从用户环境变量补齐（不读文件、不落盘）。
    """
    if os.getenv("DEEPSEEK_API_KEY"):
        return
    if sys.platform != "win32":
        return
    try:
        import winreg

        wanted = {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if name in wanted and value and not os.getenv(name):
                    os.environ[name] = str(value)
    except OSError:
        return


_bootstrap_windows_env()

# 必须在补齐环境变量之后再 import：generator 在模块加载时创建 OpenAI client。
from rag_demo.config import BASE_DIR  # noqa: E402
from rag_demo.db.connection import get_conn, reset_dataset, use_dataset  # noqa: E402
from rag_demo.eval_utils import (  # noqa: E402
    build_judge_messages,
    excerpt,
    parse_judge_json,
    render_markdown_report,
    source_recall,
    summarize_results,
    unique_sources,
)
from rag_demo.generation.generator import API_KEY, BASE_URL, MODEL as ANSWER_MODEL  # noqa: E402
from rag_demo.pipeline import answer_question  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="离线评测：真实 RAG/SQL 链路 + LLM-as-a-Judge")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="评测集 JSON 路径")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Markdown 报告输出路径")
    parser.add_argument("--results", default=str(DEFAULT_RESULTS), help="原始结果 JSON 输出路径")
    parser.add_argument("--dataset", default="demo", help="固定评测数据集（默认 demo）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（试跑用）")
    parser.add_argument("--only", default=None, help="只跑指定题号，逗号分隔，如 OPT-01,EDGE-01")
    parser.add_argument(
        "--judge-model",
        default=os.getenv("EVAL_JUDGE_MODEL", "deepseek-chat"),
        help="裁判模型（默认 deepseek-chat，可用 EVAL_JUDGE_MODEL 覆盖）",
    )
    parser.add_argument("--judge-retries", type=int, default=3, help="裁判 JSON 解析失败时的重试次数")
    return parser.parse_args()


def load_questions(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"评测集不存在：{path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list) or not data:
        sys.exit(f"评测集格式不对（应为非空数组）：{path}")
    required = {"id", "question", "acceptance"}
    for item in data:
        missing = required - set(item)
        if missing:
            sys.exit(f"题目 {item.get('id', '?')} 缺字段：{sorted(missing)}")
    return data


def select_questions(questions: list[dict], args: argparse.Namespace) -> list[dict]:
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        selected = [q for q in questions if q.get("id") in wanted]
        missing = wanted - {q.get("id") for q in selected}
        if missing:
            sys.exit(f"--only 里有不存在的题号：{sorted(missing)}")
        return selected
    if args.limit is not None:
        return questions[: max(0, args.limit)]
    return questions


def check_dataset(dataset: str) -> None:
    """确认评测数据集存在且有数据；空库直接失败，避免 33 题全部空跑。"""
    conn = get_conn(dataset)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
        profiles = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wiki_vectors")
        chunks = cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        cur.close()
        sys.exit(f"评测数据集 `{dataset}` 不可用：{exc}")
    finally:
        try:
            conn.rollback()
            cur.close()
        except Exception:  # noqa: BLE001
            pass
    if profiles == 0 and chunks == 0:
        sys.exit(
            f"评测数据集 `{dataset}` 是空的（profiles=0, chunks=0）。"
            "请先导入数据，或改用有数据的数据集（demo 默认即可）。"
        )
    print(f"[准备] 数据集 {dataset}: profiles={profiles}, chunks={chunks}", flush=True)


def make_judge_client():
    if not API_KEY:
        sys.exit(
            "缺少 DEEPSEEK_API_KEY：请先设置环境变量，"
            "或确保 Windows 用户环境变量里有（账户与生成的回答共用同一把 key）。"
        )
    from openai import OpenAI

    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


def judge_answer(client, judge_model: str, item: dict, answer: str, retries: int) -> dict:
    """调用裁判模型并严格解析 JSON；失败时记录 judge_error，不伪造分数。"""
    messages = build_judge_messages(item, answer)
    last_raw = ""
    last_error = ""
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = client.chat.completions.create(
                model=judge_model,
                messages=messages if attempt == 1 else messages + [
                    {
                        "role": "user",
                        "content": "上次输出不是合法 JSON。请重新只输出一个 JSON 对象："
                        '{"score": 0 或 1, "reason": "理由"}',
                    }
                ],
                temperature=0,
                max_tokens=400,
            )
            last_raw = (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2.0 * attempt, 6.0))
            continue
        parsed = parse_judge_json(last_raw)
        if parsed is not None:
            return {
                "score": parsed["score"],
                "judge_reason": parsed["reason"],
                "judge_raw": last_raw,
                "judge_error": None,
            }
        last_error = f"裁判输出不是合法 JSON：{last_raw[:200]}"
    return {"score": None, "judge_reason": "", "judge_raw": last_raw, "judge_error": last_error}


def run(args: argparse.Namespace) -> int:
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t_all = time.time()
    questions = select_questions(load_questions(Path(args.questions)), args)
    print(
        f"[开始] 共 {len(questions)} 题 | 数据集={args.dataset} | 回答模型={ANSWER_MODEL} "
        f"| 裁判模型={args.judge_model} | 报告={args.report}",
        flush=True,
    )
    check_dataset(args.dataset)
    judge_client = make_judge_client()

    token = use_dataset(args.dataset)
    results: list[dict] = []
    try:
        for index, item in enumerate(questions, 1):
            qid = item.get("id")
            question = item.get("question", "")
            print(f"[{index:02d}/{len(questions)}] {qid} {question}", flush=True)
            t0 = time.time()
            result: dict = {}
            answer_error = None
            try:
                result = answer_question(question, use_cache=False)
            except Exception as exc:  # noqa: BLE001
                answer_error = f"{type(exc).__name__}: {exc}"
            elapsed = time.time() - t0
            answer = (result.get("answer") or "") if isinstance(result, dict) else ""
            actual_sources = unique_sources(
                (src or {}).get("source") for src in (result.get("sources") or [])
            )
            recall = source_recall(item.get("expect_sources") or [], actual_sources)

            if answer_error or not answer.strip():
                judge = {
                    "score": 0,
                    "judge_reason": "系统没有产出回答，按不合格处理。",
                    "judge_raw": "",
                    "judge_error": None,
                }
                if answer_error:
                    judge["judge_reason"] = f"回答异常：{answer_error}"
            else:
                judge = judge_answer(judge_client, args.judge_model, item, answer, args.judge_retries)

            record = {
                **{key: item.get(key) for key in ("id", "module", "question", "type", "acceptance", "expect_wiki", "expect_sources")},
                "answer": answer,
                "actual_sources": actual_sources,
                "source_recall": recall,
                "route": result.get("route"),
                "sql": result.get("sql"),
                "rows_count": result.get("rows_count"),
                "elapsed_s": round(elapsed, 2),
                "score": judge.get("score"),
                "judge_reason": judge.get("judge_reason"),
                "judge_raw": judge.get("judge_raw"),
                "judge_error": judge.get("judge_error"),
                "answer_error": answer_error,
            }
            results.append(record)
            score_text = "?" if record["score"] is None else str(record["score"])
            recall_text = "—" if recall["recall"] is None else f"{recall['recall'] * 100:.0f}%"
            print(
                f"    → score={score_text} | 来源召回={recall_text} | {elapsed:.1f}s"
                + (f" | 裁判失败：{record['judge_error'][:80]}" if record["judge_error"] else ""),
                flush=True,
            )
    finally:
        reset_dataset(token)

    summary = summarize_results(results)
    elapsed_total = time.time() - t_all
    questions_path = Path(args.questions)
    try:
        questions_display = str(questions_path.resolve().relative_to(ROOT))
    except ValueError:
        questions_display = str(questions_path)
    report_text = render_markdown_report(
        results=results,
        summary=summary,
        dataset=args.dataset,
        judge_model=args.judge_model,
        questions_path=questions_display,
        started_at=started_at,
        elapsed_total=elapsed_total,
    )

    report_path = Path(args.report)
    results_path = Path(args.results)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    payload = {
        "started_at": started_at,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": args.dataset,
        "answer_model": ANSWER_MODEL,
        "judge_model": args.judge_model,
        "questions_path": str(Path(args.questions)),
        "elapsed_total_s": round(elapsed_total, 2),
        "summary": summary,
        "results": results,
    }
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ 汇总 ================")
    if summary["pass_rate"] is None:
        print("没有可判定的题目（裁判/回答异常），请检查日志。")
    else:
        print(
            f"通过率: {summary['passed']}/{summary['judged']} = {summary['pass_rate'] * 100:.1f}% "
            f"| 覆盖率 {summary['coverage'] * 100:.1f}% "
            f"| 来源召回(宏) {summary['source_recall_avg'] * 100:.1f}% "
            f"| 来源召回(微) {(summary['source_recall_micro'] or 0) * 100:.1f}%"
        )
    for name in sorted(summary["modules"]):
        row = summary["modules"][name]
        rate = "—" if row["pass_rate"] is None else f"{row['pass_rate'] * 100:.1f}%"
        print(f"  - {name}: {row['passed']}/{row['judged']} = {rate}")
    failed = [r["id"] for r in results if r.get("score") == 0 or r.get("judge_error") or r.get("answer_error")]
    print(f"失败/异常题目: {', '.join(failed) if failed else '无'}")
    print(f"报告: {report_path}")
    print(f"原始结果: {results_path}")
    print(f"总耗时: {elapsed_total:.1f}s")
    return 0 if summary["pass_rate"] is not None else 1


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(run(args))
    except KeyboardInterrupt:
        print("\n[中断] 评测被手动停止。", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
