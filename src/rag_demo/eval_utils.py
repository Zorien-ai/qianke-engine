# -*- coding: utf-8 -*-
"""离线评测（LLM-as-a-Judge）的纯函数工具。

把「裁判 prompt / JSON 解析 / 来源召回 / 指标聚合 / Markdown 报告」放在这里，
`scripts/run_eval.py` 只负责跑批与 I/O，这样核心口径可以被 pytest 单测覆盖。

评测口径：
  - 每道题的得分只来自裁判模型（0/1），不做字符串匹配；
  - `expect_sources` 与 `actual_sources` 做精确字符串交集，得到来源召回率；
  - 通过率 = 裁判判 1 的题数 / 成功判定的题数（裁判异常单独统计，不计入分母）。
"""
from __future__ import annotations

import json
import re

JUDGE_SYSTEM_PROMPT = """你是一个严格的 AI 评测员。请根据用户问题、系统回答、以及预期验收标准（acceptance），判断该回答是否合格。

要求：
1. 只按 acceptance 判断是否合格，不要因为回答更长或更礼貌而加分。
2. 如果 acceptance 要求「拒答」「说明数据缺失」「不编造」，而模型给出了具体数字、用户明细或事实性结论，则直接判 0 分。
3. 如果回答与问题无关、答非所问、把 demo/示例数据当成真实结论，或遗漏 acceptance 的关键点，判 0 分。
4. 回答包含 acceptance 要求的关键信息且没有编造，判 1 分。
5. 只输出 JSON，不要输出 Markdown 代码块、解释或多余文字。格式：
{"score": 1, "reason": "理由"} 或 {"score": 0, "reason": "理由"}
"""


def build_judge_messages(item: dict, answer: str) -> list[dict]:
    """构造裁判消息：system 严格评测员 + user 三要素。"""
    acceptance = str(item.get("acceptance") or "").strip()
    question = str(item.get("question") or "").strip()
    content = (
        f"【用户问题】\n{question}\n\n"
        f"【系统回答】\n{(answer or '').strip()}\n\n"
        f"【预期验收标准（acceptance）】\n{acceptance}\n"
    )
    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _extract_json_object(raw: str) -> str | None:
    """从可能带 ```json 围栏/前后废话的输出里抠出第一个 JSON 对象。"""
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


def parse_judge_json(raw: str) -> dict | None:
    """严格解析裁判 JSON；返回 {'score': 0/1, 'reason': str} 或 None。"""
    candidate = _extract_json_object(raw)
    if not candidate:
        return None
    try:
        data = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    score = data.get("score")
    if isinstance(score, bool):
        return None
    if isinstance(score, str):
        stripped = score.strip()
        if stripped not in {"0", "1"}:
            return None
        score = int(stripped)
    if score not in (0, 1):
        return None
    reason = data.get("reason")
    reason = "" if reason is None else str(reason).strip()
    return {"score": int(score), "reason": reason}


def unique_sources(values) -> list[str]:
    """按出现顺序去重（sources 可能重复引用同一来源）。"""
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def source_recall(expected, actual) -> dict:
    """来源召回：期望来源与返回来源的精确交集。"""
    expected_list = unique_sources(expected)
    actual_list = unique_sources(actual)
    if not expected_list:
        return {
            "expected": [],
            "actual": actual_list,
            "hit": [],
            "missing": [],
            "recall": None,
        }
    expected_set = set(expected_list)
    actual_set = set(actual_list)
    hit = [name for name in expected_list if name in actual_set]
    return {
        "expected": expected_list,
        "actual": actual_list,
        "hit": hit,
        "missing": [name for name in expected_list if name not in actual_set],
        "recall": len(hit) / len(expected_list),
    }


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_results(results: list[dict]) -> dict:
    """聚合总体/分模块通过率与来源召回率。"""
    total = len(results)
    judged = [r for r in results if r.get("score") in (0, 1)]
    passed = [r for r in judged if r.get("score") == 1]
    judge_errors = [r for r in results if r.get("judge_error")]
    answer_errors = [r for r in results if r.get("answer_error")]

    recalls = [r["source_recall"]["recall"] for r in results if r.get("source_recall", {}).get("recall") is not None]
    micro_expected = 0
    micro_hit = 0
    for r in results:
        recall = r.get("source_recall") or {}
        if recall.get("recall") is None:
            continue
        micro_expected += len(recall.get("expected") or [])
        micro_hit += len(recall.get("hit") or [])

    modules: dict[str, dict] = {}
    for r in results:
        name = r.get("module") or "未分类"
        row = modules.setdefault(name, {"total": 0, "judged": 0, "passed": 0, "recalls": []})
        row["total"] += 1
        if r.get("score") in (0, 1):
            row["judged"] += 1
            if r.get("score") == 1:
                row["passed"] += 1
        recall = r.get("source_recall") or {}
        if recall.get("recall") is not None:
            row["recalls"].append(recall["recall"])
    for row in modules.values():
        row["pass_rate"] = row["passed"] / row["judged"] if row["judged"] else None
        row["recall"] = _avg(row.pop("recalls"))

    elapsed = [r.get("elapsed_s") for r in results if isinstance(r.get("elapsed_s"), (int, float))]
    return {
        "total": total,
        "judged": len(judged),
        "passed": len(passed),
        "pass_rate": (len(passed) / len(judged)) if judged else None,
        "coverage": (len(judged) / total) if total else 0.0,
        "judge_errors": len(judge_errors),
        "answer_errors": len(answer_errors),
        "source_recall_avg": _avg(recalls),
        "source_recall_micro": (micro_hit / micro_expected) if micro_expected else None,
        "source_cases": len(recalls),
        "elapsed_avg": _avg(elapsed),
        "elapsed_total": sum(elapsed),
        "modules": modules,
    }


def excerpt(text: str, limit: int = 420) -> str:
    """报告里的回答摘录：压平换行/Markdown 表格，超长截断，保证报告可读。"""
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def render_markdown_report(
    *,
    results: list[dict],
    summary: dict,
    dataset: str,
    judge_model: str,
    questions_path: str,
    started_at: str,
    elapsed_total: float,
) -> str:
    """生成现场可读的 Markdown 报告（总体/分模块/来源召回/失败复盘）。"""
    lines: list[str] = []
    lines.append("# 离线评测报告（LLM-as-a-Judge）")
    lines.append("")
    lines.append(f"- 评测时间：{started_at}")
    lines.append(f"- 数据集：`{dataset}`（固定离线评测库，不经过前端 API）")
    lines.append(f"- 题目文件：`{questions_path}`")
    lines.append(f"- 裁判模型：`{judge_model}`")
    lines.append(f"- 运行命令：`uv run python scripts/run_eval.py`（可加 `--limit` / `--only` 做子集试跑）")
    lines.append(f"- 题目数：**{summary['total']}**；成功判定：{summary['judged']}；"
                 f"裁判异常：{summary['judge_errors']}；回答异常：{summary['answer_errors']}")
    lines.append(f"- 总耗时：{elapsed_total:.1f}s（平均 {summary['elapsed_avg']:.1f}s/题）")
    lines.append("")

    lines.append("## 总体通过率")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 通过率（通过/成功判定） | **{_pct(summary['pass_rate'])}** "
                 f"（{summary['passed']}/{summary['judged']}） |")
    lines.append(f"| 判定覆盖率（成功判定/总题数） | {_pct(summary['coverage'])} |")
    lines.append(f"| 来源召回率（宏平均） | {_pct(summary['source_recall_avg'])}"
                 f"（{summary['source_cases']} 题有期望来源） |")
    lines.append(f"| 来源召回率（微平均：命中/期望） | {_pct(summary['source_recall_micro'])} |")
    lines.append("")

    lines.append("## 分模块通过率")
    lines.append("")
    lines.append("| 模块 | 题数 | 已判定 | 通过 | 通过率 | 来源召回率 |")
    lines.append("|---|---|---|---|---|---|")
    for name in sorted(summary["modules"]):
        row = summary["modules"][name]
        lines.append(f"| {name} | {row['total']} | {row['judged']} | {row['passed']} | "
                     f"{_pct(row['pass_rate'])} | {_pct(row['recall'])} |")
    lines.append("")

    lines.append("## 来源召回明细")
    lines.append("")
    lines.append("| 题号 | 模块 | 期望来源 | 实际来源 | 命中 | 召回率 |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        recall = r.get("source_recall") or {}
        expected = "、".join(recall.get("expected") or []) or "—"
        actual = "、".join(recall.get("actual") or []) or "—"
        hit = "、".join(recall.get("hit") or []) or "—"
        lines.append(f"| {r.get('id')} | {r.get('module')} | {expected} | {actual} | {hit} | "
                     f"{_pct(recall.get('recall'))} |")
    lines.append("")

    failures = [r for r in results if r.get("score") == 0 or r.get("judge_error") or r.get("answer_error")]
    lines.append(f"## 失败案例复盘（{len(failures)} 条）")
    lines.append("")
    if not failures:
        lines.append("本次全部通过，没有 0 分案例。")
        lines.append("")
    for r in failures:
        lines.append(f"### {r.get('id')} · {r.get('module')} · {r.get('question')}")
        lines.append("")
        if r.get("judge_error"):
            lines.append(f"- 裁判异常：{r['judge_error']}")
        if r.get("answer_error"):
            lines.append(f"- 回答异常：{r['answer_error']}")
        if r.get("score") is not None:
            lines.append(f"- 裁判得分：**{r['score']}**")
            lines.append(f"- 裁判理由：{r.get('judge_reason') or '（空）'}")
        recall = r.get("source_recall") or {}
        lines.append(f"- 验收标准：{r.get('acceptance') or '（空）'}")
        lines.append(f"- 期望来源：{'、'.join(recall.get('expected') or []) or '—'}；"
                     f"实际来源：{'、'.join(recall.get('actual') or []) or '—'}")
        lines.append(f"- 路由：`{r.get('route')}`；耗时：{r.get('elapsed_s'):.1f}s")
        lines.append(f"- 回答摘录：{excerpt(r.get('answer') or '')}")
        if r.get("judge_raw"):
            lines.append(f"- 裁判原始输出：`{excerpt(r['judge_raw'], 200)}`")
        lines.append("")

    lines.append("## 评测口径")
    lines.append("")
    lines.append("- 执行链路：直接调用 `rag_demo.pipeline.answer_question`（真实 RAG 检索 + SQL 路由），"
                 "不走前端 HTTP，固定离线数据集。")
    lines.append("- 判定方式：LLM-as-a-Judge，裁判只依据每题的 `acceptance` 判 0/1；"
                 "要求拒答/说明缺失的题若编造数字直接 0 分。")
    lines.append("- 来源召回：`expect_sources` 与回答返回的 `sources` 精确交集 / 期望数；"
                 "无期望来源的题（负样本等）不计入召回率。")
    lines.append("- 通过率分母是「成功判定的题数」；裁判/回答异常单独计数，不混进分母。")
    lines.append("")
    return "\n".join(lines)
