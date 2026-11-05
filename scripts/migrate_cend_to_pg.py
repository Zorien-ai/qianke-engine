"""C 端控制面回填：SQLite → PostgreSQL（P3-A）。

只回填数据，不切换运行时读路径。默认 dry-run；--yes 才写入。

用法：
    python scripts/migrate_cend_to_pg.py
    python scripts/migrate_cend_to_pg.py --yes
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from rag_demo.c_end import store as c_store
from rag_demo.control.postgres_repository import PostgresControlRepository
from rag_demo.control.settings import SCHEMA_PATTERN

TABLES = [
    "c_product",
    "c_order",
    "c_order_item",
    "c_after_sale",
    "c_compensation",
    "c_quote",
    "c_message",
    "c_app_message",
    "c_friend",
    "c_group",
    "c_group_member",
    "c_group_message",
    "c_mention",
    "c_thread_read",
    "c_companion",
    "c_client_request",
    "c_reconciliation_run",
    "c_reconciliation_alert",
    "c_merchant_tenant",
    "c_merchant_member",
    "c_merchant_policy",
    "c_merchant_policy_audit",
    "c_tenant_provision",
]


def _sqlite_rows(table: str) -> list[dict[str, Any]]:
    c_store.init()
    conn = c_store._connect()
    try:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _sqlite_pk(table: str) -> list[str]:
    conn = c_store._connect()
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return [row["name"] for row in sorted(rows, key=lambda row: row["pk"]) if row["pk"]]
    finally:
        conn.close()


def _upsert_sql(schema: str, table: str, columns: list[str], pk: list[str]) -> str:
    names = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("%s" for _ in columns)
    updates = ", ".join(
        f'"{column}" = EXCLUDED."{column}"' for column in columns if column not in pk
    )
    conflict = ", ".join(f'"{column}"' for column in pk)
    suffix = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    return (
        f'INSERT INTO "{schema}"."{table}" ({names}) VALUES ({placeholders}) '
        f"ON CONFLICT ({conflict}) {suffix}"
    )


def migrate(*, schema: str = "qianke_control", apply: bool = False) -> dict[str, Any]:
    if not SCHEMA_PATTERN.match(schema):
        raise ValueError("schema 必须是合法 PostgreSQL 标识符")
    repo = PostgresControlRepository(schema=schema)
    source = {table: _sqlite_rows(table) for table in TABLES}
    pks = {table: _sqlite_pk(table) for table in TABLES}
    summary: dict[str, Any] = {
        "schema": schema,
        "apply": apply,
        "source": {table: len(rows) for table, rows in source.items()},
    }
    if not apply:
        repo.close()
        summary["target"] = "dry-run"
        return summary
    try:
        repo.init_schema()
        with repo._cursor() as cur:
            for table in TABLES:
                rows = source[table]
                if not rows:
                    continue
                columns = list(rows[0].keys())
                sql = _upsert_sql(schema, table, columns, pks[table])
                cur.executemany(
                    sql,
                    [tuple(row[column] for column in columns) for row in rows],
                )
        target = {}
        with repo._cursor() as cur:
            for table in TABLES:
                cur.execute(f'SELECT COUNT(*) AS n FROM "{schema}"."{table}"')
                target[table] = int(cur.fetchone()["n"])
        summary["target"] = target
        return summary
    finally:
        repo.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="qianke_control")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    summary = migrate(schema=args.schema, apply=args.yes)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.yes:
        print("dry-run：加 --yes 才会写入 PostgreSQL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
