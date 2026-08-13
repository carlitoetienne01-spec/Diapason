"""Tests for API key authentication middleware."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.server.auth_middleware import AuthMiddleware, ensure_local_api_key


def _make_app(api_key: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=api_key)

    @app.get("/v1/models")
    async def models():
        return {"models": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/webhooks/twilio")
    async def twilio_webhook():
        return {"status": "received"}

    @app.get("/metrics")
    async def metrics():
        return {"requests": 0}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app("oj_sk_test123"))


class TestAuthMiddleware:
    def test_rejects_missing_auth_header(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert "missing" in resp.json()["detail"].lower()

    def test_rejects_wrong_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_accepts_valid_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer oj_sk_test123"},
        )
        assert resp.status_code == 200

    def test_health_exempt(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_webhooks_exempt(self, client):
        resp = client.post("/webhooks/twilio")
        assert resp.status_code == 200

    def test_metrics_requires_auth(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 401

    def test_metrics_accepts_valid_key(self, client):
        resp = client.get("/metrics", headers={"Authorization": "Bearer oj_sk_test123"})
        assert resp.status_code == 200

    def test_no_key_configured_allows_all(self):
        client = TestClient(_make_app(""))
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        assert client.get("/metrics").status_code == 200


class TestLocalApiKeyProvisioning:
    def test_generates_and_reuses_owner_only_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "diapason.server.auth_middleware.get_config_dir", lambda: tmp_path
        )

        generated, path = ensure_local_api_key()
        reused, reused_path = ensure_local_api_key()

        assert len(generated.encode("utf-8")) >= 32
        assert reused == generated
        assert reused_path == path
        assert path is not None
        assert path.stat().st_mode & 0o777 == 0o600

    def test_rejects_short_explicit_key(self):
        with pytest.raises(ValueError, match="at least 32 bytes"):
            ensure_local_api_key("too-short")

    def test_refuses_symlink_key_file(self, tmp_path, monkeypatch):
        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        target = tmp_path / "target"
        target.write_text("x" * 40)
        try:
            (auth_dir / "local_api_key").symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is not permitted on this platform")
        monkeypatch.setattr(
            "diapason.server.auth_middleware.get_config_dir", lambda: tmp_path
        )

        with pytest.raises((OSError, RuntimeError)):
            ensure_local_api_key()
