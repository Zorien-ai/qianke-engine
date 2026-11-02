"""Super-agent vs 当前 B Agent 对比 Eval（真实 HTTP + 真实模型）。

用法：
    python scripts/superagent_eval.py --api http://127.0.0.1:8000

输出：
    tests/superagent_eval_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rag_demo import auth  # noqa: E402

CASES = [
    {
        "id": "order_status",
        "question": "请查订单 order_5695476eb1c8441e 的状态和商品",
        "expected": ["order_5695476eb1c8441e", "保温杯"],
        "domain": "order",
    },
    {
        "id": "logistics",
        "question": "订单 order_5695476eb1c8441e 的物流是什么？买家说物流异常",
        "expected": ["顺丰", "SF-B-0001"],
        "domain": "order",
    },
    {
        "id": "after_sales",
        "question": "订单 order_5695476eb1c8441e 有没有售后工单？用户要退款",
        "expected": ["售后", "退款"],
        "domain": "after_sales",
    },
    {
        "id": "policy",
        "question": "平台售后和退货政策是什么？",
        "expected": ["7天", "退货"],
        "domain": "policy",
    },
    {
        "id": "noise",
        "question": "今天天气不错，随便聊聊",
        "expected": [],
        "domain": "noise",
    },
]


def _login(client: httpx.Client) -> None:
    response = client.post(
        "/auth/login",
        json={"account": auth.SEED_ADMIN_USERNAME, "password": auth.SEED_ADMIN_PASSWORD},
    )
    response.raise_for_status()


def _run_superagent(client: httpx.Client, case: dict) -> dict:
    start = time.perf_counter()
    event = client.post(
        "/api/superagent/events",
        json={
            "source": "eval",
            "channel": "eval",
            "content": case["question"],
            "thread_key": f"eval:{case['id']}:{time.time_ns()}",
        },
    ).json()
    if not event.get("accepted"):
        return {
            "accepted": False,
            "reason": event.get("reason"),
            "latency_ms": round((time.perf_counter() - start) * 1000),
            "answer": "",
            "status": "FILTERED",
        }
    item_id = event["work_item"]["work_item_id"]
    client.post(f"/api/superagent/work-items/{item_id}/run").raise_for_status()
    item = {}
    for _ in range(90):
        time.sleep(2)
        item = client.get(f"/api/superagent/work-items/{item_id}").json()
        if item.get("status") not in ("PENDING", "RUNNING"):
            break
    return {
        "accepted": True,
        "work_item_id": item_id,
        "status": item.get("status"),
        "latency_ms": round((time.perf_counter() - start) * 1000),
        "answer": (item.get("result") or {}).get("summary") or "",
        "worker": (item.get("result") or {}).get("worker"),
    }


def _run_b_agent(client: httpx.Client, case: dict) -> dict:
    start = time.perf_counter()
    try:
        response = client.post("/api/agent/run", json={"query": case["question"]}, timeout=180)
        data = response.json()
        answer = data.get("answer") or data.get("final_answer") or json.dumps(data, ensure_ascii=False)[:3000]
        return {
            "http_status": response.status_code,
            "latency_ms": round((time.perf_counter() - start) * 1000),
            "answer": answer,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "http_status": 0,
            "latency_ms": round((time.perf_counter() - start) * 1000),
            "answer": "",
            "error": str(exc)[:500],
        }


def _score(answer: str, expected: list[str]) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for token in expected if token in (answer or ""))
    return round(hits / len(expected), 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default=str(ROOT / "tests" / "superagent_eval_results.json"))
    args = parser.parse_args()
    results = []
    with httpx.Client(base_url=args.api, timeout=30) as client:
        _login(client)
        for case in CASES:
            print(f"[eval] {case['id']} superagent...", flush=True)
            sa = _run_superagent(client, case)
            sa["score"] = _score(sa.get("answer") or "", case["expected"])
            print(f"[eval] {case['id']} b-agent...", flush=True)
            ba = _run_b_agent(client, case)
            ba["score"] = _score(ba.get("answer") or "", case["expected"])
            results.append({
                "case": case,
                "superagent": sa,
                "b_agent": ba,
                "winner": "superagent" if sa["score"] > ba["score"] else (
                    "b_agent" if ba["score"] > sa["score"] else "tie"
                ),
            })
    summary = {
        "cases": len(results),
        "superagent_avg_score": round(sum(r["superagent"]["score"] for r in results) / len(results), 3),
        "b_agent_avg_score": round(sum(r["b_agent"]["score"] for r in results) / len(results), 3),
        "superagent_wins": sum(1 for r in results if r["winner"] == "superagent"),
        "b_agent_wins": sum(1 for r in results if r["winner"] == "b_agent"),
        "ties": sum(1 for r in results if r["winner"] == "tie"),
        "results": results,
    }
    Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
