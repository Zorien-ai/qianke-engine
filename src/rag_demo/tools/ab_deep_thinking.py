#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : ab_deep_thinking.py
@Function: A/B 实验——最后一个 LLM 开/关「深度思考」的代价与收益

要回答的问题
------------
思考模式（reasoning）会让模型先写一段推理再给答案：那段推理**不进答案**，
却照样耗时耗 token（config 里实测：慢 63%、completion 涨 3.4 倍）。
那它值不值？只有**最后一个生成调用**说了算——规划、Text2SQL 那些中间调用
开思考只是白白变慢，答案质量不会因此提高。所以本实验只切开关最后一个调用。

对照条件（关键，别改）
--------------------
每题只跑一次 prepare()，两条臂**用同一份 context**（同一批候选、同一份 SQL 结果），
只切换 generate() 的 deep_thinking。否则「检索这次运气好不好」会和「思考开关」
混在一起，分不清差异来自哪一个。

测什么
------
耗时、completion_tokens（含 reasoning_tokens）、答案字数，
外加忠实度（复用 eval_faithfulness 的判官，同一套口径）。

⚠️ 读数前必须知道的两条局限
--------------------------
1. **judge 与生成是同一个模型**，存在自评偏差（见 eval_faithfulness 的局限说明）。
   所以重点看「同一题两臂的差异」，并配合人工核验，别只看绝对分。
2. **单次采样**（temperature=0.3，n=题数），没有重复轮次。
   同一 prompt 的耗时与措辞波动本来就大，想下强结论要加重复轮次再跑。

用法
----
    uv run python src/rag_demo/tools/ab_deep_thinking.py
    uv run python src/rag_demo/tools/ab_deep_thinking.py --ids OPT-01,OPT-04
"""
import argparse
import json
import logging
import os
import sys
import time

logging.basicConfig(level=logging.WARNING)

from rag_demo.config import BASE_DIR
from rag_demo.generation.generator import generate
from rag_demo.pipeline import prepare

TESTS = os.path.join(BASE_DIR, "src", "rag_demo", "tests")
sys.path.insert(0, TESTS)
from eval_faithfulness import REFUSAL_IDS, build_judge_context, judge, score  # noqa: E402

# 默认题号：覆盖画像+wiki 综合、运营方案、口径、SQL、对比、统计、分群、拒答
DEFAULT_IDS = ["OPT-01", "OPT-04", "DA-01", "DA-04", "MQ-03", "SQ-01", "MD-01", "EDGE-02"]

# 臂名用英文做键、中文做显示：JSON 归档里键名稳定，改文案不会破坏历史结果
ARMS = (("off", "关闭"), ("on", "开启"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="深度思考 A/B（只切最后一个 LLM）")
    p.add_argument("--ids", default="", help=f"题号，逗号分隔，默认 {'/'.join(DEFAULT_IDS)}")
    p.add_argument("--out", default="", help="结果 JSON（默认 tests/thinking_ab_results.json）")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ids = [x.strip() for x in args.ids.split(",") if x.strip()] or DEFAULT_IDS
    out = args.out or os.path.join(TESTS, "thinking_ab_results.json")

    with open(os.path.join(TESTS, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}

    print("[预热] ...")
    prepare("高价值用户怎么定义")
    print("[预热] 完成\n")

    records = []
    for qid in ids:
        item = items.get(qid)
        if not item:
            print(f"{qid}: 评测集里没有这道题，跳过")
            continue
        q = item["question"]
        prep = prepare(q)
        if prep.get("route") != "rag":
            print(f"{qid}: route={prep.get('route')}，跳过")
            continue

        cands, sql = prep["candidates"], prep["sql_result"]
        ctx = build_judge_context(prep)
        refusal = qid in REFUSAL_IDS

        arms = {}
        for key, label in ARMS:
            t0 = time.time()
            r = generate(q, cands, sql_result=sql, deep_thinking=(key == "on"))
            elapsed = time.time() - t0
            claims = judge(q, r["answer"], ctx, refusal=refusal)
            arms[key] = {
                "elapsed": elapsed,
                "answer": r["answer"],
                "usage": r.get("usage", {}),
                "claims": claims,
                "score": None if refusal else score(claims),
            }
            time.sleep(1)   # 两臂之间留一口气，避免把限流抖动算进耗时差

        records.append({"id": qid, "question": q, "refusal": refusal, "arms": arms})

        print("=" * 96)
        print(f"{qid} | {q}")
        for key, label in ARMS:
            a = arms[key]
            u = a["usage"]
            extra = f"（含推理 {u['reasoning_tokens']}）" if u.get("reasoning_tokens") else ""
            if a["score"]:
                s = a["score"]
                denom = s["SUPPORTED"] + s["UNSUPPORTED"] + s["CONTRADICTED"]
                fai = f"{s['SUPPORTED']}/{denom}"
                bad = [c for c in a["claims"] if c["verdict"] in ("UNSUPPORTED", "CONTRADICTED")]
                tail = f" | 问题陈述 {len(bad)}" if bad else ""
            else:
                vs = {}
                for c in a["claims"]:
                    vs[c["verdict"]] = vs.get(c["verdict"], 0) + 1
                fai, bad, tail = "拒答口径 " + str(vs), [], ""
            print(f"  {label} {a['elapsed']:5.1f}s | 答案 {len(a['answer']):4d} 字 | "
                  f"tokens {u.get('completion_tokens', '?')}{extra} | 忠实 {fai}{tail}")
            for c in bad[:3]:
                print(f"        [{c['verdict']}] {c['claim'][:70]}")

    print("\n" + "=" * 96)
    print("汇总（同一批题、同一份 context，只切换最后一个 LLM 的思考开关）")
    print("=" * 96)
    for key, label in ARMS:
        tot_t = sum(r["arms"][key]["elapsed"] for r in records)
        tot_k = sum(r["arms"][key]["usage"].get("completion_tokens", 0) for r in records)
        tot_r = sum(r["arms"][key]["usage"].get("reasoning_tokens", 0) for r in records)
        sup = sum(r["arms"][key]["score"]["SUPPORTED"] for r in records if r["arms"][key]["score"])
        uns = sum(r["arms"][key]["score"]["UNSUPPORTED"] for r in records if r["arms"][key]["score"])
        con = sum(r["arms"][key]["score"]["CONTRADICTED"] for r in records if r["arms"][key]["score"])
        denom = sup + uns + con
        print(f"  {label}  合计 {tot_t:6.1f}s | completion {tot_k:6d} tokens（推理 {tot_r}）| "
              f"忠实度 {sup}/{denom} = {sup / max(1, denom):.1%}")

    print("\n逐题忠实度差异")
    for r in records:
        a, b = r["arms"]["off"]["score"], r["arms"]["on"]["score"]
        if not a or not b:
            continue

        def fai(s):
            d = s["SUPPORTED"] + s["UNSUPPORTED"] + s["CONTRADICTED"]
            return s["SUPPORTED"] / max(1, d)

        fa, fb = fai(a), fai(b)
        verdict = "持平" if abs(fa - fb) < 1e-9 else ("开启更好" if fb > fa else "开启更差")
        print(f"  {r['id']:9s} 关闭 {fa:6.1%} -> 开启 {fb:6.1%}   {verdict}"
              f"   （{r['arms']['off']['elapsed']:.1f}s -> {r['arms']['on']['elapsed']:.1f}s）")

    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"\n完整答案已保存: {out}")


if __name__ == "__main__":
    main()
