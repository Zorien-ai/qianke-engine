"""最小安全响应头、CSP 上报与登录限流。"""
from __future__ import annotations

import logging
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
