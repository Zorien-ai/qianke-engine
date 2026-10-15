#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : eval_faithfulness.py
@Function: 忠实度评测——回答里的事实性陈述，有多少能被「实际检索到的资料」支撑

为什么需要这个指标
------------------
`run_eval.py` 的自动判定只回答「引用的文件对不对」（来源命中率），
**不回答「说的内容有没有依据」**。两个场景它都看不见：

    1. 答案里引用了正确的来源，但数字/事实是编的  -> 来源命中，忠实度不合格
    2. 答案内容全对，但没有 [来源N] 标记          -> 忠实度高，引用格式差

忠实度 = 事实性陈述被资料支撑的比例。RAG 系统最该盯的指标就是它——
「找不到就说找不到」的正确拒答，忠实度是 100%，哪怕通过率低。

怎么测
------
LLM-as-judge：把【资料原文 + 结构化查询结果 + 回答】一起交给一个
严格的核查员，让它把回答拆成事实性陈述并逐条判定：

    SUPPORTED    资料里能找到对应信息（数字需完全一致）
    UNSUPPORTED  资料里找不到（模型自己补的、常识、或未标注的推断）
    CONTRADICTED 与资料冲突

指标口径：
    陈述级忠实度 = SUPPORTED / 全部陈述
    题级完全忠实 = 无 UNSUPPORTED 且无 CONTRADICTED 的题数 / 总题数

⚠️ 已知局限（结论别过度外推）
-----------------------------
1. **judge 与生成用的是同一个模型**（deepseek-flash），存在自评偏差——
   模型倾向于认可自己生成的表述。本报告附上每条判定的证据片段，
   关键结论应对照人工复核，或换一个更强的模型做 judge 再测一次。
2. 陈述切分由 LLM 完成，边界模糊（一句里既有事实又有推断时会拆错）。
3. 只评「回答 vs 检索到的资料」，不评「资料本身对不对」——
   资料错了但忠实地引用它，本指标仍算 SUPPORTED。
4. 拒答题（明确说"资料里没有"）不产生事实性陈述，忠实度按 100% 计，
   但它回答不了任何问题，所以**必须与通过率一起看**，不能单看。

用法：
    python src/rag_demo/tests/eval_faithfulness.py --tag v19
    python src/rag_demo/tests/eval_faithfulness.py --ids MQ-01,FT-01
"""
import argparse
import io
import json
import os
import re
import sys
import time
import traceback
from datetime import date

# tests 目录进 sys.path，保证能 import 同目录的 preflight
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)

from preflight import check_api  # noqa: E402

from rag_demo.config import BASE_DIR, DEVICE, DTYPE  # noqa: E402
from rag_demo.generation.generator import chat_completion, generate_stream  # noqa: E402
from rag_demo.pipeline import prepare  # noqa: E402
from rag_demo.retrieval.hybrid_retriever import hybrid_search  # noqa: E402

QUESTIONS_PATH = os.path.join(TESTS_DIR, "eval_questions.json")
RESULTS_PATH = os.path.join(TESTS_DIR, "faithfulness_results.json")

JUDGE_PROMPT = """你是严格的事实核查员。给定【资料】和【回答】，检查回答里的事实性陈述是否被资料支撑。

判定标准（严格执行）：
- SUPPORTED：资料里能找到对应信息。**数字必须完全一致**（四舍五入到整数视为一致；数值差异超 1% 算 UNSUPPORTED）。
- UNSUPPORTED：资料里找不到对应依据——包括模型补充的常识、自己推算的结论、未标注的推断。
- CONTRADICTED：与资料直接冲突。
- 明确标注为推断/推测的表述（如"大概率属于""推断他偏好"）算 SUPPORTED；未标注的推断算 UNSUPPORTED。
- 纯建议、提问、引导语不计入陈述，不要为它们编造判定。
- 只输出 JSON 数组，不要任何解释文字、不要 markdown 代码块。

输出格式：
[{"claim": "陈述原文，40字以内", "verdict": "SUPPORTED", "evidence": "支撑它的资料片段原文，60字以内；无则写'无'"}]

【资料】
<<<CONTEXT>>>

【回答】
<<<ANSWER>>>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="忠实度评测（LLM-as-judge）")
    parser.add_argument("--tag", default="", help="归档标签，如 v19")
    parser.add_argument("--ids", default="", help="只跑指定题号，逗号分隔")
    return parser.parse_args()


def build_judge_context(prep: dict) -> str:
    """把实际送进生成阶段的资料拼成核查上下文（与生成时同源，避免拿不到原文）"""
    parts = []
    cands = prep.get("candidates") or []
    if cands:
        lines = ["[检索资料]"]
        for i, c in enumerate(cands, 1):
            lines.append(f"[资料{i}] ({c.get('source', '')})\n{c['text']}")
        parts.append("\n".join(lines))
    sql_result = prep.get("sql_result")
    if sql_result and sql_result.get("rows"):
        rows = sql_result["rows"]
        parts.append(
            "[结构化查询结果]\n执行的查询：%s\n共 %d 行\n%s"
            % (
                sql_result.get("sql", ""),
                len(rows),
                "\n".join(" | ".join(str(v) for v in row) for row in rows[:20]),
            )
        )
    return "\n\n".join(parts) if parts else "（本次没有检索资料）"


def extract_json(text: str):
    """从 LLM 输出里抠出 JSON 数组（容忍代码块包裹、前后废话）"""
    if not text:
        return None
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def judge(question: str, answer: str, context: str) -> list[dict]:
    """
    调用核查员；解析失败重试一次（仍失败则抛，由上层记为 judge 失败）

    ⚠️ 这里用 replace 而不是 str.format：prompt 里含 JSON 示例
    `{"claim": ...}`，format 会把它当成格式字段直接抛 KeyError('"claim"')。
    """
    prompt = JUDGE_PROMPT.replace("<<<CONTEXT>>>", context).replace("<<<ANSWER>>>", answer)
    for attempt in range(2):
        resp = chat_completion([{"role": "user", "content": prompt}], temperature=0.0)
        claims = extract_json(resp.choices[0].message.content or "")
        if claims is not None:
            return [
                {
                    "claim": str(c.get("claim", ""))[:120],
                    "verdict": str(c.get("verdict", "")).upper(),
                    "evidence": str(c.get("evidence", ""))[:200],
                }
                for c in claims
                if isinstance(c, dict)
            ]
        logger_msg = f"[忠实度] judge 输出解析失败，重试 {attempt + 1}/2"
        print(" ", logger_msg)
    raise ValueError("judge 输出无法解析为 JSON")


def score(claims: list[dict]) -> dict:
    s = {"SUPPORTED": 0, "UNSUPPORTED": 0, "CONTRADICTED": 0, "OTHER": 0}
    for c in claims:
        v = c["verdict"]
        s[v if v in s else "OTHER"] += 1
    return s


def main() -> None:
    args = parse_args()
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        questions = json.load(f)
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        questions = [q for q in questions if q["id"] in want]

    # 预检：LLM API 不通就不要启动——跑完只会得到一堆 judge 失败
    # （2026-10-14 实测：API 故障期间首跑 3 题全挂，白等一轮）
    if not check_api():
        print("LLM API 当前不可用，忠实度评测中止。")
        sys.exit(2)

    # 预热 + 自检：模型加载不计入忠实度统计（与 run_eval 一致）
    print(f"[预热] 加载模型与索引（device={DEVICE}, dtype={DTYPE}）...")
    t0 = time.time()
    prepare("高价值用户怎么定义")
    print(f"[预热] 完成，耗时 {time.time() - t0:.1f}s")

    # ⚠️ 自检：检索必须先确认可用，否则会拿着「空资料」去评忠实度——
    #    那样每题都判 100%，数字漂亮但毫无意义（2026-10-14 首次跑就踩了）。
    #
    #    已知触发场景：上一个进程（uvicorn 服务 / 上一轮评测）刚退出就立刻起本脚本，
    #    显存还没释放完，模型加载会出现跨设备精度混用
    #    （expected scalar type Half but found Float），此时向量检索整条路失败。
    #    单独复现脚本跑同样的检索却是好的——所以必须在这里拦，而不是事后猜。
    try:
        probe = hybrid_search("高客单女性用户", top_k=3)
        if not probe:
            raise RuntimeError("hybrid_search 返回空")
        print(f"[自检] 检索可用（命中 {len(probe)} 条）\n")
    except Exception as e:
        print(f"\n[自检失败] 检索不可用：{type(e).__name__}: {e}")
        traceback.print_exc(limit=8)
        print("  忠实度数字必须建立在「检索可用」之上，否则不可信。先解决检索再重跑。")
        sys.exit(2)

    results = []
    for i, item in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {item['id']} | {item['question']}")
        rec = {"id": item["id"], "module": item.get("module"), "question": item["question"]}
        try:
            prep = prepare(item["question"])
            answer = "".join(generate_stream(item["question"], prep.get("candidates") or [], prep.get("sql_result")))
            context = build_judge_context(prep)
            claims = judge(item["question"], answer, context)
            s = score(claims)
            total = s["SUPPORTED"] + s["UNSUPPORTED"] + s["CONTRADICTED"]
            rec.update(
                {
                    "route": prep.get("route"),
                    "candidates_count": len(prep.get("candidates") or []),
                    "answer": answer,
                    "claims": claims,
                    "counts": s,
                    "total_claims": total,
                    # 拒答/闲聊没有事实性陈述，记为无陈述而非 0%
                    "claim_faithfulness": (s["SUPPORTED"] / total) if total else None,
                    "fully_faithful": total > 0 and s["UNSUPPORTED"] == 0 and s["CONTRADICTED"] == 0,
                    "no_claims": total == 0,
                }
            )
            flag = "OK " if rec["fully_faithful"] else "[!]"
            print(
                f"  → {flag} 陈述 {total} 条 | 支持 {s['SUPPORTED']} | 无据 {s['UNSUPPORTED']} "
                f"| 冲突 {s['CONTRADICTED']} | 忠实度 "
                f"{'n/a' if rec['claim_faithfulness'] is None else format(rec['claim_faithfulness'] * 100, '.0f') + '%'}"
            )
            for c in claims:
                if c["verdict"] in ("UNSUPPORTED", "CONTRADICTED"):
                    print(f"      [{c['verdict']}] {c['claim']}")
        except Exception as e:
            rec["error"] = str(e)
            rec["traceback"] = traceback.format_exc(limit=4)
            print(f"  [FAIL] {type(e).__name__}: {e}")
        results.append(rec)

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    if args.tag:
        archive = os.path.join(TESTS_DIR, f"faithfulness_{args.tag}_{date.today().isoformat()}.json")
        with open(archive, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n归档快照: {archive}")

    # ---------- 汇总 ----------
    ok = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]
    with_claims = [r for r in ok if r.get("total_claims")]
    no_claims = [r for r in ok if r.get("no_claims")]
    tot = sum(r["total_claims"] for r in with_claims)
    sup = sum(r["counts"]["SUPPORTED"] for r in with_claims)
    uns = sum(r["counts"]["UNSUPPORTED"] for r in with_claims)
    con = sum(r["counts"]["CONTRADICTED"] for r in with_claims)
    fully = sum(1 for r in ok if r.get("fully_faithful"))

    print("\n=== 忠实度汇总 ===")
    print(f"执行成功: {len(ok)}/{len(results)}" + (f"（{len(failed)} 题 judge 失败）" if failed else ""))
    if tot:
        print(f"陈述总数: {tot}（有陈述题 {len(with_claims)}，无陈述题 {len(no_claims)}）")
        print(f"  支持 SUPPORTED:    {sup:4d}（{sup / tot * 100:.1f}%）")
        print(f"  无据 UNSUPPORTED:  {uns:4d}（{uns / tot * 100:.1f}%）")
        print(f"  冲突 CONTRADICTED: {con:4d}（{con / tot * 100:.1f}%）")
        print(f"\n陈述级忠实度: {sup / tot * 100:.1f}%")
    print(f"题级完全忠实: {fully}/{len(ok)}（{fully / max(len(ok), 1) * 100:.1f}%）")
    if no_claims:
        print(f"  其中 {len(no_claims)} 题未产生事实性陈述（拒答/闲聊），不计入陈述级忠实度")
    bad = sorted(
        (r for r in ok if not r.get("fully_faithful") and r.get("total_claims")),
        key=lambda r: -(r["counts"]["UNSUPPORTED"] + r["counts"]["CONTRADICTED"]),
    )
    if bad:
        print("\n=== 存在无据/冲突陈述的题（按条数排序） ===")
        for r in bad:
            n = r["counts"]["UNSUPPORTED"] + r["counts"]["CONTRADICTED"]
            print(f"  {r['id']:8s} 无据 {r['counts']['UNSUPPORTED']} 冲突 {r['counts']['CONTRADICTED']} | {r['question'][:30]}")
    print(f"\n结果已保存: {RESULTS_PATH}")
    print("⚠️ judge 与生成同模型，存在自评偏差；关键结论请对照 claims[].evidence 人工复核")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
