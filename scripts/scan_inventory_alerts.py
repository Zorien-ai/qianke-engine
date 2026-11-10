"""扫描商家低库存并写入站内待发送告警队列。

用法::

    python scripts/scan_inventory_alerts.py
    python scripts/scan_inventory_alerts.py --merchant m_gear_002

本脚本只写 c_inventory_alert，不调用企业微信/邮件。渠道未配置时，
告警停留在 PENDING 队列，等待后续发送器消费；可交给 cron / 任务计划程序定时执行。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rag_demo.api.b_workbench import _products_snapshot  # noqa: E402
from rag_demo.c_end import store  # noqa: E402


def scan_merchant(merchant_id: str, limit: int = 200) -> dict:
    snapshot = _products_snapshot(merchant_id, limit=limit)
    low_items = []
    for product in snapshot["products"]:
        for sku in product["skus"]:
            if not sku.get("low_stock"):
                continue
            low_items.append({
                "product_id": product["product_id"],
                "product_title": product.get("title") or product.get("name") or product["product_id"],
                "sku": sku["sku"],
                "spec": sku.get("spec") or "",
                "available_qty": sku.get("available_qty") or 0,
                "safety_stock": sku.get("safety_stock") or 0,
                "reorder_qty": sku.get("reorder_qty") or 0,
            })
    result = store.sync_inventory_alerts(merchant_id, low_items)
    return {**result, "low_stock_items": low_items}


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描商家低库存并写站内告警队列")
    parser.add_argument("--merchant", action="append", default=None, help="商家 ID，可重复；默认扫描全部已绑定商家")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    merchants = args.merchant or store.list_merchant_ids()
    if not merchants:
        print(json.dumps({"ok": True, "merchants": [], "note": "没有已绑定商家"}, ensure_ascii=False))
        return 0

    results = []
    for merchant_id in merchants:
        results.append(scan_merchant(merchant_id, limit=args.limit))
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
