"""Super-agent 控制表回填：SQLite → PostgreSQL。

默认 dry-run；--yes 才写入。幂等 upsert，按主键更新。

用法：
    python scripts/migrate_superagent_to_pg.py
    python scripts/migrate_superagent_to_pg.py --yes
    python scripts/migrate_superagent_to_pg.py --yes --skip-jobs
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from rag_demo.c_end import store as c_store
from rag_demo.control.postgres_repository import PostgresControlRepository
from rag_demo.control.settings import SCHEMA_PATTERN
from rag_demo.superagent import store as sa_store

TABLES = ["sa_thread", "sa_trigger", "sa_work_item", "sa_approval"]
JOB_COLUMNS = [
    "job_id", "work_item_id", "kind", "status", "attempts", "max_attempts",
    "available_at", "lease_until", "worker_id", "last_error", "created_at", "updated_at",
]
PK = {"sa_thread": "thread_id", "sa_trigger": "trigger_id", "sa_work_item": "work_item_id", "sa_approval": "approval_id"}


def _sqlite_rows(table: str) -> list[dict[str, Any]]:
    c_store.init()
    sa_store.init()
    conn = c_store._connect()
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _upsert_sql(schema: str, table: str, columns: list[str]) -> str:
    names = ", ".join(columns)
    placeholders = ", ".join("%s" for _ in columns)
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != PK[table])
    return (
        f'INSERT INTO "{schema}".{table} ({names}) VALUES ({placeholders}) '
        f"ON CONFLICT ({PK[table]}) DO UPDATE SET {updates}"
    )


def _ensure_queue_schema(cur, schema: str) -> None:
    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".sa_job (
            job_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 2,
            available_at TEXT NOT NULL,
            lease_until TEXT,
            worker_id TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(work_item_id, kind)
        )
        """
    )
    cur.execute(
        f'CREATE INDEX IF NOT EXISTS idx_sa_job_claim ON "{schema}".sa_job '
        "(status, available_at, created_at)"
    )


def migrate(*, schema: str = "qianke_control", queue_schema: str = "sa_queue",
            include_jobs: bool = True, apply: bool = False) -> dict[str, Any]:
    if not SCHEMA_PATTERN.match(schema) or not SCHEMA_PATTERN.match(queue_schema):
        raise ValueError("schema/queue_schema 必须是合法 PostgreSQL 标识符")
    repo = PostgresControlRepository(schema=schema)
    source = {table: _sqlite_rows(table) for table in TABLES}
    jobs = _sqlite_rows("sa_job") if include_jobs else []
    summary: dict[str, Any] = {
        "schema": schema,
        "queue_schema": queue_schema,
        "apply": apply,
        "source": {table: len(rows) for table, rows in source.items()},
        "jobs": len(jobs),
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
                sql = _upsert_sql(schema, table, columns)
                cur.executemany(sql, [tuple(row[column] for column in columns) for row in rows])
            if include_jobs and jobs:
                _ensure_queue_schema(cur, queue_schema)
                columns = JOB_COLUMNS
                sql = (
                    f'INSERT INTO "{queue_schema}".sa_job ({", ".join(columns)}) '
                    f'VALUES ({", ".join("%s" for _ in columns)}) '
                    "ON CONFLICT (job_id) DO UPDATE SET "
                    + ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != "job_id")
                )
                cur.executemany(sql, [tuple(row[column] for column in columns) for row in jobs])

        target = {}
        with repo._cursor() as cur:
            for table in TABLES:
                cur.execute(f'SELECT COUNT(*) AS n FROM "{schema}".{table}')
                target[table] = int(cur.fetchone()["n"])
            if include_jobs and jobs:
                cur.execute(f'SELECT COUNT(*) AS n FROM "{queue_schema}".sa_job')
                target["queue_jobs"] = int(cur.fetchone()["n"])
        summary["target"] = target
        return summary
    finally:
        repo.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="qianke_control")
    parser.add_argument("--queue-schema", default="sa_queue")
    parser.add_argument("--skip-jobs", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    summary = migrate(
        schema=args.schema,
        queue_schema=args.queue_schema,
        include_jobs=not args.skip_jobs,
        apply=args.yes,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.yes:
        print("dry-run：加 --yes 才会写入 PostgreSQL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
