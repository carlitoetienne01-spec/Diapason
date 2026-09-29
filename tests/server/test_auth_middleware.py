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

PREFIXES_VIE = ("/v1/vie", "/v1/succes")


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

    # Le domaine vie sous ses deux préfixes (25/09/2026) : le nom neuf et
    # l'alias des clients d'avant le renommage.
    for prefixe in PREFIXES_VIE:

        @app.get(f"{prefixe}/projects")
        async def vie_projects():
            return {"projects": [], "count": 0}

        @app.get(f"{prefixe}/tasks")
        async def vie_tasks():
            return {"tasks": [], "count": 0}

        @app.get(f"{prefixe}/sync/status")
        async def vie_sync_status():
            return {"role": "ready"}

        @app.post(f"{prefixe}/sync/pair")
        async def vie_sync_pair():
            return {"ok": True}

        @app.post(f"{prefixe}/sync/exchange")
        async def vie_sync_exchange():
            return {"ok": True}

    @app.post("/v1/chat/completions")
    async def chat_completions():
        return {"ok": True}

    @app.get("/v1/conversations")
    async def conversations():
        return {"conversations": [], "deleted": []}

    @app.get("/v1/study/sessions")
    @app.get("/v1/study/materials")
    @app.get("/v1/study/sessions/{identifiant}")
    async def etudes(identifiant: str = ""):
        return {"id": identifiant}

    @app.post("/v1/study/sessions")
    async def preparer_etude():
        return {"ok": True}

    @app.get("/v1/approvals/pending")
    async def approvals_pending():
        return {"actions": [], "count": 0}

    @app.post("/v1/approvals/{action_id}/approve")
    async def approve(action_id: str):
        return {"status": "approved", "id": action_id}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app("oj_sk_test123"))


class TestAuthMiddleware:
    def test_la_reprise_detude_ne_partage_pas_le_seau_des_ecritures(self):
        """§100 : le panneau ne doit pas échouer à l'ouverture pendant la voix."""
        client = TestClient(_make_app("cle-etude", requests_per_minute=1, burst_size=1))
        entetes = {"Authorization": "Bearer cle-etude"}
        assert client.get("/v1/models", headers=entetes).status_code == 200
        assert client.get("/v1/models", headers=entetes).status_code == 429
        for route in ("sessions", "materials", "sessions/exemple"):
            assert client.get(f"/v1/study/{route}", headers=entetes).status_code == 200
            assert client.get(f"/v1/study/{route}").status_code == 401
        assert client.post("/v1/study/sessions", headers=entetes).status_code == 429
        codes = [
            client.get("/v1/study/sessions", headers=entetes).status_code
            for _ in range(30)
        ]
        assert 429 in codes, "les lectures ont leur propre plafond, pas une exemption"

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

    @pytest.mark.parametrize("prefixe", PREFIXES_VIE)
    def test_vie_routes_are_authenticated_but_not_rate_limited(self, prefixe):
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=1, burst_size=1)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}

        # Exhausting the shared bucket must not block local vie CRUD.
        assert client.get("/v1/models", headers=headers).status_code == 200
        assert client.get("/v1/models", headers=headers).status_code == 429
        assert client.get(f"{prefixe}/projects", headers=headers).status_code != 429
        assert client.get(f"{prefixe}/projects").status_code == 401

    @pytest.mark.parametrize("prefixe", PREFIXES_VIE)
    def test_soixante_requetes_rapides_sans_un_429(self, prefixe):
        """Étape 4 du plan de la phase 1b : un préfixe oublié dans
        l'exemption, et l'autosave prend des 429 que le cache masque."""
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=10, burst_size=10)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}
        codes = [
            client.get(f"{prefixe}/tasks", headers=headers).status_code
            for _ in range(60)
        ]
        assert codes.count(429) == 0, (
            f"{codes.count(429)} réponses 429 sur {prefixe}/tasks : le domaine "
            "vie doit rester hors du limiteur"
        )

    @pytest.mark.parametrize("prefixe", PREFIXES_VIE)
    @pytest.mark.parametrize("porte", ["pair", "exchange"])
    def test_la_synchro_sans_cle_garde_un_limiteur(self, prefixe, porte):
        """/sync/pair et /sync/exchange se passent de la clé : sans seau,
        soixante essais de code d'appairage d'affilée passaient tous
        (constaté le 25/09/2026, malgré un commentaire qui disait le
        contraire)."""
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=10, burst_size=10)
        )
        codes = [client.post(f"{prefixe}/sync/{porte}").status_code for _ in range(60)]
        assert 429 in codes, f"{prefixe}/sync/{porte} n'est limité par rien"

    @pytest.mark.parametrize("prefixe", PREFIXES_VIE)
    def test_la_synchro_avec_cle_garde_le_seau_commun(self, prefixe):
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=10, burst_size=10)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}
        codes = [
            client.get(f"{prefixe}/sync/status", headers=headers).status_code
            for _ in range(60)
        ]
        assert 429 in codes, f"{prefixe}/sync/status doit rester limité"

    def test_un_prefixe_voisin_n_est_pas_exempte(self):
        """« /v1/succes » sans barre finale exemptait aussi « /v1/successeur »."""
        from diapason.server.auth_middleware import _VIE_SANS_LIMITE

        assert not "/v1/successeur".startswith(_VIE_SANS_LIMITE)
        assert not "/v1/viennoiserie".startswith(_VIE_SANS_LIMITE)

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

    def test_la_cloche_sondee_chaque_seconde_ne_vide_pas_le_seau(self):
        """Phase 5 du plan mobile (26/09/2026) : la cloche relit la liste
        chaque seconde tant qu'une demande attend — 60 par minute, le seau
        commun entier. Au banc d'émulateur, la notification touchée ouvrait
        la cloche sur un 429. La lecture n'est jamais limitée, et jamais
        sans la clé ; la décision, elle, garde le seau."""
        client = TestClient(
            _make_app("oj_sk_test123", requests_per_minute=10, burst_size=10)
        )
        headers = {"Authorization": "Bearer oj_sk_test123"}
        codes = [
            client.get("/v1/approvals/pending", headers=headers).status_code
            for _ in range(60)
        ]
        assert codes.count(429) == 0, (
            f"{codes.count(429)} réponses 429 sur la liste des approbations"
        )
        assert client.get("/v1/approvals/pending").status_code == 401, (
            "sans clé, le mur d'authentification doit rester fermé"
        )
        decisions = [
            client.post("/v1/approvals/a1/approve", headers=headers).status_code
            for _ in range(60)
        ]
        assert 429 in decisions, "approuver doit rester limité"

    @pytest.mark.parametrize("prefixe", PREFIXES_VIE)
    def test_vie_sync_pair_and_exchange_skip_api_key(self, client, prefixe):
        assert client.post(f"{prefixe}/sync/pair").status_code == 200
        assert client.post(f"{prefixe}/sync/exchange").status_code == 200
        assert client.get(f"{prefixe}/projects").status_code == 401
        assert client.get(f"{prefixe}/sync/status").status_code == 401, (
            "seules pair et exchange se passent de la clé"
        )


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
