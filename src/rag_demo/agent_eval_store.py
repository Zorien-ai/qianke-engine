# -*- coding: utf-8 -*-
"""Agent 数据集与评测实验的本地存储/执行器（Phase C MVP）。

只存元数据和评测结果；单次 Agent 调用仍走 ai_traces 监控。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from rag_demo import auth

_schema_ready = False
_lock = threading.Lock()

DDL = [
    """
    CREATE TABLE IF NOT EXISTS agent_eval_dataset (
        dataset_id    TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        description   TEXT NOT NULL DEFAULT '',
        created_by    TEXT NOT NULL DEFAULT '',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_eval_case (
        case_id              TEXT PRIMARY KEY,
        dataset_id           TEXT NOT NULL REFERENCES agent_eval_dataset(dataset_id) ON DELETE CASCADE,
        question             TEXT NOT NULL,
        expected_answer      TEXT NOT NULL DEFAULT '',
        expected_keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        expected_tools_json  JSONB NOT NULL DEFAULT '[]'::jsonb,
        source_trace_id      TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS agent_eval_case_dataset ON agent_eval_case (dataset_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS agent_eval_experiment (
        experiment_id TEXT PRIMARY KEY,
        dataset_id    TEXT NOT NULL REFERENCES agent_eval_dataset(dataset_id) ON DELETE CASCADE,
        name          TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'QUEUED',
        target_dataset TEXT NOT NULL DEFAULT '',
        created_by    TEXT NOT NULL DEFAULT '',
        total_cases   INTEGER NOT NULL DEFAULT 0,
        passed_cases  INTEGER NOT NULL DEFAULT 0,
        metrics_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
        error         TEXT NOT NULL DEFAULT '',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        started_at    TIMESTAMPTZ,
        finished_at   TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS agent_eval_exp_dataset ON agent_eval_experiment (dataset_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS agent_eval_result (
        result_id     TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES agent_eval_experiment(experiment_id) ON DELETE CASCADE,
        case_id       TEXT NOT NULL,
        trace_id      TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT '',
        passed        BOOLEAN NOT NULL DEFAULT FALSE,
        score         DOUBLE PRECISION NOT NULL DEFAULT 0,
        answer        TEXT NOT NULL DEFAULT '',
        latency_ms    INTEGER NOT NULL DEFAULT 0,
        total_tokens  BIGINT NOT NULL DEFAULT 0,
        tools_json    JSONB NOT NULL DEFAULT '[]'::jsonb,
        error         TEXT NOT NULL DEFAULT '',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS agent_eval_result_exp ON agent_eval_result (experiment_id, created_at)",
]


def _connect():
    cfg = dict(auth.current_pg_config())
    if str(cfg.get("host") or "") == "localhost":
        cfg["host"] = "127.0.0.1"
    return psycopg2.connect(**cfg)


def init() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _lock:
        if _schema_ready:
            return
        conn = _connect()
        try:
            cur = conn.cursor()
            for sql in DDL:
                cur.execute(sql)
            conn.commit()
            cur.close()
        finally:
            conn.close()
        _schema_ready = True


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return []
    return value if value is not None else []


def _dataset_row(row: dict) -> dict:
    return {
        **row,
        "created_at": _iso(row.get("created_at")),
    }


def _case_row(row: dict) -> dict:
    return {
        **row,
        "expected_keywords": _loads(row.get("expected_keywords_json")),
        "expected_tools": _loads(row.get("expected_tools_json")),
        "created_at": _iso(row.get("created_at")),
    }


def create_dataset(name: str, description: str, trace_ids: list[str], *, actor: str = "") -> dict:
    init()
    name = str(name or "").strip()[:100]
    if not name:
        raise ValueError("数据集名称不能为空")
    trace_ids = [str(item).strip() for item in (trace_ids or []) if str(item).strip()]
    if not trace_ids:
        raise ValueError("至少选择一条 Trace")
    if len(trace_ids) > 50:
        raise ValueError("一次最多从 50 条 Trace 创建数据集")
    dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "INSERT INTO agent_eval_dataset (dataset_id, name, description, created_by) VALUES (%s,%s,%s,%s)",
            (dataset_id, name, str(description or "")[:500], actor),
        )
        for trace_id in dict.fromkeys(trace_ids):
            cur.execute(
                "SELECT trace_id, meta FROM ai_traces WHERE trace_id=%s AND entrypoint LIKE %s",
                (trace_id, "agent.%"),
            )
            trace = cur.fetchone()
            if trace is None:
                continue
            meta = trace.get("meta") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (TypeError, ValueError):
                    meta = {}
            question = str(meta.get("question") or "").strip()
            if not question:
                continue
            cur.execute(
                """INSERT INTO agent_eval_case
                   (case_id, dataset_id, question, expected_answer, source_trace_id)
                   VALUES (%s,%s,%s,%s,%s)""",
                (
                    f"case_{uuid.uuid4().hex[:12]}",
                    dataset_id,
                    question,
                    str(meta.get("final_answer") or "")[:4000],
                    trace_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_dataset(dataset_id) or {"dataset_id": dataset_id, "name": name, "cases": []}


def list_datasets() -> list[dict]:
    init()
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT d.*, COUNT(c.case_id) AS case_count
               FROM agent_eval_dataset d
               LEFT JOIN agent_eval_case c ON c.dataset_id=d.dataset_id
               GROUP BY d.dataset_id
               ORDER BY d.created_at DESC LIMIT 100"""
        )
        return [_dataset_row(dict(row)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_dataset(dataset_id: str) -> dict | None:
    init()
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM agent_eval_dataset WHERE dataset_id=%s", (dataset_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "SELECT * FROM agent_eval_case WHERE dataset_id=%s ORDER BY created_at ASC",
            (dataset_id,),
        )
        cases = [_case_row(dict(item)) for item in cur.fetchall()]
        data = _dataset_row(dict(row))
        data["case_count"] = len(cases)
        data["cases"] = cases
        return data
    finally:
        conn.close()


def create_experiment(dataset_id: str, name: str, *, target_dataset: str, actor: str = "") -> dict:
    init()
    dataset = get_dataset(dataset_id)
    if dataset is None:
        raise ValueError("数据集不存在")
    if not dataset.get("cases"):
        raise ValueError("数据集没有用例")
    experiment_id = f"exp_{uuid.uuid4().hex[:10]}"
    exp_name = str(name or "").strip()[:100] or f"实验 {datetime.now().strftime('%m-%d %H:%M')}"
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO agent_eval_experiment
               (experiment_id, dataset_id, name, status, target_dataset, created_by, total_cases)
               VALUES (%s,%s,%s,'QUEUED',%s,%s,%s)""",
            (experiment_id, dataset_id, exp_name, target_dataset, actor, len(dataset["cases"])),
        )
        conn.commit()
    finally:
        conn.close()
    return get_experiment(experiment_id) or {"experiment_id": experiment_id}


def list_experiments(dataset_id: str | None = None) -> list[dict]:
    init()
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if dataset_id:
            cur.execute(
                "SELECT * FROM agent_eval_experiment WHERE dataset_id=%s ORDER BY created_at DESC LIMIT 100",
                (dataset_id,),
            )
        else:
            cur.execute("SELECT * FROM agent_eval_experiment ORDER BY created_at DESC LIMIT 100")
        return [_experiment_row(dict(row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _experiment_row(row: dict) -> dict:
    return {
        **row,
        "metrics": _loads(row.get("metrics_json")),
        "created_at": _iso(row.get("created_at")),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
    }


def get_experiment(experiment_id: str) -> dict | None:
    init()
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM agent_eval_experiment WHERE experiment_id=%s", (experiment_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "SELECT r.*, c.question FROM agent_eval_result r LEFT JOIN agent_eval_case c ON c.case_id=r.case_id "
            "WHERE r.experiment_id=%s ORDER BY r.created_at ASC",
            (experiment_id,),
        )
        results = []
        for item in cur.fetchall():
            data = dict(item)
            data["tools"] = _loads(data.pop("tools_json", []))
            data["created_at"] = _iso(data.get("created_at"))
            results.append(data)
        data = _experiment_row(dict(row))
        data["results"] = results
        return data
    finally:
        conn.close()


def _score_case(case: dict, result: dict) -> tuple[bool, float]:
    status_ok = str(result.get("status") or "") == "COMPLETED"
    answer = str(result.get("final_answer") or "")
    keywords = case.get("expected_keywords") or []
    keyword_ok = all(str(word).lower() in answer.lower() for word in keywords)
    expected_tools = set(case.get("expected_tools") or [])
    actual_tools = {
        str(item.get("name") or "")
        for item in (result.get("tool_calls") or [])
        if isinstance(item, dict)
    }
    tools_ok = expected_tools.issubset(actual_tools)
    passed = bool(status_ok and keyword_ok and tools_ok)
    return passed, 1.0 if passed else 0.0


def run_experiment(experiment_id: str, *, account: dict, target_dataset: str) -> None:
    init()
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM agent_eval_experiment WHERE experiment_id=%s",
            (experiment_id,),
        )
        exp = cur.fetchone()
        if exp is None:
            return
        cur.execute(
            "UPDATE agent_eval_experiment SET status='RUNNING', started_at=now() WHERE experiment_id=%s",
            (experiment_id,),
        )
        conn.commit()
        cur.execute(
            "SELECT * FROM agent_eval_case WHERE dataset_id=%s ORDER BY created_at ASC",
            (exp["dataset_id"],),
        )
        cases = [_case_row(dict(item)) for item in cur.fetchall()]
    finally:
        conn.close()

    passed_count = 0
    total_latency = 0
    total_tokens = 0
    errors = 0
    try:
        from rag_demo.agent.execution_store import get_execution_store
        from rag_demo.agent.policy import ToolPolicy
        from rag_demo.agent.service import execute_agent

        allowed_tools = ToolPolicy.for_account(account).allowed_tools(account)
        for index, case in enumerate(cases, 1):
            started = time.perf_counter()
            try:
                result, replay = execute_agent(
                    query=case["question"],
                    dataset=target_dataset,
                    account=account,
                    request_id=f"{experiment_id}_{index}",
                    store=get_execution_store(),
                    wall_timeout_seconds=60,
                    allowed_tools=tuple(allowed_tools),
                )
                passed, score = _score_case(case, result)
                status = str(result.get("status") or "")
                answer = str(result.get("final_answer") or "")
                latency = int((time.perf_counter() - started) * 1000)
                tokens = int(result.get("total_tokens") or 0)
                tools = [str(item.get("name") or "") for item in (result.get("tool_calls") or []) if isinstance(item, dict)]
                trace_id = str(result.get("monitor_trace_id") or "")
                error = str(result.get("error") or "")
                passed_count += 1 if passed else 0
                total_latency += latency
                total_tokens += tokens
            except Exception as exc:  # noqa: BLE001
                passed = False
                score = 0.0
                status = "FAILED"
                answer = ""
                latency = 0
                tokens = 0
                tools = []
                trace_id = ""
                error = f"{type(exc).__name__}: {exc}"
                errors += 1
            conn = _connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO agent_eval_result
                       (result_id, experiment_id, case_id, trace_id, status, passed, score,
                        answer, latency_ms, total_tokens, tools_json, error)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        f"res_{uuid.uuid4().hex[:12]}",
                        experiment_id,
                        case["case_id"],
                        trace_id,
                        status,
                        passed,
                        score,
                        answer[:8000],
                        latency,
                        tokens,
                        Json(tools),
                        error[:1000],
                    ),
                )
                cur.execute(
                    "UPDATE agent_eval_experiment SET passed_cases=%s WHERE experiment_id=%s",
                    (passed_count, experiment_id),
                )
                conn.commit()
            finally:
                conn.close()
        metrics = {
            "success_rate": round(passed_count / len(cases), 4) if cases else 0,
            "passed": passed_count,
            "total": len(cases),
            "avg_latency_ms": round(total_latency / len(cases)) if cases else 0,
            "avg_tokens": round(total_tokens / len(cases)) if cases else 0,
            "errors": errors,
        }
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE agent_eval_experiment
                   SET status='COMPLETED', passed_cases=%s, metrics_json=%s, finished_at=now()
                   WHERE experiment_id=%s""",
                (passed_count, Json(metrics), experiment_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE agent_eval_experiment SET status='FAILED', error=%s, finished_at=now() WHERE experiment_id=%s",
                (f"{type(exc).__name__}: {exc}"[:1000], experiment_id),
            )
            conn.commit()
        finally:
            conn.close()
