"""安全响应头测试。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_demo.api.security import install_security_headers


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
