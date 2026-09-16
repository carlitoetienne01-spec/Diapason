"""Tests for API key authentication middleware."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from diapason.server.auth_middleware import (
    AuthMiddleware,
    RateLimitMiddleware,
    ensure_local_api_key,
)


def _make_app(
    api_key: str, *, requests_per_minute: int = 600, burst_size: int = 100
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=requests_per_minute,
        burst_size=burst_size,
    )
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

    @app.get("/v1/voice/live/health")
    async def voice_health():
        return {"available": True}

    @app.get("/v1/succes/projects")
    async def succes_projects():
        return {"projects": [], "count": 0}

    @app.post("/v1/succes/sync/pair")
    async def succes_sync_pair():
        return {"ok": True}

    @app.post("/v1/succes/sync/exchange")
    async def succes_sync_exchange():
        return {"ok": True}

    @app.post("/v1/chat/completions")
    async def chat_completions():
        return {"ok": True}

    @app.get("/v1/conversations")
    async def conversations():
        return {"conversations": [], "deleted": []}

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

    def test_tauri_cors_preflight_reaches_cors_before_auth(self, client):
        resp = client.options(
            "/v1/voice/live/health",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "tauri://localhost"
        assert "authorization" in resp.headers["access-control-allow-headers"].lower()

    def test_voice_readiness_is_authenticated_but_not_rate_limited(self):
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=1, burst_size=1)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}

        assert client.get("/v1/voice/live/health", headers=headers).status_code == 200
        assert client.get("/v1/voice/live/health", headers=headers).status_code == 200
        assert client.get("/v1/voice/live/health").status_code == 401

    def test_succes_routes_are_authenticated_but_not_rate_limited(self):
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=1, burst_size=1)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}

        # Exhausting the shared bucket must not block local Succès CRUD.
        assert client.get("/v1/models", headers=headers).status_code == 200
        assert client.get("/v1/models", headers=headers).status_code == 429
        assert client.get("/v1/succes/projects", headers=headers).status_code != 429
        assert client.get("/v1/succes/projects").status_code == 401

    def test_le_chat_est_authentifie_mais_jamais_limite(self):
        """§82/§100 — le mini-panneau de la réglette est une 2e instance du
        bundle (même adresse, même clé, même seau) : sa rafale de démarrage
        vidait le seau commun et le message tapé rebondissait « 429 » en 8 ms
        (16 sept. 2026). La conversation ne doit jamais être limitée ; elle
        reste derrière le mur de la clé."""
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=1, burst_size=1)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}

        # Le seau partagé est vidé par une autre route…
        assert client.get("/v1/models", headers=headers).status_code == 200
        assert client.get("/v1/models", headers=headers).status_code == 429
        # … et la conversation passe quand même, mais jamais sans la clé.
        reponse = client.post("/v1/chat/completions", headers=headers)
        assert reponse.status_code != 429, (
            "le message tapé ne doit pas rebondir sur le limiteur"
        )
        assert client.post("/v1/chat/completions").status_code == 401, (
            "sans clé, le mur d'authentification doit rester fermé"
        )

    def test_la_sync_des_conversations_est_authentifiee_mais_jamais_limitee(self):
        """§100 — le moteur de sync tire toutes les 10 s et pousse à chaque
        mutation ; pendant un streaming les poussées débordent le seau
        partagé (60/min) et un 429 fait diverger les deux vues EN SILENCE
        (16 sept. 2026). Jamais limité, mais jamais sans la clé."""
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=1, burst_size=1)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}

        # Le seau partagé est vidé par une autre route…
        assert client.get("/v1/models", headers=headers).status_code == 200
        assert client.get("/v1/models", headers=headers).status_code == 429
        # … et la synchronisation passe quand même, mais jamais sans la clé.
        assert client.get("/v1/conversations", headers=headers).status_code != 429, (
            "une poussée de sync ne doit jamais rebondir sur le limiteur"
        )
        assert client.get("/v1/conversations").status_code == 401, (
            "sans clé, le mur d'authentification doit rester fermé"
        )

    def test_succes_sync_pair_and_exchange_skip_api_key(self, client):
        assert client.post("/v1/succes/sync/pair").status_code == 200
        assert client.post("/v1/succes/sync/exchange").status_code == 200
        assert client.get("/v1/succes/projects").status_code == 401


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


def test_les_routes_oauth_naviguees_passent_sans_cle():
    """La fenêtre OAuth et le retour de Google ne peuvent pas porter la clé
    locale — ces deux routes GET passent, tout le reste de /v1/connectors
    reste derrière le mur (24 août 2026)."""
    from diapason.server.auth_middleware import AuthMiddleware

    exige = AuthMiddleware._requires_auth
    assert not exige("/v1/connectors/gmail/oauth/start")
    assert not exige("/v1/connectors/gcalendar/oauth/callback")
    assert exige("/v1/connectors")
    assert exige("/v1/connectors/gmail/sync")
    assert exige("/v1/connectors/gmail/oauth/callback/extra")
