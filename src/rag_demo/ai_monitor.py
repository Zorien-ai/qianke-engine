# -*- coding: utf-8 -*-
"""AI 全链路监控与 Token 计费。

设计原则：
1. 监控/账单是控制面，不放在企业数据空间里，避免企业库重建丢账单；
2. 所有查询必须由登录账号推导 tenant_id，前端不传 tenant；
3. 采集失败不能影响问答主链路，因此所有写入都吞异常并记日志；
4. Token 以 provider usage 为唯一事实；没有 usage 的调用只记 estimated，不扣费。
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from rag_demo import auth
from rag_demo.db.connection import current_dataset

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TRIAL_TOKENS = 200_000

_trace_id: ContextVar[str | None] = ContextVar("ai_trace_id", default=None)
_trace_tenant: ContextVar[str | None] = ContextVar("ai_trace_tenant", default=None)
_schema_ready = False

DDL = [
    """
    CREATE TABLE IF NOT EXISTS ai_traces (
        trace_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        dataset TEXT,
        entrypoint TEXT NOT NULL,
        account_id TEXT,
        status TEXT NOT NULL DEFAULT 'running',
        cache_hit BOOLEAN NOT NULL DEFAULT FALSE,
        guard_hit BOOLEAN NOT NULL DEFAULT FALSE,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ,
        total_ms INTEGER,
        first_token_ms INTEGER,
        prompt_tokens BIGINT NOT NULL DEFAULT 0,
        completion_tokens BIGINT NOT NULL DEFAULT 0,
        reasoning_tokens BIGINT NOT NULL DEFAULT 0,
        total_tokens BIGINT NOT NULL DEFAULT 0,
        cost_amount NUMERIC(14, 6) NOT NULL DEFAULT 0,
        meta JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS ai_traces_tenant_time ON ai_traces (tenant_id, started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS ai_spans (
        span_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        model TEXT,
        prompt_tokens BIGINT NOT NULL DEFAULT 0,
        completion_tokens BIGINT NOT NULL DEFAULT 0,
        reasoning_tokens BIGINT NOT NULL DEFAULT 0,
        total_tokens BIGINT NOT NULL DEFAULT 0,
        cost_amount NUMERIC(14, 6) NOT NULL DEFAULT 0,
        latency_ms INTEGER,
        status TEXT NOT NULL DEFAULT 'success',
        error_code TEXT,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        meta JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS ai_spans_trace ON ai_spans (trace_id, started_at)",
    """
    CREATE TABLE IF NOT EXISTS ai_usage_events (
        event_id TEXT PRIMARY KEY,
        idempotency_key TEXT UNIQUE NOT NULL,
        trace_id TEXT,
        tenant_id TEXT NOT NULL,
        dataset TEXT,
        feature TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_tokens BIGINT NOT NULL DEFAULT 0,
        completion_tokens BIGINT NOT NULL DEFAULT 0,
        reasoning_tokens BIGINT NOT NULL DEFAULT 0,
        total_tokens BIGINT NOT NULL DEFAULT 0,
        input_cost NUMERIC(14, 8) NOT NULL DEFAULT 0,
        output_cost NUMERIC(14, 8) NOT NULL DEFAULT 0,
        cost_amount NUMERIC(14, 6) NOT NULL DEFAULT 0,
        sales_amount NUMERIC(14, 6) NOT NULL DEFAULT 0,
        usage_source TEXT NOT NULL DEFAULT 'provider',
        status TEXT NOT NULL DEFAULT 'success',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ai_usage_tenant_time ON ai_usage_events (tenant_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS model_prices (
        model TEXT PRIMARY KEY,
        input_cost_per_1k NUMERIC(14, 8) NOT NULL DEFAULT 0,
        output_cost_per_1k NUMERIC(14, 8) NOT NULL DEFAULT 0,
        input_sale_per_1k NUMERIC(14, 8),
        output_sale_per_1k NUMERIC(14, 8),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS token_wallets (
        tenant_id TEXT PRIMARY KEY,
        tenant_name TEXT,
        balance_tokens BIGINT NOT NULL DEFAULT 0,
        frozen_tokens BIGINT NOT NULL DEFAULT 0,
        plan_name TEXT,
        plan_tokens BIGINT NOT NULL DEFAULT 0,
        plan_used_tokens BIGINT NOT NULL DEFAULT 0,
        period_start DATE,
        period_end DATE,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS token_transactions (
        id BIGSERIAL PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        tokens BIGINT NOT NULL,
        amount NUMERIC(14, 6) NOT NULL DEFAULT 0,
        order_id TEXT,
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS token_transactions_tenant ON token_transactions (tenant_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS token_packs (
        pack_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        tokens BIGINT NOT NULL,
        price NUMERIC(14, 2) NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        sort_order INT NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recharge_orders (
        order_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        pack_id TEXT NOT NULL,
        tokens BIGINT NOT NULL,
        amount NUMERIC(14, 2) NOT NULL,
        status TEXT NOT NULL DEFAULT 'paid',
        paid_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS recharge_orders_tenant ON recharge_orders (tenant_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS billing_invoices (
        invoice_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        order_id TEXT,
        period_start DATE,
        period_end DATE,
        tokens BIGINT NOT NULL DEFAULT 0,
        amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'issued',
        title TEXT,
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS billing_invoices_tenant ON billing_invoices (tenant_id, created_at DESC)",
]

SEED_PRICES = [
    # 内部成本价（元 / 1K tokens）；销售价留空，后续由管理端配置。
    ("deepseek-flash", 0.0005, 0.0010),
    ("deepseek-chat", 0.0010, 0.0020),
    ("deepseek-reasoner", 0.0020, 0.0080),
]

SEED_PACKS = [
    ("pack_1m", "1M Token 包", 1_000_000, 99.00, 1),
    ("pack_5m", "5M Token 包", 5_000_000, 399.00, 2),
    ("pack_20m", "20M Token 包", 20_000_000, 1299.00, 3),
]


def _connect():
    return psycopg2.connect(**auth.PG_CONFIG)


def ensure_schema(conn=None) -> None:
    global _schema_ready
    if _schema_ready:
        return
    own = conn is None
    if own:
        conn = _connect()
    cur = conn.cursor()
    try:
        for sql in DDL:
            cur.execute(sql)
        for model, cost_in, cost_out in SEED_PRICES:
            cur.execute(
                """INSERT INTO model_prices
                   (model, input_cost_per_1k, output_cost_per_1k)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (model) DO NOTHING""",
                (model, cost_in, cost_out),
            )
        for pack_id, name, tokens, price, sort_order in SEED_PACKS:
            cur.execute(
                """INSERT INTO token_packs (pack_id, name, tokens, price, sort_order)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (pack_id) DO NOTHING""",
                (pack_id, name, tokens, price, sort_order),
            )
        if own:
            conn.commit()
        else:
            # 调用方传进来的连接也要提交 DDL，否则 close 时建表事务会回滚。
            conn.commit()
        _schema_ready = True
    finally:
        cur.close()
        if own:
            conn.close()


def _safe(fn, *args, **kwargs):
    """监控写入不允许反噬业务。"""
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("监控写入失败，已忽略")
        return None


def tenant_of(dataset: str | None = None) -> str:
    return dataset or current_dataset() or "demo"


def set_trace_context(trace_id: str | None, tenant: str | None = None) -> None:
    _trace_id.set(trace_id)
    _trace_tenant.set(tenant)


def current_trace_id() -> str | None:
    return _trace_id.get()


def begin_trace(entrypoint: str, account: dict | None = None) -> str:
    trace_id = uuid.uuid4().hex
    tenant = tenant_of()
    set_trace_context(trace_id, tenant)
    _safe(_begin_trace, trace_id, tenant, entrypoint, (account or {}).get("username"))
    return trace_id


def _begin_trace(trace_id: str, tenant: str, entrypoint: str, account_id: str | None) -> None:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO ai_traces (trace_id, tenant_id, dataset, entrypoint, account_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (trace_id, tenant, tenant, entrypoint, account_id),
        )
        conn.commit()
    finally:
        conn.close()


def finish_trace(
    *,
    status: str = "success",
    cache_hit: bool = False,
    guard_hit: bool = False,
    total_ms: int | None = None,
    first_token_ms: int | None = None,
    meta: dict | None = None,
    trace_id: str | None = None,
) -> None:
    tid = trace_id or current_trace_id()
    if not tid:
        return
    _safe(_finish_trace, tid, status, cache_hit, guard_hit, total_ms, first_token_ms, meta or {})


def _finish_trace(tid, status, cache_hit, guard_hit, total_ms, first_token_ms, meta):
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE ai_traces
               SET status=%s, cache_hit=%s, guard_hit=%s, total_ms=%s,
                   first_token_ms=%s, finished_at=now(), meta=COALESCE(meta, '{}'::jsonb) || %s
               WHERE trace_id=%s""",
            (status, cache_hit, guard_hit, total_ms, first_token_ms, Json(meta), tid),
        )
        conn.commit()
    finally:
        conn.close()


def record_span(
    *,
    kind: str,
    name: str,
    latency_ms: int | None = None,
    status: str = "success",
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    reasoning_tokens: int = 0,
    cost_amount: float = 0.0,
    meta: dict | None = None,
    trace_id: str | None = None,
) -> None:
    tid = trace_id or current_trace_id()
    if not tid:
        return
    _safe(
        _record_span, tid, tenant_of(), kind, name, latency_ms, status,
        model, prompt_tokens, completion_tokens, reasoning_tokens, cost_amount, meta or {},
    )


def _record_span(tid, tenant, kind, name, latency_ms, status, model, p, c, r, cost, meta):
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO ai_spans
               (span_id, trace_id, tenant_id, kind, name, model, prompt_tokens,
                completion_tokens, reasoning_tokens, total_tokens, cost_amount,
                latency_ms, status, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                uuid.uuid4().hex, tid, tenant, kind, name, model, p, c, r,
                p + c, cost, latency_ms, status, Json(meta),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _price_for(cur, model: str) -> tuple[float, float, float | None, float | None]:
    cur.execute(
        """SELECT input_cost_per_1k, output_cost_per_1k,
                  input_sale_per_1k, output_sale_per_1k
           FROM model_prices WHERE model=%s""",
        (model,),
    )
    row = cur.fetchone()
    if row:
        return (
            float(row[0] or 0), float(row[1] or 0),
            float(row[2]) if row[2] is not None else None,
            float(row[3]) if row[3] is not None else None,
        )
    return 0.0, 0.0, None, None


def _ensure_wallet(cur, tenant: str, name: str | None = None) -> None:
    cur.execute(
        """INSERT INTO token_wallets
           (tenant_id, tenant_name, balance_tokens, plan_name, plan_tokens)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (tenant_id) DO NOTHING""",
        (tenant, name or tenant, TRIAL_TOKENS, "Trial", TRIAL_TOKENS),
    )


def record_llm_usage(
    *,
    model: str,
    usage: dict | None,
    feature: str = "llm",
    latency_ms: int | None = None,
    status: str = "success",
    usage_source: str = "provider",
) -> None:
    """记录一次 LLM 调用的 Token 与内部成本。没有 usage 时只记录估算占位。"""
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    reasoning = int(usage.get("reasoning_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    if total <= 0:
        return
    _safe(
        _record_llm_usage, model, feature, prompt, completion, reasoning,
        total, latency_ms, status, usage_source,
    )


def _record_llm_usage(model, feature, prompt, completion, reasoning, total, latency_ms, status, usage_source):
    tenant = tenant_of()
    tid = current_trace_id()
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor()
        in_cost, out_cost, in_sale, out_sale = _price_for(cur, model)
        cost = prompt / 1000 * in_cost + completion / 1000 * out_cost
        if in_sale is not None and out_sale is not None:
            sales = prompt / 1000 * in_sale + completion / 1000 * out_sale
        else:
            sales = 0.0
        _ensure_wallet(cur, tenant)
        cur.execute(
            """INSERT INTO ai_usage_events
               (event_id, idempotency_key, trace_id, tenant_id, dataset, feature, model,
                prompt_tokens, completion_tokens, reasoning_tokens, total_tokens,
                input_cost, output_cost, cost_amount, sales_amount, usage_source, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (idempotency_key) DO NOTHING""",
            (
                uuid.uuid4().hex,
                f"{tid or 'notrace'}:{tenant}:{uuid.uuid4().hex}",
                tid, tenant, tenant, feature, model,
                prompt, completion, reasoning, total,
                in_cost, out_cost, round(cost, 6), round(sales, 6),
                usage_source, status,
            ),
        )
        # 钱包按 billable token 扣减；余额不足不阻断问答，先记录欠费，后续可切换策略。
        if total > 0:
            cur.execute(
                """UPDATE token_wallets
                   SET balance_tokens = GREATEST(0, balance_tokens - %s),
                       plan_used_tokens = plan_used_tokens + %s,
                       updated_at = now()
                   WHERE tenant_id=%s""",
                (total, total, tenant),
            )
            cur.execute(
                """INSERT INTO token_transactions (tenant_id, kind, tokens, amount, note)
                   VALUES (%s, 'usage', %s, %s, %s)""",
                (tenant, -total, round(sales, 6), f"{feature} / {model}"),
            )
            if tid:
                cur.execute(
                    """UPDATE ai_traces
                       SET prompt_tokens=prompt_tokens+%s,
                           completion_tokens=completion_tokens+%s,
                           reasoning_tokens=reasoning_tokens+%s,
                           total_tokens=total_tokens+%s,
                           cost_amount=cost_amount+%s
                       WHERE trace_id=%s""",
                    (prompt, completion, reasoning, total, round(cost, 6), tid),
                )
        conn.commit()
    finally:
        conn.close()


def pin_trace(trace_id: str | None, tenant: str | None = None) -> None:
    """流式生成器每次恢复时重新设置上下文（与 pin_dataset 同理）。"""
    set_trace_context(trace_id, tenant)


# ==================== 查询 ====================

def _range_delta(value: str) -> timedelta:
    return {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}.get(value, timedelta(hours=24))


def _tenant_filter(tenant: str | None, admin: bool) -> tuple[str, list]:
    if admin and not tenant:
        return "", []
    return "WHERE tenant_id=%s", [tenant]


def overview(tenant: str, range_key: str = "24h", admin: bool = False) -> dict:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        since = datetime.now(timezone.utc) - _range_delta(range_key)
        where = "WHERE started_at >= %s"
        params: list[Any] = [since]
        if not admin:
            where += " AND tenant_id=%s"
            params.append(tenant)
        cur.execute(
            f"""SELECT COUNT(*) AS requests,
                       COUNT(*) FILTER (WHERE status='error') AS errors,
                       COUNT(*) FILTER (WHERE cache_hit) AS cache_hits,
                       COUNT(*) FILTER (WHERE guard_hit) AS guard_hits,
                       COALESCE(SUM(total_tokens), 0) AS tokens,
                       COALESCE(SUM(cost_amount), 0) AS cost,
                       COALESCE(AVG(total_ms), 0) AS avg_ms
                FROM ai_traces {where}""",
            params,
        )
        row = dict(cur.fetchone() or {})
        cur.execute(
            f"""SELECT COALESCE(SUM(total_tokens),0) AS tokens,
                       COALESCE(SUM(cost_amount),0) AS cost,
                       COALESCE(SUM(sales_amount),0) AS sales
                FROM ai_usage_events
                WHERE created_at >= %s""" + ("" if admin else " AND tenant_id=%s"),
            [since] + ([] if admin else [tenant]),
        )
        usage = dict(cur.fetchone() or {})
        cur.execute(
            f"""SELECT total_ms FROM ai_traces {where} AND total_ms IS NOT NULL ORDER BY total_ms ASC""",
            params,
        )
        latencies = [r["total_ms"] for r in cur.fetchall()]
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
        requests = int(row.get("requests") or 0)
        errors = int(row.get("errors") or 0)
        return {
            "range": range_key,
            "requests": requests,
            "errors": errors,
            "error_rate": round(errors / requests, 4) if requests else 0,
            "cache_hits": int(row.get("cache_hits") or 0),
            "cache_hit_rate": round(int(row.get("cache_hits") or 0) / requests, 4) if requests else 0,
            "guard_hits": int(row.get("guard_hits") or 0),
            "tokens": int(usage.get("tokens") or row.get("tokens") or 0),
            "cost": float(usage.get("cost") or row.get("cost") or 0),
            "sales": float(usage.get("sales") or 0),
            "avg_latency_ms": round(float(row.get("avg_ms") or 0)),
            "p95_latency_ms": int(p95 or 0),
        }
    finally:
        conn.close()


def timeseries(tenant: str, range_key: str = "24h", admin: bool = False) -> list[dict]:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor()
        since = datetime.now(timezone.utc) - _range_delta(range_key)
        bucket = "minute" if range_key == "1h" else "hour"
        where = f"WHERE created_at >= %s"
        params: list[Any] = [since]
        if not admin:
            where += " AND tenant_id=%s"
            params.append(tenant)
        cur.execute(
            f"""SELECT date_trunc('{bucket}', created_at) AS bucket,
                       COUNT(*) AS requests,
                       COALESCE(SUM(total_tokens),0) AS tokens,
                       COALESCE(SUM(cost_amount),0) AS cost,
                       COUNT(*) FILTER (WHERE status='error') AS errors
                FROM ai_usage_events {where}
                GROUP BY bucket ORDER BY bucket ASC""",
            params,
        )
        rows = cur.fetchall()
        return [
            {
                "time": row[0].strftime("%H:%M" if bucket == "minute" else "%m-%d %H:00"),
                "requests": int(row[1] or 0),
                "tokens": int(row[2] or 0),
                "cost": float(row[3] or 0),
                "errors": int(row[4] or 0),
            }
            for row in rows
        ]
    finally:
        conn.close()


def traces(tenant: str, limit: int = 30, admin: bool = False) -> list[dict]:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        where = "" if admin else "WHERE tenant_id=%s"
        params: list[Any] = [] if admin else [tenant]
        cur.execute(
            f"""SELECT trace_id, tenant_id, entrypoint, account_id, status, cache_hit,
                       guard_hit, started_at, total_ms, first_token_ms, total_tokens, cost_amount
                FROM ai_traces {where}
                ORDER BY started_at DESC LIMIT %s""",
            params + [min(100, max(1, limit))],
        )
        return [
            {
                **dict(row),
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "cost_amount": float(row["cost_amount"] or 0),
            }
            for row in cur.fetchall()
        ]
    finally:
        conn.close()


def trace_detail(tenant: str, trace_id: str, admin: bool = False) -> dict | None:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        where = "WHERE trace_id=%s" if admin else "WHERE trace_id=%s AND tenant_id=%s"
        params = [trace_id] if admin else [trace_id, tenant]
        cur.execute(f"SELECT * FROM ai_traces {where}", params)
        trace = cur.fetchone()
        if not trace:
            return None
        cur.execute("SELECT * FROM ai_spans WHERE trace_id=%s ORDER BY started_at ASC", (trace_id,))
        spans = []
        for row in cur.fetchall():
            d = dict(row)
            d["started_at"] = d["started_at"].isoformat() if d["started_at"] else None
            d["cost_amount"] = float(d["cost_amount"] or 0)
            d["total_tokens"] = int(d["total_tokens"] or 0)
            spans.append(d)
        result = dict(trace)
        result["started_at"] = result["started_at"].isoformat() if result["started_at"] else None
        result["finished_at"] = result["finished_at"].isoformat() if result["finished_at"] else None
        result["cost_amount"] = float(result["cost_amount"] or 0)
        result["spans"] = spans
        return result
    finally:
        conn.close()


# ==================== 钱包 / 充值 / 发票 ====================

def wallet(tenant: str, name: str | None = None) -> dict:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_wallet(cur, tenant, name)
        conn.commit()
        cur.execute("SELECT * FROM token_wallets WHERE tenant_id=%s", (tenant,))
        row = dict(cur.fetchone())
        if row["period_start"]:
            row["period_start"] = row["period_start"].isoformat()
        if row["period_end"]:
            row["period_end"] = row["period_end"].isoformat()
        row["updated_at"] = row["updated_at"].isoformat() if row["updated_at"] else None
        return row
    finally:
        conn.close()


def usage_summary(tenant: str, range_key: str = "30d", admin: bool = False) -> list[dict]:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor()
        since = datetime.now(timezone.utc) - timedelta(days=30 if range_key == "30d" else 1)
        where = "WHERE created_at >= %s AND " + ("" if admin else "tenant_id=%s AND ")
        if admin:
            where = "WHERE created_at >= %s"
            params = [since]
        else:
            where = "WHERE created_at >= %s AND tenant_id=%s"
            params = [since, tenant]
        cur.execute(
            f"""SELECT feature, model, COALESCE(SUM(total_tokens),0),
                       COALESCE(SUM(cost_amount),0), COALESCE(SUM(sales_amount),0), COUNT(*)
                FROM ai_usage_events {where}
                GROUP BY feature, model ORDER BY 3 DESC""",
            params,
        )
        return [
            {
                "feature": row[0], "model": row[1], "tokens": int(row[2] or 0),
                "cost": float(row[3] or 0), "sales": float(row[4] or 0),
                "calls": int(row[5] or 0),
            }
            for row in cur.fetchall()
        ]
    finally:
        conn.close()


def packs() -> list[dict]:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM token_packs WHERE active ORDER BY sort_order ASC, tokens ASC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def recharge(tenant: str, pack_id: str, name: str | None = None) -> dict:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM token_packs WHERE pack_id=%s AND active", (pack_id,))
        pack = cur.fetchone()
        if not pack:
            raise ValueError("Token 包不存在或已下架")
        _ensure_wallet(cur, tenant, name)
        order_id = "R" + uuid.uuid4().hex[:16].upper()
        cur.execute(
            """INSERT INTO recharge_orders (order_id, tenant_id, pack_id, tokens, amount, status, paid_at)
               VALUES (%s,%s,%s,%s,%s,'paid',now())""",
            (order_id, tenant, pack_id, pack["tokens"], pack["price"]),
        )
        cur.execute(
            "UPDATE token_wallets SET balance_tokens=balance_tokens+%s, updated_at=now() WHERE tenant_id=%s",
            (pack["tokens"], tenant),
        )
        cur.execute(
            """INSERT INTO token_transactions (tenant_id, kind, tokens, amount, order_id, note)
               VALUES (%s,'recharge',%s,%s,%s,%s)""",
            (tenant, pack["tokens"], pack["price"], order_id, pack["name"]),
        )
        # 演示环境自动开票；真实支付渠道接入后由支付回调触发。
        invoice_id = "INV" + uuid.uuid4().hex[:16].upper()
        cur.execute(
            """INSERT INTO billing_invoices
               (invoice_id, tenant_id, order_id, tokens, amount, status, title, note)
               VALUES (%s,%s,%s,%s,%s,'issued',%s,%s)""",
            (
                invoice_id, tenant, order_id, pack["tokens"], pack["price"],
                f"Token 充值 - {pack['name']}", "模拟支付自动开票",
            ),
        )
        conn.commit()
        return {
            "order_id": order_id, "invoice_id": invoice_id,
            "tokens": pack["tokens"], "amount": float(pack["price"]),
            "pack": dict(pack), "status": "paid",
        }
    finally:
        conn.close()


def invoices(tenant: str) -> list[dict]:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM billing_invoices WHERE tenant_id=%s ORDER BY created_at DESC", (tenant,))
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            d["amount"] = float(d["amount"] or 0)
            rows.append(d)
        return rows
    finally:
        conn.close()


def invoice(tenant: str, invoice_id: str) -> dict | None:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM billing_invoices WHERE invoice_id=%s AND tenant_id=%s",
            (invoice_id, tenant),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        d["amount"] = float(d["amount"] or 0)
        return d
    finally:
        conn.close()


def model_prices() -> list[dict]:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM model_prices ORDER BY model")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_model_prices(items: list[dict]) -> None:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor()
        for item in items:
            model = str(item.get("model") or "").strip()
            if not model:
                continue
            cur.execute(
                """INSERT INTO model_prices
                   (model, input_sale_per_1k, output_sale_per_1k, updated_at)
                   VALUES (%s,%s,%s,now())
                   ON CONFLICT (model) DO UPDATE SET
                     input_sale_per_1k=EXCLUDED.input_sale_per_1k,
                     output_sale_per_1k=EXCLUDED.output_sale_per_1k,
                     updated_at=now()""",
                (model, item.get("input_sale_per_1k"), item.get("output_sale_per_1k")),
            )
        conn.commit()
    finally:
        conn.close()


def admin_tenants() -> list[dict]:
    conn = _connect()
    ensure_schema(conn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT t.tenant_id,
                      COALESCE(w.tenant_name, t.tenant_id) AS name,
                      COUNT(*) AS requests,
                      COALESCE(SUM(t.total_tokens),0) AS tokens,
                      COALESCE(SUM(t.cost_amount),0) AS cost,
                      MAX(t.started_at) AS last_seen,
                      COALESCE(w.balance_tokens,0) AS balance_tokens
               FROM ai_traces t LEFT JOIN token_wallets w ON w.tenant_id=t.tenant_id
               GROUP BY t.tenant_id, w.tenant_name, w.balance_tokens
               ORDER BY tokens DESC LIMIT 100"""
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["last_seen"] = d["last_seen"].isoformat() if d["last_seen"] else None
            d["cost"] = float(d["cost"] or 0)
            rows.append(d)
        return rows
    finally:
        conn.close()
