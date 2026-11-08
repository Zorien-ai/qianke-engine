"""安全响应头测试。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from rag_demo.api.security import (
    LoginRateLimiter,
    cookie_secure,
    install_csp_report,
    install_security_headers,
)


def test_security_headers_present():
    app = FastAPI()
    install_security_headers(app)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in response.headers["Permissions-Policy"]
    assert "Content-Security-Policy-Report-Only" in response.headers
    assert "default-src 'self'" in response.headers["Content-Security-Policy-Report-Only"]
    assert "report-uri /security/csp-report" in response.headers["Content-Security-Policy-Report-Only"]
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_only_on_https():
    app = FastAPI()
    install_security_headers(app)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app, base_url="https://testserver")
    response = client.get("/ping")
    assert response.headers["Strict-Transport-Security"].startswith("max-age=31536000")


def test_login_rate_limiter_blocks_and_resets():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)
    key = "127.0.0.1:alice"
    assert limiter.retry_after(key) == 0
    limiter.record_failure(key)
    assert limiter.retry_after(key) == 0
    limiter.record_failure(key)
    assert limiter.retry_after(key) > 0
    limiter.reset(key)
    assert limiter.retry_after(key) == 0


def test_cookie_secure_follows_scheme_and_proxy_header():
    def request(scheme: str, headers=None) -> Request:
        return Request({
            "type": "http", "scheme": scheme, "http_version": "1.1",
            "method": "GET", "path": "/", "raw_path": b"/", "query_string": b"",
            "headers": headers or [], "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80), "root_path": "",
        })

    assert cookie_secure(request("https")) is True
    assert cookie_secure(request("http")) is False
    assert cookie_secure(request("http", [(b"x-forwarded-proto", b"https")])) is True


def test_csp_report_endpoint_accepts_payload():
    app = FastAPI()
    install_security_headers(app)
    install_csp_report(app)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    client = TestClient(app)
    response = client.post(
        "/security/csp-report",
        json={"csp-report": {"blocked-uri": "https://evil.example"}},
    )
    assert response.status_code == 204
