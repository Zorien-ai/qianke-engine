"""最小安全响应头、CSP 上报与登录限流。"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)


class LoginRateLimiter:
    """单进程滑动窗口限流；多进程部署需换成 Redis/PG。"""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._hits[key] = [ts for ts in self._hits.get(key, []) if ts >= cutoff]
        if not self._hits[key]:
            self._hits.pop(key, None)

    def retry_after(self, key: str) -> int:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now)
            hits = self._hits.get(key, [])
            if len(hits) < self.max_attempts:
                return 0
            return max(1, int(self.window_seconds - (now - hits[0])) + 1)

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now)
            self._hits[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


LOGIN_RATE_LIMITER = LoginRateLimiter()


class PostgresLoginRateLimiter:
    """PostgreSQL 固定窗口限流，支持多进程/多实例共享。"""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300,
                 schema: str | None = None) -> None:
        from rag_demo.control.settings import pg_settings

        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self.settings = pg_settings(schema=schema)
        self.schema = self.settings["schema"]
        self._ensure_schema()

    def _connect(self):
        import psycopg2

        return psycopg2.connect(
            host=self.settings["host"],
            port=self.settings["port"],
            user=self.settings["user"],
            password=self.settings["password"],
            dbname=self.settings["dbname"],
            connect_timeout=self.settings.get("connect_timeout", 5),
        )

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self.schema}.c_login_attempt ("
                    "attempt_key TEXT PRIMARY KEY, window_start DOUBLE PRECISION NOT NULL, "
                    "attempts INTEGER NOT NULL DEFAULT 0, updated_at DOUBLE PRECISION NOT NULL)"
                )
                cur.execute(
                    f"DELETE FROM {self.schema}.c_login_attempt WHERE updated_at < %s",
                    (time.time() - 86400,),
                )
            conn.commit()
        finally:
            conn.close()

    def retry_after(self, key: str) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT window_start, attempts FROM {self.schema}.c_login_attempt "
                    "WHERE attempt_key = %s",
                    (str(key),),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return 0
        elapsed = time.time() - float(row[0])
        if elapsed >= self.window_seconds or int(row[1]) < self.max_attempts:
            return 0
        return max(1, int(math.ceil(self.window_seconds - elapsed)))

    def record_failure(self, key: str) -> None:
        now = time.time()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self.schema}.c_login_attempt"
                    "(attempt_key, window_start, attempts, updated_at) "
                    "VALUES (%s, %s, 1, %s) ON CONFLICT (attempt_key) DO UPDATE SET "
                    "attempts = CASE WHEN EXCLUDED.window_start - c_login_attempt.window_start >= %s "
                    "THEN 1 ELSE c_login_attempt.attempts + 1 END, "
                    "window_start = CASE WHEN EXCLUDED.window_start - c_login_attempt.window_start >= %s "
                    "THEN EXCLUDED.window_start ELSE c_login_attempt.window_start END, "
                    "updated_at = EXCLUDED.updated_at",
                    (str(key), now, now, self.window_seconds, self.window_seconds),
                )
            conn.commit()
        finally:
            conn.close()

    def reset(self, key: str) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.schema}.c_login_attempt WHERE attempt_key = %s",
                    (str(key),),
                )
            conn.commit()
        finally:
            conn.close()


def _build_login_rate_limiter():
    mode = (os.environ.get("QIANKE_LOGIN_RATE_BACKEND") or "").strip().lower()
    control = (os.environ.get("QIANKE_CONTROL_BACKEND") or "").strip().lower()
    if mode == "memory" or (not mode and control not in {"postgres", "postgresql", "pg"}):
        return LoginRateLimiter()
    try:
        limiter = PostgresLoginRateLimiter()
        logger.info("登录限流使用 PostgreSQL 分布式窗口")
        return limiter
    except Exception as exc:  # noqa: BLE001 数据库不可用时退回单进程
        logger.warning("PostgreSQL 登录限流不可用，回退内存版：%s", exc)
        return LoginRateLimiter()


LOGIN_RATE_LIMITER = _build_login_rate_limiter()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        headers.setdefault(
            "Content-Security-Policy-Report-Only",
            "default-src 'self'; img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "connect-src 'self' ws: wss: https:; frame-ancestors 'self'; base-uri 'self'; "
            "report-uri /security/csp-report",
        )
        if request.url.scheme == "https":
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def install_security_headers(app: FastAPI) -> None:
    app.add_middleware(SecurityHeadersMiddleware)


_csp_lock = threading.Lock()
_csp_window_start = 0.0
_csp_count = 0
_CSP_MAX_PER_MINUTE = 120


def install_csp_report(app: FastAPI) -> None:
    @app.post("/security/csp-report", status_code=204, include_in_schema=False)
    async def csp_report(request: Request) -> Response:
        global _csp_window_start, _csp_count
        raw = await request.body()
        now = time.monotonic()
        should_log = False
        with _csp_lock:
            if now - _csp_window_start >= 60:
                _csp_window_start = now
                _csp_count = 0
            _csp_count += 1
            should_log = _csp_count <= _CSP_MAX_PER_MINUTE
        if should_log:
            text = raw[:2000].decode("utf-8", errors="replace")
            logger.warning("CSP violation: %s", text)
        return Response(status_code=204)
