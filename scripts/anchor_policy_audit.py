"""写入策略审计锚点；建议每天由定时任务执行。"""
from __future__ import annotations

import argparse
import json

from rag_demo.c_end import store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchant", action="append", default=[])
    args = parser.parse_args()
    merchants = args.merchant or ["m_gear_002"]
    store.init()
    result = []
    for merchant in merchants:
        anchor = store.anchor_policy_audit(merchant)
        verified = store.verify_policy_audit_anchor(merchant)
        result.append({"anchor": anchor, "verify": verified})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(item["verify"]["ok"] for item in result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
