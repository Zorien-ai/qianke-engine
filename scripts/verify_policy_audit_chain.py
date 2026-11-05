"""校验策略审计哈希链，供定时任务/发布检查调用。"""
from __future__ import annotations

import argparse
import json

from rag_demo.c_end import store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchant", default="m_gear_002")
    args = parser.parse_args()
    store.init()
    result = store.verify_policy_audit_chain(args.merchant)
    result["anchor"] = store.verify_policy_audit_anchor(args.merchant)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] and result["anchor"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
