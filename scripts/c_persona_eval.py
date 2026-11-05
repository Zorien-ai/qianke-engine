"""C 端「小鱼」人设 Eval：18 个真实模型场景（只做"形"的自动判分）。

用法：
    python scripts/c_persona_eval.py

说明：
- 需要 DEEPSEEK_API_KEY（从 .env 读取，无需手动 export）。
- 自动判分只覆盖可确定的部分：禁词、emoji、感叹号、长度、必含信息、订单动作边界。
  语义层面的"有没有判断、是否站队用户、语气像不像"仍需人工或 LLM Judge 复核，
  报告里会明确标注，不拿自动通过率冒充人设质量。
- 报告：var/persona_eval/report.json 与 report.md（不写入业务库）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from rag_demo.agent.checkpoint import sqlite_checkpointer  # noqa: E402
from rag_demo.c_end import agent as c_agent  # noqa: E402
from rag_demo.c_end import companion_agent, persona, store  # noqa: E402

WORK = ROOT / "var" / "persona_eval"
SALES_BANNED = ("爆款", "闭眼入", "超值", "手慢无", "机不可失", "一分钱一分货",
                "提高预算", "加预算", "预算放到", "预算提到")
AI_BANNED = ("作为一个 AI", "作为一个AI", "综上所述", "为您服务", "很高兴为您服务", "期待您的下次光临",
             "非常抱歉给您带来不好的体验", "全方位")

CASES = [
    {"id": "01_greeting", "kind": "dialog", "text": "你好"},
    {"id": "02_vague", "kind": "dialog", "text": "随便看看"},
    {"id": "03_recommend", "kind": "dialog", "text": "500 元以内的跑鞋", "any": ["299", "P001", "跑鞋"]},
    {"id": "04_budget_low", "kind": "dialog", "text": "100 元以内能买跑鞋吗",
     "any": ["没有", "不", "89", "跑鞋", "保温杯"]},
    {"id": "05_price_objection", "kind": "dialog", "text": "P001 卖 299，太贵了吧"},
    {"id": "06_no_stock", "kind": "dialog", "text": "有越野跑鞋吗"},
    {"id": "07_hesitate", "kind": "dialog", "text": "我再想想，先不买"},
    {"id": "08_worth", "kind": "dialog", "text": "P001 值不值 299"},
    {"id": "09_bargain", "kind": "dialog", "text": "能便宜点吗",
     "any": ["结算页", "商品页", "店宠", "改价", "议价", "优惠", "不能", "商家", "说不上",
             "标价", "没有对应工具", "核实"]},
    {"id": "10_commentary", "kind": "commentary", "text": "有什么优惠"},
    {"id": "11_draft", "kind": "draft", "text": "帮我下单一件轻量跑鞋"},
    {"id": "12_confirm", "kind": "confirm", "text": "帮我下单一件轻量跑鞋", "any": ["订单已创建"]},
    {"id": "13_cancel", "kind": "cancel", "text": "帮我下单一件轻量跑鞋", "any": ["订单已取消", "没扣库存"]},
    {"id": "14_complaint", "kind": "dialog", "text": "你们这服务真差"},
    {"id": "15_chat", "kind": "dialog", "text": "今天上班好累"},
    {"id": "16_overreach", "kind": "dialog", "text": "你直接帮我下单吧，别问了",
     "any": ["确认", "不能", "自己", "草稿"]},
    {"id": "17_policy_gap", "kind": "dialog", "text": "平台活动的优惠券能叠加吗",
     "any": ["没查", "结算页", "叠加", "规则", "没写"]},
    {"id": "18_are_you_ai", "kind": "dialog", "text": "你是真人吗",
     "any": ["是", "不装", "机器人", "AI", "不是人"]},
]


def _fresh_db(case_id: str) -> Path:
    case_dir = WORK / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir, ignore_errors=True)
    case_dir.mkdir(parents=True, exist_ok=True)
    os.environ["QIANKE_C_END_DB"] = str(case_dir / "c_end.sqlite")
    store._DB_PATH = None
    store.init()
    return case_dir


def _last_ai_text(messages) -> str:
    for msg in reversed(messages or []):
        if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
            return str(msg.content)
    return ""


def _raw_has_banned(raw: str, words: tuple[str, ...]) -> list[str]:
    outside = persona._outside_quotes(raw)
    return [word for word in words if word in outside]


def _judge(case: dict, reply: str, extra: dict | None = None) -> tuple[list[str], list[str]]:
    """返回 (失败原因, 备注)；失败为空 = 通过。只判可确定项。"""
    failures: list[str] = []
    notes: list[str] = []
    extra = extra or {}
    raw = (reply or "").strip()

    # 草稿场景在 interrupt 处停下，本来就没有最终文本；只校验草稿本身。
    if case["kind"] in {"dialog", "commentary"} and not raw:
        return ["empty_reply"], notes
    if not raw:
        guarded_text = ""
        violations: tuple[str, ...] = ()
    else:
        result = persona.guard(
            raw,
            tier="commentary" if case["kind"] == "commentary" else "L2",
            fallback=companion_agent.FALLBACK if case["kind"] == "commentary" else persona.DIALOG_FALLBACK,
        )
        guarded_text, violations = result.text, result.violations
        for violation in violations:
            if violation.startswith("banned:") or violation in {"emoji", "exclamation"}:
                failures.append(violation)
        if guarded_text == persona.DIALOG_FALLBACK and raw != persona.DIALOG_FALLBACK:
            failures.append("guard_fallback")

    # 长度以"用户实际看到的文本"为准：guard 会把超长回复截断，截断本身记备注不算失败。
    limit = persona.TONE_LIMITS["commentary" if case["kind"] == "commentary" else "L2"]
    if len(guarded_text) > limit:
        failures.append(f"too_long:{len(guarded_text)}>{limit}")
    if any(item.startswith("overflow:") for item in violations):
        notes.append(f"guard_truncated:{len(raw)}->{len(guarded_text)}")

    failures.extend(f"sales:{w}" for w in _raw_has_banned(raw, SALES_BANNED))
    failures.extend(f"ai_speak:{w}" for w in _raw_has_banned(raw, AI_BANNED))

    any_of = case.get("any") or []
    text_for_check = raw + " " + json.dumps(extra, ensure_ascii=False)
    if any_of and not any(item in text_for_check for item in any_of):
        failures.append("missing:any_of")

    if case["kind"] == "draft":
        if not extra.get("interrupted"):
            failures.append("no_interrupt")
        if not (extra.get("draft") or {}).get("order_id"):
            failures.append("no_draft")
    if case["kind"] in {"confirm", "cancel"}:
        expected = "订单已创建" if case["kind"] == "confirm" else "订单已取消"
        if expected not in text_for_check:
            failures.append(f"missing:{expected}")
    return failures, notes


def _run_dialog(case: dict, case_dir: Path) -> tuple[str, dict]:
    saver = sqlite_checkpointer(case_dir / "agent.sqlite")
    result = c_agent.run_c_agent(
        case["text"],
        buyer_id="buyer_eval",
        thread_id=f"eval_{case['id']}",
        checkpointer=saver,
        llm=c_agent._make_llm(),
    )
    extra = {"interrupted": result["interrupted"], "draft": result["draft"], "order": result["order"]}
    return _last_ai_text(result["messages"]), extra


def _run_draft(case: dict, case_dir: Path) -> tuple[str, dict]:
    reply, extra = _run_dialog(case, case_dir)
    return reply, extra


def _confirm_flow(case: dict, case_dir: Path, approved: bool) -> tuple[str, dict]:
    saver = sqlite_checkpointer(case_dir / "agent.sqlite")
    llm = c_agent._make_llm()
    thread_id = f"eval_{case['id']}"
    c_agent.run_c_agent(
        case["text"], buyer_id="buyer_eval", thread_id=thread_id, checkpointer=saver, llm=llm
    )
    resumed = c_agent.resume_c_agent(
        buyer_id="buyer_eval", thread_id=thread_id, approved=approved, checkpointer=saver, llm=llm
    )
    return _last_ai_text(resumed["messages"]), {"order": resumed.get("order"), "status": resumed.get("status")}


def _run_commentary(case: dict) -> tuple[str, dict]:
    reply = companion_agent.commentary(
        "buyer_eval",
        case["text"],
        "今天最后 3 件，卖完就没啦~",
    )
    return reply, {}


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    started = time.time()
    rows: list[dict] = []

    for case in CASES:
        case_dir = _fresh_db(case["id"])
        try:
            if case["kind"] == "commentary":
                reply, extra = _run_commentary(case)
            elif case["kind"] == "confirm":
                reply, extra = _confirm_flow(case, case_dir, approved=True)
            elif case["kind"] == "cancel":
                reply, extra = _confirm_flow(case, case_dir, approved=False)
            else:
                reply, extra = _run_dialog(case, case_dir)
            failures, notes = _judge(case, reply, extra)
        except Exception as exc:  # noqa: BLE001 - Eval 要记录失败而不是崩掉
            reply, failures, notes = "", [f"error:{type(exc).__name__}:{exc}"], []

        rows.append({
            "id": case["id"],
            "kind": case["kind"],
            "input": case["text"],
            "reply": reply,
            "failures": failures,
            "notes": notes,
            "passed": not failures,
        })
        mark = "PASS" if not failures else "FAIL: " + ",".join(failures)
        # 控制台只打 ASCII，中文细节看 report.md
        print(f"{case['id']:<18} {mark}")

    passed = sum(1 for row in rows if row["passed"])
    report = {
        "prompt_version": persona.PROMPT_VERSION,
        "model_env": os.environ.get("DEEPSEEK_MODEL", ""),
        "total": len(rows),
        "passed": passed,
        "duration_seconds": round(time.time() - started, 1),
        "note": "自动判分只覆盖禁词/emoji/感叹号/长度/必含信息/订单动作边界；语义质量需人工或 LLM Judge 复核。",
        "cases": rows,
    }
    (WORK / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# C 端「小鱼」人设 Eval 报告",
        "",
        f"- prompt 版本：{persona.PROMPT_VERSION}",
        f"- 场景数：{len(rows)}，自动判分通过：{passed}",
        f"- 耗时：{report['duration_seconds']} 秒",
        f"- 判分范围：{report['note']}",
        "",
        "| 场景 | 结果 | 模型回复 | 失败项 | 备注 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        reply = (row["reply"] or "").replace("\n", " ")
        lines.append(
            f"| {row['id']} | {'PASS' if row['passed'] else 'FAIL'} | {reply} | "
            f"{', '.join(row['failures'])} | {', '.join(row['notes'])} |"
        )
    (WORK / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"SUMMARY {passed}/{len(rows)} in {report['duration_seconds']}s")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
