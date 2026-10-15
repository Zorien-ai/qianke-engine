#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : eval_ragas.py
@Function: 用 RAGAS 评测本 RAG 系统的四个核心指标，结果打印并落 CSV

四个指标（RAGAS 官方口径）
--------------------------
1. 忠实度 Faithfulness           回答里的陈述能否被检索上下文支撑（越高越好）—— 只看生成，不看检索
2. 答案相关性 AnswerRelevancy     回答是否切题（对问题直接有用，不跑题、不答非所问）
3. 上下文相关性 ContextPrecision  检索到的上下文里，有多少是真正与问题相关的（噪声比例）
4. 上下文召回率 ContextRecall     参考答案所需的信息，有多少能在检索上下文里找到（漏召回比例）

3 与 4 都需要**参考答案**（reference）。本项目评测集没有标准答案文本，
用 `eval_questions.json` 里人工写的 `acceptance`（验收标准，描述期望答案要点）
作为 reference —— 它能表达「答案该包含什么」，但比标准答案粗。
口径影响已写在下面的「局限」里。

局限（读数字前必须知道）
------------------------
1. **reference 是验收标准而非标准答案**：ContextRecall/Precision 按它判定，
   与「以标准答案为基准」的结果不可直接比较。
2. RAGAS 的 judge 用与生成同一个模型（deepseek-flash），存在自评偏差。
3. 33 题 × 4 指标，每题要拆句、逐条判定，**LLM 调用量大（数百次）**，
   全量跑约 20~40 分钟；先用 --limit 3 验证再全量。
4. SQL 题的「上下文」是检索到的画像文本；SQL 查询结果单独拼一条 context
   一起交给 RAGAS（否则它会认为答案里的数字没有上下文支撑）。

用法：
    python src/rag_demo/tests/eval_ragas.py --limit 3          # 先验证
    python src/rag_demo/tests/eval_ragas.py --tag v19          # 全量 + 归档
    python src/rag_demo/tests/eval_ragas.py --ids MQ-01,FT-01
"""
import argparse
import io
import json
import os
import sys
import time

# 脚本所在目录进 sys.path，保证无论怎么启动都能 import 到同目录的 ragas_compat
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ⚠️ 顺序要求：垫片必须在 import ragas 之前执行
#    （ragas 会 import LangChain 1.x 里已移除的模块，见 ragas_compat 说明）
import ragas_compat  # noqa: E402

ragas_compat.patch_missing_langchain_modules()

from ragas import EvaluationDataset, RunConfig, SingleTurnSample, evaluate  # noqa: E402
from ragas.metrics import (  # noqa: E402
    AnswerRelevancy,
    Faithfulness,
    LLMContextPrecisionWithReference,
    LLMContextRecall,
)

from preflight import check_api  # noqa: E402

from rag_demo.config import BASE_DIR  # noqa: E402
from rag_demo.generation.generator import generate_stream  # noqa: E402
from rag_demo.pipeline import prepare  # noqa: E402

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")
QUESTIONS_PATH = os.path.join(TESTS_DIR, "eval_questions.json")

# 中文显示名 -> 用来在实际结果列里匹配的关键字（不同 ragas 版本列名有差异）
METRIC_SPECS = [
    ("忠实度", ["faithfulness"]),
    ("答案相关性", ["answer_relevancy", "answer_relevance"]),
    ("上下文相关性", ["context_precision"]),
    ("上下文召回率", ["context_recall"]),
]


def find_metric_columns(df) -> dict:
    """把显示名映射到 DataFrame 里的实际列名；匹配不到则记为 None（该指标失败）"""
    found = {}
    for label, keys in METRIC_SPECS:
        col = None
        for c in df.columns:  # 先精确，再模糊
            if c.lower() in keys:
                col = c
                break
        if col is None:
            for c in df.columns:
                if any(k in c.lower() for k in keys):
                    col = c
                    break
        found[label] = col
    return found


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAGAS 四指标评测")
    p.add_argument("--tag", default="", help="归档标签，如 v19")
    p.add_argument("--limit", type=int, default=0, help="只跑前 N 题（先验证用）")
    p.add_argument("--ids", default="", help="只跑指定题号，逗号分隔")
    p.add_argument("--out", default="", help="CSV 输出路径")
    return p.parse_args()


def build_sample(item: dict) -> SingleTurnSample:
    """跑一遍项目链路，拿到 answer 与实际检索到的 contexts"""
    prep = prepare(item["question"])
    candidates = prep.get("candidates") or []
    sql_result = prep.get("sql_result")
    answer = "".join(generate_stream(item["question"], candidates, sql_result))

    contexts = [c["text"] for c in candidates]
    # SQL 题：把结构化结果也作为一条 context —— 否则答案里的数字在 RAGAS
    # 看来毫无上下文支撑，忠实度会被判得很低（这是口径问题，不是模型问题）
    if sql_result and sql_result.get("rows"):
        rows = sql_result["rows"]
        contexts.append(
            "[结构化查询结果]\n执行的查询：%s\n共 %d 行：\n%s"
            % (
                sql_result.get("sql", ""),
                len(rows),
                "\n".join(" | ".join(str(v) for v in r) for r in rows[:20]),
            )
        )

    return SingleTurnSample(
        user_input=item["question"],
        response=answer,
        retrieved_contexts=contexts,
        # 该题人工写的验收标准，作为参考答案的近似（无标准答案）
        reference=item["acceptance"],
    )


def main() -> None:
    args = parse_args()
    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        questions = json.load(f)
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        questions = [q for q in questions if q["id"] in want]
    if args.limit:
        questions = questions[: args.limit]

    print(f"[RAGAS] 待评 {len(questions)} 题 · 4 指标（忠实度/答案相关性/上下文相关性/上下文召回率）")

    # 预检：LLM API 不通就不要启动。本脚本全量约 20 分钟，
    # 且 ragas 的 raise_exceptions=False 会把失败样本静默记成 NaN——
    # API 故障期间跑完只会得到一堆空值，白等一轮（2026-10-14 实测踩过）
    if not check_api():
        print("LLM API 当前不可用，RAGAS 评测中止。")
        sys.exit(2)

    # ---------- 1) 跑项目链路，收集 question / answer / contexts / reference ----------
    samples, meta = [], []
    for i, item in enumerate(questions, 1):
        t0 = time.time()
        print(f"[{i}/{len(questions)}] {item['id']} 生成中...", flush=True)
        try:
            s = build_sample(item)
            samples.append(s)
            meta.append(
                {
                    "id": item["id"],
                    "module": item.get("module"),
                    "question": item["question"],
                    "answer": s.response,
                    "contexts_count": len(s.retrieved_contexts),
                    "gen_sec": round(time.time() - t0, 2),
                }
            )
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            meta.append({"id": item["id"], "question": item["question"], "error": str(e)})

    if not samples:
        print("没有可用样本，退出")
        return

    # ---------- 2) RAGAS 评测 ----------
    print(f"\n[RAGAS] 开始评测 {len(samples)} 题（每题多次 LLM 调用，请耐心）...")
    t0 = time.time()
    dataset = EvaluationDataset(samples=samples)
    result = evaluate(
        dataset=dataset,
        metrics=[
            Faithfulness(),
            # strictness 默认 3：ragas 会用 n=3 请求 LLM 生成多个反向问题再取平均。
            # DeepSeek 只返回 1 条（实测警告 "LLM returned 1 generations instead
            # of requested 3"），多出来的样本会让该指标不稳定，故设为 1。
            AnswerRelevancy(strictness=1),
            LLMContextPrecisionWithReference(),
            LLMContextRecall(),
        ],
        llm=ragas_compat.build_ragas_llm(),
        embeddings=ragas_compat.build_ragas_embeddings(),
        # ⚠️ RunConfig 默认 max_workers=16：ragas 会并发 16 路打 LLM API。
        # DeepSeek 扛不住这个并发（实测 33 题全量跑时大批样本失败，
        # 而 raise_exceptions=False 会把失败样本静默记成 NaN——
        # 表现为「上下文相关性」一半是空的，看着像指标算不出来，
        # 其实是限流）。降到 2 路并发，用时间换正确性。
        run_config=RunConfig(max_workers=2, timeout=180, max_retries=3),
        raise_exceptions=False,
    )
    print(f"[RAGAS] 评测完成，耗时 {time.time() - t0:.1f}s\n")

    df = result.to_pandas()
    col_map = find_metric_columns(df)
    missing = [k for k, v in col_map.items() if v is None]
    if missing:
        print(f"[警告] 这些指标没有产出结果（该次评测失败）：{'、'.join(missing)}")
        print(f"        实际结果列：{list(df.columns)}")

    # ---------- 3) 打印 ----------
    labels = [k for k, v in col_map.items() if v is not None]
    print("=== 逐题得分 ===")
    header = f"{'ID':<9}" + "".join(f"{k:>14}" for k in labels)
    print(header)
    print("-" * len(header))
    for i, row in df.iterrows():
        qid = meta[i]["id"] if i < len(meta) else "?"
        cells = ""
        for label in labels:
            v = row[col_map[label]]
            cells += f"{(f'{v:.3f}' if v == v else 'nan'):>14}"
        print(f"{qid:<9}{cells}")

    print("\n=== 平均分 ===")
    summary = {}
    for label in labels:
        col = col_map[label]
        n_nan = int(df[col].isna().sum())
        v = df[col].mean()
        summary[label] = None if v != v else round(float(v), 4)
        note = f"  ⚠ {n_nan} 个样本无结果" if n_nan else ""
        print(f"  {label:<12} {(f'{v:.4f}' if v == v else 'nan')}{note}")
    print(f"  {'样本数':<12} {len(df)}")

    # NaN 兜底告警：ragas 的 raise_exceptions=False 会静默吞掉失败样本，
    # 均值照样算得出来——但那是对「部分样本」的均值，不能当全量结论用。
    # 典型成因：LLM API 抖动 / 限流 / 超时（2026-10-14 实测 16 路并发 +
    # API 故障时，33 题里有 25 题上下文相关性为空）。
    total_nan = sum(int(df[col_map[l]].isna().sum()) for l in labels)
    if total_nan:
        print(f"\n⚠️ 共有 {total_nan} 个指标样本无结果（已从均值中剔除）。")
        print("   上述均值只代表有效样本，不能当全量结论。")
        print("   常见原因：LLM API 抖动/限流/超时。确认 API 稳定后重跑。")

    # ---------- 4) 落 CSV ----------
    import pandas as pd

    out_rows = []
    for i, row in df.iterrows():
        rec = {
            "id": meta[i]["id"] if i < len(meta) else f"row{i}",
            "module": meta[i].get("module") if i < len(meta) else "",
            "question": row.get("user_input", ""),
            "answer": row.get("response", ""),
            "contexts_count": meta[i].get("contexts_count") if i < len(meta) else "",
        }
        for label in labels:
            rec[label] = row[col_map[label]]
        out_rows.append(rec)

    out_df = pd.DataFrame(out_rows)
    # 汇总行：便于在 Excel 里直接看到平均值
    avg_row = {"id": "AVERAGE", "module": "", "question": "", "answer": "", "contexts_count": ""}
    for label in labels:
        avg_row[label] = out_df[label].mean()
    out_df = pd.concat([out_df, pd.DataFrame([avg_row])], ignore_index=True)

    csv_path = args.out or os.path.join(
        TESTS_DIR, f"ragas_results{'_' + args.tag if args.tag else ''}.csv"
    )
    out_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV 已保存: {csv_path}")

    # 原始结果 JSON（含 RAGAS 明细，便于复查判定）另存一份
    raw_path = os.path.splitext(csv_path)[0] + "_raw.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": summary,
                "n": len(df),
                "rows": out_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"明细已保存: {raw_path}")
    print("\n⚠️ reference 用的是评测集的 acceptance（验收标准），非标准答案；")
    print("   judge 与生成同模型，存在自评偏差——数字请结合口径解读。")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
