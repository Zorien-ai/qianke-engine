"""租户试点冒烟：租户 / owner / 策略 / 工作项隔离检查。"""
from __future__ import annotations

import argparse
import json

from rag_demo.c_end import store as c_store
from rag_demo.superagent import store as sa_store


def run(merchant_id: str, owner_id: int) -> dict:
    c_store.init()
    sa_store.init()
    checks = []
    tenant = c_store.get_tenant(merchant_id)
    checks.append({"name": "tenant_exists", "ok": tenant is not None, "detail": tenant and tenant.get("status")})
    member = c_store.get_merchant_member(owner_id)
    checks.append({
        "name": "owner_bound",
        "ok": member is not None and member.get("merchant_id") == merchant_id and member.get("role") == "owner",
        "detail": member,
    })
    policy = c_store.get_merchant_policy(merchant_id)
    checks.append({
        "name": "policy_initialized",
        "ok": bool(policy and policy.get("allowed_actions")),
        "detail": {
            "allowed_actions": len(policy.get("allowed_actions") or []),
            "compensation_max_amount": policy.get("compensation_max_amount"),
            "refund_max_amount": policy.get("refund_max_amount"),
        },
    })
    items = sa_store.list_work_items(limit=200, merchant_id=merchant_id)
    checks.append({
        "name": "work_items_scoped",
        "ok": all(item.get("merchant_id") == merchant_id for item in items),
        "detail": {"count": len(items)},
    })
    return {"merchant_id": merchant_id, "owner_id": owner_id, "ok": all(c["ok"] for c in checks), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchant", default="m_pilot_001")
    parser.add_argument("--owner-id", type=int, default=60)
    args = parser.parse_args()
    result = run(args.merchant, args.owner_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
