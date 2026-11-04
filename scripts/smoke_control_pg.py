"""控制面 PostgreSQL 隔离烟测：建 schema、写审批流、队列 claim、审计查询、清理。

不修改生产 schema/配置；默认使用临时 schema 并在结束时 DROP。
"""
from __future__ import annotations

import argparse
import json
import os
import uuid

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="")
    parser.add_argument("--queue-schema", default="")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    schema = args.schema or f"qianke_smoke_{uuid.uuid4().hex[:8]}"
    queue_schema = args.queue_schema or f"sa_queue_smoke_{uuid.uuid4().hex[:8]}"
    os.environ["QIANKE_CONTROL_BACKEND"] = "postgres"
    os.environ["QIANKE_CONTROL_PG_SCHEMA"] = schema
    os.environ["QIANKE_QUEUE_SCHEMA"] = queue_schema

    from rag_demo.control.settings import pg_settings
    from rag_demo.superagent import queue_pg, store as sa_store

    queue_pg.SCHEMA = queue_schema
    result = {"schema": schema, "queue_schema": queue_schema, "steps": []}
    try:
        sa_store.init()
        out = sa_store.create_trigger(
            source="smoke", content="控制面 PG 烟测", channel="manual", thread_key="smoke:1"
        )
        work_item_id = out["work_item"]["work_item_id"]
        result["steps"].append({"thread": out["thread"]["thread_id"], "work_item": work_item_id})
        result["steps"].append({"start": sa_store.start_work_item(work_item_id)["status"]})
        result["steps"].append({
            "finish": sa_store.finish_work_item(
                work_item_id, {"ok": True}, approval=True,
                action={"action_type": "CANCEL_ORDER", "order_id": "o_smoke"},
            )["status"]
        })
        result["steps"].append({"decide": sa_store.decide_approval(work_item_id, approved=True)["status"]})
        result["steps"].append({
            "complete": sa_store.complete_execution(work_item_id, success=True, result={"done": True})["status"]
        })
        result["approval"] = sa_store.get_approval(work_item_id)["execution_status"]
        result["audit_total"] = sa_store.list_action_audit("m_gear_002", action_type="CANCEL_ORDER")["total"]

        job = sa_store.enqueue_job(work_item_id, kind="ACTION")
        result["job"] = job["job_id"]
        claimed = sa_store.claim_next_job("smoke-worker")
        result["claimed"] = claimed["status"] if claimed else None
        sa_store.finish_job(job["job_id"], "DONE")
        result["job_done"] = sa_store.get_job(job["job_id"])["status"]
        result["ok"] = True
    finally:
        if not args.keep:
            import psycopg2

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
