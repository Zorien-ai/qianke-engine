"""B 端千客用户池常驻刷新器：会话 + 交易并集，按商户隔离。

本地演示：
    python scripts/b_qianke_pool_worker.py --interval 300
    python scripts/b_qianke_pool_worker.py --merchant m_gear_002 --once

生产建议交给 systemd / 容器常驻；单次刷新也可以走
`POST /api/b/workbench/profile-pool/refresh`（owner/admin）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rag_demo.b_end import user_pool  # noqa: E402
from rag_demo.c_end import store  # noqa: E402

logger = logging.getLogger("b_qianke_pool_worker")


def _setup_logging() -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "b_qianke_pool_worker.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


def _targets(merchant: str | None) -> list[str]:
    if merchant:
        return [merchant]
    tenants = store.list_tenants()
    return [
        str(item["merchant_id"])
        for item in tenants
        if str(item.get("status") or "ACTIVE").upper() == "ACTIVE"
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="B 端千客用户池常驻刷新")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--limit", type=int, default=user_pool.POOL_MAX_BUYERS)
    parser.add_argument("--merchant", default="")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    _setup_logging()

    while True:
        started = time.time()
        total = 0
        for merchant_id in _targets(args.merchant or None):
            try:
                result = user_pool.refresh_merchant_pool(merchant_id, limit=args.limit)
                total += int(result.get("upserted") or 0)
                logger.info(
                    "pool_refresh %s",
                    json.dumps(result, ensure_ascii=False, default=str),
                )
            except Exception:  # noqa: BLE001 - 单商户失败不退出常驻进程
                logger.exception("pool_refresh_failed merchant=%s", merchant_id)
        logger.info("pool_round done merchants=%d upserted=%d elapsed=%.2fs",
                    len(_targets(args.merchant or None)), total, time.time() - started)
        if args.once:
            return 0
        time.sleep(max(30, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
