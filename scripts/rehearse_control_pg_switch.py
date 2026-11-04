"""控制面切换预演：SQLite 回填到临时 PG schema，再用 PG 读写，最后清理。

不改生产 schema，不停 API/Worker；仅验证切换步骤与数据一致性。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_migrate():
    path = ROOT / "scripts" / "migrate_superagent_to_pg.py"
    spec = importlib.util.spec_from_file_location("migrate_superagent_to_pg", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="")
    parser.add_argument("--queue-schema", default="")
    args = parser.parse_args()
    schema = args.schema or f"qianke_rehearsal_{uuid.uuid4().hex[:8]}"
    queue_schema = args.queue_schema or f"sa_queue_rehearsal_{uuid.uuid4().hex[:8]}"

    migrate_mod = _load_migrate()
    migrated = migrate_mod.migrate(
        schema=schema, queue_schema=queue_schema, include_jobs=True, apply=True
    )

    os.environ["QIANKE_CONTROL_BACKEND"] = "postgres"
    os.environ["QIANKE_CONTROL_PG_SCHEMA"] = schema
    os.environ["QIANKE_QUEUE_SCHEMA"] = queue_schema

    from rag_demo.superagent import queue_pg, store as sa_store

    queue_pg.SCHEMA = queue_schema
    sa_store._PG_INITIALIZED_SCHEMA = None
    result = {"schema": schema, "queue_schema": queue_schema, "migrated": migrated}
    try:
        out = sa_store.create_trigger(
            source="rehearsal", content="切换预演", channel="manual", thread_key="rehearsal:1"
        )
        work_item_id = out["work_item"]["work_item_id"]
        sa_store.start_work_item(work_item_id)
        sa_store.finish_work_item(
            work_item_id, {"ok": True}, approval=True,
            action={"action_type": "CANCEL_ORDER", "order_id": "o_rehearsal"},
        )
        sa_store.decide_approval(work_item_id, approved=True)
        sa_store.complete_execution(work_item_id, success=True, result={"done": True})
        result["write_status"] = sa_store.get_work_item(work_item_id)["status"]
        result["approval"] = sa_store.get_approval(work_item_id)["execution_status"]
        result["audit_total"] = sa_store.list_action_audit(
            "m_gear_002", action_type="CANCEL_ORDER"
        )["total"]
        result["ok"] = result["write_status"] == "DONE" and result["approval"] == "EXECUTED"
    finally:
        import psycopg2
        from rag_demo.control.settings import pg_settings

        settings = pg_settings()
        conn = psycopg2.connect(
            host=settings["host"], port=settings["port"], user=settings["user"],
            password=settings["password"], dbname=settings["dbname"], connect_timeout=5,
        )
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                cur.execute(f'DROP SCHEMA IF EXISTS "{queue_schema}" CASCADE')
        finally:
            conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
