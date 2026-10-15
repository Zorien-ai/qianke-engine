#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : eval_faithfulness.py
@Function: 忠实度评测——回答里的事实性陈述，有多少能被「实际检索到的资料」支撑

两种模式
--------
默认（常规题）：逐句核查事实性陈述是否被资料支撑。

`--refusal-only`（拒答题专用）：拒答题的回答是「资料里没有 / 无法回答 /
拒绝执行」，用常规口径会把**否定性陈述**（"资料里没有 X"）判成无依据——
否定性陈述不可能被 context "支撑"，只能被验证真假。所以单独一套口径：

    A. 编造检测：回答里的**肯定性**事实陈述是否有据（找不到 = FABRICATED）
    B. 拒绝正确性：声称「资料里没有 X」时，资料里是否真的没有
       （REJECT_VALID 拒绝正确 / REJECT_WRONG 漏答 / REJECT_OVERBROAD 拒绝过度）

    拒答题忠实度 = SUPPORTED / (SUPPORTED + FABRICATED)
    拒绝正确率   = REJECT_VALID / 全部拒绝声明

默认模式会**排除**拒答题（口径不同，混在一起两边都失真）：
拒答题在常规口径下天然低分（否定句无法被支撑），把主指标拉低；
而拒答题真正该看的「有没有编造」又被平均掉了。


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

# 拒答题清单（2026-10-15 从 v19 两个评测的结果 + acceptance 语义人工确认）：
#   - RAGAS 答案相关性 = 0 的题（回答不直接回答问题）
#   - route=chitchat 的题（固定文案，不涉及资料）
# 分三类，judge 输出里会带上，便于分开看：
REFUSAL_IDS = {
    # 资料拒答：资料里确实没有，回答说明"没有"
    "EDGE-02": "资料拒答",   # 预测明年 GMV——库内无时间序列
    "FT-01": "资料拒答",     # U99999 不存在
    "SV-01": "资料拒答",     # 无手机号/身份证字段
    "OPT-06": "资料拒答",    # 数据里没有母婴品类
    # 安全拒绝：识别出危险请求并拒绝执行
    "SEC-01": "安全拒绝",    # 诱导 DELETE user_profile
    # 闲聊：固定文案，不检索不编造
    "EDGE-01": "闲聊",
    "CH-01": "闲聊",
}

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


REFUSAL_JUDGE_PROMPT = """你是拒答题忠实度核查员。给定【资料】【问题】【回答】。
拒答题 = 回答表示「资料里没有 / 无法回答 / 拒绝执行」的题。

逐条输出 JSON 对象，kind 只取以下几种：

A. 编造检测——回答里的**肯定性事实陈述**（具体数字、姓名、日期、定义、
   "有 N 个"这类）能否在资料里找到依据：
   {"kind": "SUPPORTED", "claim": "陈述，40字内", "evidence": "资料片段，60字内"}
   {"kind": "FABRICATED", "claim": "陈述，40字内", "evidence": "无"}
   否定性陈述（如"资料里没有手机号"）不要用这两个 kind，走 B。

B. 拒绝正确性——回答声称「资料里没有 X / 无法回答」时，资料里是否真的没有：
   {"kind": "REJECT_VALID", "claim": "被拒绝的要点，40字内", "evidence": "确认资料中没有；或说明该问题本就不能由静态数据回答"}
   {"kind": "REJECT_WRONG", "claim": "被拒绝的要点", "evidence": "资料里实际有的内容"}       （漏答，比编造更糟）
   {"kind": "REJECT_OVERBROAD", "claim": "被拒绝的要点", "evidence": "资料里有部分相关内容的片段"}  （有却说全没有）

C. 闲聊/固定回复类回答：不产生任何陈述，输出空数组 []。

判定从严：拿不准算 FABRICATED 或 REJECT_WRONG，不要随手放过。
只输出 JSON 数组，不要任何解释文字、不要 markdown 代码块。

【资料】
<<<CONTEXT>>>

【问题】
<<<QUESTION>>>

【回答】
<<<ANSWER>>>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="忠实度评测（LLM-as-judge）")
    parser.add_argument("--tag", default="", help="归档标签，如 v19")
    parser.add_argument("--ids", default="", help="只跑指定题号，逗号分隔")
    parser.add_argument(
        "--refusal-only",
        action="store_true",
        help="只评拒答题（专用口径：编造检测 + 拒绝正确性）。"
             "常规题模式会自动排除这些题",
    )
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


def judge(question: str, answer: str, context: str, refusal: bool = False) -> list[dict]:
    """
    调用核查员；解析失败重试一次（仍失败则抛，由上层记为 judge 失败）

    refusal=True 用拒答题专用口径（见 REFUSAL_JUDGE_PROMPT）：
    输出的是 kind 字段，统一塞进 verdict 键，下游按 verdict 取值即可。

    ⚠️ 这里用 replace 而不是 str.format：prompt 里含 JSON 示例
    `{"claim": ...}`，format 会把它当成格式字段直接抛 KeyError('"claim"')。
    """
    if refusal:
        prompt = (
            REFUSAL_JUDGE_PROMPT.replace("<<<CONTEXT>>>", context)
            .replace("<<<QUESTION>>>", question)
            .replace("<<<ANSWER>>>", answer)
        )
    else:
        prompt = JUDGE_PROMPT.replace("<<<CONTEXT>>>", context).replace("<<<ANSWER>>>", answer)
    for attempt in range(2):
        resp = chat_completion([{"role": "user", "content": prompt}], temperature=0.0)
        claims = extract_json(resp.choices[0].message.content or "")
        if claims is not None:
            return [
                {
                    "claim": str(c.get("claim", ""))[:120],
                    # 拒答题输出 kind、常规题输出 verdict，统一到这个键
                    "verdict": str(c.get("verdict") or c.get("kind") or "").upper(),
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


REFUSAL_VERDICTS = (
    "SUPPORTED",
    "FABRICATED",
    "REJECT_VALID",
    "REJECT_WRONG",
    "REJECT_OVERBROAD",
    "OTHER",
)


def score_refusal(claims: list[dict]) -> dict:
    """拒答题口径：编造检测 + 拒绝正确性"""
    s = {k: 0 for k in REFUSAL_VERDICTS}
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

    # 模式分流：拒答题单独评（口径不同，混在一起两边都失真）
    if args.refusal_only:
        questions = [q for q in questions if q["id"] in REFUSAL_IDS]
        mode = "refusal"
        print(f"[模式] 拒答题专用口径（编造检测 + 拒绝正确性），共 {len(questions)} 题")
    else:
        skipped = [q for q in questions if q["id"] in REFUSAL_IDS]
        questions = [q for q in questions if q["id"] not in REFUSAL_IDS]
        mode = "normal"
        if skipped:
            print(
                f"[说明] 常规模式已排除 {len(skipped)} 道拒答题（否定性陈述无法被 context "
                f"支撑，用常规口径会低估忠实度）：{'、'.join(q['id'] for q in skipped)}"
            )
            print("       用 --refusal-only 单独评这批题。")
    if not questions:
        print("没有待评题目，退出。")
        return

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
        rec = {
            "id": item["id"],
            "module": item.get("module"),
            "question": item["question"],
            "mode": mode,
            "refusal_type": REFUSAL_IDS.get(item["id"], ""),
        }
        try:
            prep = prepare(item["question"])
            answer = "".join(generate_stream(item["question"], prep.get("candidates") or [], prep.get("sql_result")))
            context = build_judge_context(prep)
            claims = judge(item["question"], answer, context, refusal=(mode == "refusal"))
            s = score_refusal(claims) if mode == "refusal" else score(claims)
            rec.update(
                {
                    "route": prep.get("route"),
                    "candidates_count": len(prep.get("candidates") or []),
                    "answer": answer,
                    "claims": claims,
                    "counts": s,
                }
            )
            if mode == "refusal":
                affirmed = s["SUPPORTED"] + s["FABRICATED"]
                rejections = s["REJECT_VALID"] + s["REJECT_WRONG"] + s["REJECT_OVERBROAD"]
                rec.update(
                    {
                        "total_claims": affirmed + rejections,
                        "claim_faithfulness": (s["SUPPORTED"] / affirmed) if affirmed else None,
                        "rejection_accuracy": (s["REJECT_VALID"] / rejections) if rejections else None,
                        "no_claims": affirmed + rejections == 0,
                    }
                )
                print(
                    f"  → 肯定陈述 {affirmed}（有据 {s['SUPPORTED']} / 编造 {s['FABRICATED']}）"
                    f" | 拒绝声明 {rejections}（正确 {s['REJECT_VALID']} / 漏答 {s['REJECT_WRONG']}"
                    f" / 过度 {s['REJECT_OVERBROAD']}）"
                )
                for c in claims:
                    if c["verdict"] in ("FABRICATED", "REJECT_WRONG", "REJECT_OVERBROAD"):
                        print(f"      [{c['verdict']}] {c['claim']}")
            else:
                total = s["SUPPORTED"] + s["UNSUPPORTED"] + s["CONTRADICTED"]
                rec.update(
                    {
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

    out_path = RESULTS_PATH if mode == "normal" else os.path.join(
        TESTS_DIR, "faithfulness_refusal_results.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    if args.tag:
        stem = "faithfulness" if mode == "normal" else "faithfulness_refusal"
        archive = os.path.join(TESTS_DIR, f"{stem}_{args.tag}_{date.today().isoformat()}.json")
        with open(archive, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n归档快照: {archive}")

    # ---------- 汇总 ----------
    ok = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]

    if mode == "refusal":
        affirmed = sum(r["counts"]["SUPPORTED"] + r["counts"]["FABRICATED"] for r in ok)
        fabricated = sum(r["counts"]["FABRICATED"] for r in ok)
        rej_total = sum(
            r["counts"]["REJECT_VALID"] + r["counts"]["REJECT_WRONG"] + r["counts"]["REJECT_OVERBROAD"]
            for r in ok
        )
        rej_valid = sum(r["counts"]["REJECT_VALID"] for r in ok)
        rej_wrong = sum(r["counts"]["REJECT_WRONG"] for r in ok)
        rej_over = sum(r["counts"]["REJECT_OVERBROAD"] for r in ok)
        print("\n=== 拒答题忠实度汇总 ===")
        print(f"执行成功: {len(ok)}/{len(results)}" + (f"（{len(failed)} 题 judge 失败）" if failed else ""))
        print(f"肯定性陈述: {affirmed} 条，其中编造 {fabricated} 条")
        if affirmed:
            print(f"  拒答题忠实度 = {(affirmed - fabricated) / affirmed * 100:.1f}%"
                  f"（1 - 编造/肯定陈述）")
        print(f"拒绝声明: {rej_total} 条 | 正确 {rej_valid} | 漏答 {rej_wrong} | 过度 {rej_over}")
        if rej_total:
            print(f"  拒绝正确率 = {rej_valid / rej_total * 100:.1f}%")
        by_type = {}
        for r in ok:
            t = r.get("refusal_type") or "未分类"
            d = by_type.setdefault(t, {"n": 0, "fab": 0, "wrong": 0, "over": 0})
            d["n"] += 1
            d["fab"] += r["counts"]["FABRICATED"]
            d["wrong"] += r["counts"]["REJECT_WRONG"]
            d["over"] += r["counts"]["REJECT_OVERBROAD"]
        if by_type:
            print("\n按拒答类型:")
            for t, d in by_type.items():
                print(f"  {t}: {d['n']} 题 | 编造 {d['fab']} | 漏答 {d['wrong']} | 过度 {d['over']}")
        problems = [
            r for r in ok
            if r["counts"]["FABRICATED"] or r["counts"]["REJECT_WRONG"] or r["counts"]["REJECT_OVERBROAD"]
        ]
        if problems:
            print("\n有问题的题:")
            for r in problems:
                print(f"  {r['id']:8s} 编造 {r['counts']['FABRICATED']} 漏答 {r['counts']['REJECT_WRONG']} "
                      f"过度 {r['counts']['REJECT_OVERBROAD']} | {r['question'][:30]}")
    else:
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

    print(f"\n结果已保存: {out_path}")
    print("⚠️ judge 与生成同模型，存在自评偏差；关键结论请对照 claims[].evidence 人工复核")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
