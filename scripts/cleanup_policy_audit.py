"""清理开发/测试环境生成的策略变更审计。

生产环境审计应保持只追加；本脚本只用于演示库清理测试数据。
默认 dry-run；--yes 才删除，并先导出 JSON 备份。

用法：
    python scripts/cleanup_policy_audit.py --merchant m_gear_002 --changed-by admin
    python scripts/cleanup_policy_audit.py --merchant m_gear_002 --changed-by admin --yes
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rag_demo.c_end import store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchant", default="m_gear_002")
    parser.add_argument("--changed-by", default="admin")
    parser.add_argument("--yes", action="store_true", help="确认删除；默认只预览")
    args = parser.parse_args()

    store.init()
    rows = store.query_policy_audit(args.merchant, limit=5000)["items"]
    targets = [
        row for row in rows
        if not args.changed_by or row.get("changed_by") == args.changed_by
    ]
    print(f"merchant={args.merchant} matched={len(targets)} total={len(rows)}")
    for row in targets[:20]:
        print(row["policy_audit_id"], row["changed_at"], row["changed_by"])
    if not targets:
        return 0
    if not args.yes:
        print("dry-run：加 --yes 才会删除（会先备份）")
        return 0

    backup_dir = Path("logs")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"policy_audit_backup_{int(time.time())}.json"
    backup.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"backup={backup}")

    conn = store._connect()
    try:
        conn.executemany(
            "DELETE FROM c_merchant_policy_audit WHERE policy_audit_id = ?",
            [(row["policy_audit_id"],) for row in targets],
        )
        conn.commit()
    finally:
        conn.close()
    print(f"deleted={len(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
