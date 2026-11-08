"""生产预检：一次检查 PG 控制面、队列、C 端、监控、域名与安全基线。

用法：
    python scripts/production_preflight.py
    python scripts/production_preflight.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

import psycopg2

from rag_demo.control.settings import pg_settings

API = "http://127.0.0.1:8000"
DOMAIN = "https://qianke.qiankeagent.com"


def _http(url: str, timeout: float = 10.0) -> tuple[int, str]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "qianke-preflight/1.0 (+https://qianke.qiankeagent.com)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _db():
    settings = pg_settings()
    return psycopg2.connect(
        host=settings["host"], port=settings["port"], user=settings["user"],
        password=settings["password"], dbname=settings["dbname"], connect_timeout=5,
    )


def _table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    )
    return cur.fetchone() is not None


def _count(cur, schema: str, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
    return int(cur.fetchone()[0])


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def run() -> dict:
    checks: list[dict] = []
    ready_status, ready_body = _http(f"{API}/ready")
    checks.append(_check("api_ready", ready_status == 200 and '"status":"ok"' in ready_body,
                         f"{ready_status} {ready_body[:120]}"))
    domain_status, domain_body = _http(f"{DOMAIN}/ready")
    checks.append(_check("domain_ready", domain_status == 200 and '"status":"ok"' in domain_body,
                         f"{domain_status} {domain_body[:120]}"))

    try:
        conn = _db()
        try:
            with conn.cursor() as cur:
                control_schema = pg_settings()["schema"]
                tables = ["sa_thread", "sa_work_item", "sa_approval", "c_order", "c_product",
                          "c_login_attempt", "c_policy_audit_anchor"]
                missing = [t for t in tables if not _table_exists(cur, control_schema, t)]
                counts = {t: _count(cur, control_schema, t) for t in tables if t not in missing}
                checks.append(_check("control_tables", not missing,
                                     f"missing={missing} " + " ".join(f"{k}={v}" for k, v in counts.items())))
                queue_schema = "sa_queue"
                queue_exists = _table_exists(cur, queue_schema, "sa_job")
                queue_counts = {}
                if queue_exists:
                    cur.execute(f"SELECT status, COUNT(*) FROM {queue_schema}.sa_job GROUP BY status")
                    queue_counts = {str(status): int(n) for status, n in cur.fetchall()}
                checks.append(_check("queue_table", queue_exists,
                                     f"schema={queue_schema} counts={queue_counts}"))
                checks.append(_check("c_end_data", counts.get("c_product", 0) > 0 and counts.get("c_order", 0) > 0,
                                     f"products={counts.get('c_product')} orders={counts.get('c_order')}"))
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("postgres", False, f"{type(exc).__name__}: {exc}"))

    prom_status, prom_body = _http("http://127.0.0.1:19090/-/ready")
    checks.append(_check("prometheus_ready", prom_status == 200, f"{prom_status} {prom_body[:80]}"))
    targets_status, targets_body = _http("http://127.0.0.1:19090/api/v1/targets")
    target_up = targets_status == 200 and "host.docker.internal:8000" in targets_body and '"health":"up"' in targets_body
    checks.append(_check("prometheus_target", target_up, f"{targets_status} qianke_target_up={target_up}"))
    grafana_status, _ = _http("http://127.0.0.1:3000/api/health")
    checks.append(_check("grafana_health", grafana_status == 200, str(grafana_status)))
    alert_status, alert_body = _http("http://127.0.0.1:19093/-/ready")
    checks.append(_check("alertmanager_ready", alert_status == 200, f"{alert_status} {alert_body[:40]}"))

    header_status, _ = _http(f"{DOMAIN}/health")
    # urllib 不暴露响应头，单独用 http.client 取一次头
    import http.client
    from urllib.parse import urlparse

    parsed = urlparse(f"{DOMAIN}/health")
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=10)
    try:
        conn.request("GET", parsed.path, headers={"User-Agent": "qianke-preflight/1.0"})
        response = conn.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        response.read()
    finally:
        conn.close()
    csp = headers.get("content-security-policy-report-only", "")
    checks.append(_check(
        "security_headers",
        header_status == 200
        and "max-age=" in headers.get("strict-transport-security", "")
        and "report-uri /security/csp-report" in csp
        and headers.get("x-frame-options", "").upper() == "SAMEORIGIN",
        f"hsts={bool(headers.get('strict-transport-security'))} csp_report_uri={'/security/csp-report' in csp} "
        f"x_frame={headers.get('x-frame-options')}",
    ))
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["checks"]:
            print(("PASS" if item["ok"] else "FAIL"), item["name"], "-", item["detail"])
        print("OVERALL", "PASS" if result["ok"] else "FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
