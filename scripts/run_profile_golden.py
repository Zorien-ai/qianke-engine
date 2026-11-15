#!/usr/bin/env python
"""B 端用户画像查询黄金集运行器。

用法：
    B_IMPORT_PASSWORD=... python scripts/run_profile_golden.py
    python scripts/run_profile_golden.py --fail-under 0.9 --json-out var/b_profile_golden_result.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN = ROOT / "tests" / "evals" / "b_profile" / "golden.json"


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")


def _answer_ok(answer: str, groups: list[list[str]]) -> tuple[bool, list[str]]:
    haystack = str(answer or "").lower()
    failed = []
    for group in groups:
        if not any(str(choice).lower() in haystack for choice in group):
            failed.append(" / ".join(str(item) for item in group))
    return not failed, failed


def _cards_ok(cards: list[dict[str, Any]], expected: list[str]) -> tuple[bool, list[str]]:
    ids = [str(card.get("user_id") or "") for card in cards]
    missing = []
    for item in expected:
        if item.endswith("_"):
            found = any(card_id.startswith(item) for card_id in ids)
        else:
            found = item in ids
        if not found:
            missing.append(item)
    return not missing, missing


def _sources_ok(sources: list[dict[str, Any]], expected: list[str]) -> tuple[bool, list[str]]:
    """sources_any：候选来源命中任意一个即可。"""
    names = [str(source.get("source") or "") for source in sources]
    if not expected:
        return True, []
    if any(any(name in source_name for source_name in names) for name in expected):
        return True, []
    return False, expected


def evaluate(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    expect = case.get("expect") or {}
    answer = str(response.get("answer") or "")
    cards = response.get("cards") or []
    sources = response.get("sources") or []
    failures: list[str] = []
    if expect.get("route") and response.get("route") != expect["route"]:
        failures.append(f"route={response.get('route')} 期望 {expect['route']}")
    ok, missing = _cards_ok(cards, expect.get("cards_all") or [])
    if not ok:
        failures.append("缺卡牌: " + "、".join(missing))
    ok, missing = _cards_ok(cards, expect.get("cards_any") or [])
    if not ok:
        failures.append("缺任一卡牌: " + "、".join(missing))
    if expect.get("min_cards") is not None and len(cards) < int(expect["min_cards"]):
        failures.append(f"卡牌数 {len(cards)} < {expect['min_cards']}")
    if expect.get("max_cards") is not None and len(cards) > int(expect["max_cards"]):
        failures.append(f"卡牌数 {len(cards)} > {expect['max_cards']}")
    ok, missing = _answer_ok(answer, expect.get("answer_groups") or [])
    if not ok:
        failures.append("回答缺关键词: " + "、".join(missing))
    ok, missing = _sources_ok(sources, expect.get("sources_any") or [])
    if not ok:
        failures.append("缺来源: " + "、".join(missing))
    return {
        "id": case.get("id"),
        "question": case.get("question"),
        "source": case.get("source"),
        "route": response.get("route"),
        "cards": [card.get("user_id") for card in cards],
        "sources": [source.get("source") for source in sources],
        "answer": answer[:500],
        "passed": not failures,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("B_PROFILE_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--username", default=os.environ.get("B_PROFILE_USERNAME", "sim_biz_tea"))
    parser.add_argument("--password", default=os.environ.get("B_IMPORT_PASSWORD") or os.environ.get("B_PROFILE_PASSWORD") or "")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--fail-under", type=float, default=0.8)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    if not args.password:
        print(json.dumps({"ok": False, "error": "缺少密码：设置 B_IMPORT_PASSWORD"}, ensure_ascii=False))
        return 2
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    session = requests.Session()
    login = session.post(
        f"{args.base_url}/auth/login",
        json={"account": args.username, "password": args.password, "remember": False},
        timeout=30,
    )
    if login.status_code != 200:
        print(json.dumps({"ok": False, "error": f"登录失败 HTTP {login.status_code}"}, ensure_ascii=False))
        return 2
    results = []
    started = time.time()
    for case in golden.get("cases") or []:
        began = time.time()
        try:
            response = session.post(
                f"{args.base_url}/api/b/workbench/profile-query",
                json={"question": case["question"], "source": case.get("source", "all")},
                timeout=180,
            )
            if response.status_code != 200:
                results.append({
                    "id": case.get("id"),
                    "passed": False,
                    "failures": [f"HTTP {response.status_code}: {response.text[:300]}"],
                    "elapsed_s": round(time.time() - began, 1),
                })
                continue
            result = evaluate(case, response.json())
            result["elapsed_s"] = round(time.time() - began, 1)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            results.append({
                "id": case.get("id"),
                "passed": False,
                "failures": [str(exc)],
                "elapsed_s": round(time.time() - began, 1),
            })
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    pass_rate = round(passed / total, 4) if total else 0.0
    report = {
        "ok": pass_rate >= args.fail_under,
        "golden": golden.get("name"),
        "merchant_id": golden.get("merchant_id"),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": pass_rate,
        "threshold": args.fail_under,
        "elapsed_s": round(time.time() - started, 1),
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
