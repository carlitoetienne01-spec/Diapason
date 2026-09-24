"""Les routes locales ``/v1/account/*`` : statuts, seau, montage, journaux.

Conception : ``docs/development/compte-chiffre.md`` §3.8 (routes locales,
« jamais de 401 », seau propre), §3.7 et l'étape 8 du §6.

Le serveur de comptes est ``diapason_comptes`` en mémoire derrière un
``httpx.MockTransport`` (``tests/compte/_banc.py``) : aucun envoi réseau
réel. Aucun test de composant React ici — ce sont les routes Python.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.server.auth_middleware import (  # noqa: E402
    AuthMiddleware,
    RateLimitMiddleware,
)
from diapason.server.compte_routes import (  # noqa: E402
    AccesCompte,
    create_compte_router,
)
from tests.compte._banc import (  # noqa: E402
    EMAIL,
    MDP,
    MDP_2,
    Vps,
    appareil,
    argon_rapide,
    extrait,
)


@pytest.fixture(autouse=True)
def _argon(monkeypatch):
    argon_rapide(monkeypatch)


@pytest.fixture
def vps(tmp_path):
    serveur = Vps(tmp_path / "vps")
    yield serveur
    serveur.fermer()


def _app_locale(service) -> TestClient:
    app = FastAPI()
    app.include_router(create_compte_router(AccesCompte(lambda: service)))
    return TestClient(app)


def _inscrire_par_http(client: TestClient, vps: Vps, mot_de_passe: str = MDP) -> dict:
    vps.plus_tard()
    avant = vps.nombre(EMAIL, "code_inscription")
    assert (
        client.post(
            "/v1/account/signup/start", json={"email": EMAIL, "termsAccepted": True}
        ).status_code
        == 200
    )
    code = vps.code(EMAIL, "code_inscription", avant + 1)
    assert (
        client.post("/v1/account/signup/verify", json={"code": code}).status_code == 200
    )
    rendu = client.post(
        "/v1/account/signup/prepare", json={"password": mot_de_passe, "remember": False}
    ).json()
    fin = client.post(
        "/v1/account/signup/complete", json={"recoveryExcerpt": extrait(rendu)}
    )
    assert fin.status_code == 200, fin.text
    return fin.json()


# Chaque route, avec un corps plausible : le balayage ne cherche pas le bon
# résultat, il cherche le 401 qui ne doit jamais sortir.
ROUTES = [
    ("GET", "/v1/account/status", None),
    ("POST", "/v1/account/signup/start", {"email": EMAIL, "termsAccepted": True}),
    ("POST", "/v1/account/signup/verify", {"code": "123456"}),
    ("POST", "/v1/account/signup/prepare", {"password": MDP, "remember": False}),
    ("POST", "/v1/account/signup/complete", {"skipRecovery": True}),
    ("POST", "/v1/account/login", {"email": EMAIL, "password": MDP_2}),
    ("POST", "/v1/account/unlock", {"password": MDP_2}),
    ("POST", "/v1/account/lock", {}),
    ("POST", "/v1/account/password", {"currentPassword": MDP, "newPassword": MDP_2}),
    ("POST", "/v1/account/password/forgotten-here/code", {}),
    (
        "POST",
        "/v1/account/password/forgotten-here",
        {"code": "123456", "newPassword": MDP_2},
    ),
    (
        "POST",
        "/v1/account/recover",
        {"email": EMAIL, "recoveryKey": "0" * 32, "newPassword": MDP_2},
    ),
    ("POST", "/v1/account/recovery-key", {"password": MDP}),
    ("POST", "/v1/account/recovery-key/confirm", {"recoveryExcerpt": ["0000", "0000"]}),
    ("POST", "/v1/account/recovery-key/remove", {"password": MDP}),
    ("POST", "/v1/account/reset/request", {"email": EMAIL}),
    ("POST", "/v1/account/reset/confirm", {"email": EMAIL, "code": "123456"}),
    ("POST", "/v1/account/reset/cancel", {}),
    (
        "POST",
        "/v1/account/reset/complete",
        {"email": EMAIL, "code": "123456", "newPassword": MDP_2},
    ),
    ("GET", "/v1/account/devices", None),
    ("POST", "/v1/account/devices/inconnue/disconnect", {"password": MDP}),
    ("POST", "/v1/account/sync/consent", {}),
    ("POST", "/v1/account/sync-now", {}),
    ("POST", "/v1/account/onboarding/done", {}),
    ("POST", "/v1/account/logout", {"eraseLocalData": False}),
    ("POST", "/v1/account/delete", {"password": MDP_2, "eraseLocalData": False}),
]


def _balayer(client: TestClient) -> dict[str, int]:
    statuts = {}
    for methode, chemin, corps in ROUTES:
        reponse = client.request(methode, chemin, json=corps)
        assert reponse.status_code != 401, (
            f"{methode} {chemin} a rendu 401 : apiFetch rafraîchirait la clé "
            "locale en boucle (§3.7)"
        )
        statuts[chemin] = reponse.status_code
    return statuts


class TestJamaisDe401:
    """§3.8 : « jamais de 401 : un compte verrouillé renvoie 423
    accountLocked, les autres cas 409 ». ``apiFetch`` rejoue tout 401 en
    rafraîchissant la clé d'API locale (``api.ts:191-201``)."""

    def test_sans_compte_aucune_route_ne_rend_401(self, vps, tmp_path):
        service = appareil(vps, tmp_path / "a")
        _balayer(_app_locale(service))
        service.fermer()

    def test_verrouille_rend_423(self, vps, tmp_path):
        service = appareil(vps, tmp_path / "a")
        client = _app_locale(service)
        _inscrire_par_http(client, vps)
        assert client.post("/v1/account/lock", json={}).status_code == 200
        for chemin, corps in (
            ("/v1/account/password", {"currentPassword": MDP, "newPassword": MDP_2}),
            ("/v1/account/password/forgotten-here/code", {}),
            ("/v1/account/recovery-key", {"password": MDP}),
            ("/v1/account/recovery-key/remove", {"password": MDP}),
        ):
            reponse = client.post(chemin, json=corps)
            assert reponse.status_code == 423, f"{chemin} verrouillé : {reponse.text}"
            assert reponse.json()["error"]["code"] == "accountLocked"
        assert client.get("/v1/account/devices").status_code == 423
        _balayer(client)
        service.fermer()

    def test_une_session_revoquee_rend_409_session_expired(self, vps, tmp_path):
        """§3.7 : un 401 du VPS devient 409 ``sessionExpired`` — le 401 du
        serveur de comptes n'est PAS celui de la clé locale."""
        a = appareil(vps, tmp_path / "a")
        client_a = _app_locale(a)
        _inscrire_par_http(client_a, vps)
        b = appareil(vps, tmp_path / "b")
        client_b = _app_locale(b)
        assert (
            client_b.post(
                "/v1/account/login", json={"email": EMAIL, "password": MDP}
            ).status_code
            == 200
        )
        changement = client_a.post(
            "/v1/account/password", json={"currentPassword": MDP, "newPassword": MDP_2}
        )
        assert changement.status_code == 200, changement.text
        reponse = client_b.get("/v1/account/devices")
        assert reponse.status_code == 409, reponse.text
        assert reponse.json()["error"]["code"] == "sessionExpired"
        assert client_b.get("/v1/account/status").json()["state"] == "sessionExpired"
        _balayer(client_b)
        a.fermer()
        b.fermer()

    def test_un_mauvais_mot_de_passe_rend_403(self, vps, tmp_path):
        """Le VPS répond 401 ``invalidCredentials`` ; ici, 403."""
        a = appareil(vps, tmp_path / "a")
        _inscrire_par_http(_app_locale(a), vps)
        b = appareil(vps, tmp_path / "b")
        reponse = _app_locale(b).post(
            "/v1/account/login", json={"email": EMAIL, "password": MDP_2}
        )
        assert reponse.status_code == 403
        assert reponse.json()["error"]["code"] == "invalidCredentials"
        a.fermer()
        b.fermer()

    def test_la_suppression_ne_contourne_pas_la_limite(self, vps, tmp_path):
        """§3.8 : après cinq échecs de ``unlock``, ``/delete`` sur l'appareil
        verrouillé rendait 403 à chaque essai, sans rien compter
        (contre-épreuve du 24/09/2026) : un oracle du mot de passe."""
        service = appareil(vps, tmp_path / "a")
        client = _app_locale(service)
        _inscrire_par_http(client, vps)
        client.post("/v1/account/lock", json={})
        for _ in range(5):
            client.post("/v1/account/unlock", json={"password": MDP_2})
        refus = client.post(
            "/v1/account/delete", json={"password": MDP, "eraseLocalData": False}
        )
        assert refus.status_code == 429, refus.text
        assert refus.json()["error"]["retryAfterS"] == 30
        service.fermer()

    def test_cinq_essais_puis_429_avec_retry_after(self, vps, tmp_path):
        """§3.8 : ``unlock`` — 5 essais, puis 30 s ; le refus dit combien."""
        service = appareil(vps, tmp_path / "a")
        client = _app_locale(service)
        _inscrire_par_http(client, vps)
        client.post("/v1/account/lock", json={})
        for _ in range(5):
            assert (
                client.post("/v1/account/unlock", json={"password": MDP_2}).status_code
                == 403
            )
        refus = client.post("/v1/account/unlock", json={"password": MDP})
        assert refus.status_code == 429
        assert refus.json()["error"]["retryAfterS"] == 30
        assert refus.headers["Retry-After"] == "30"
        service.fermer()


class TestAucunEcho:
    def test_un_refus_ne_renvoie_jamais_le_mot_de_passe(self, vps, tmp_path):
        """§3.8 « validation écrite à la main » : le 422 par défaut de FastAPI
        recopie l'entrée refusée ; un mot de passe y reviendrait en écho."""
        service = appareil(vps, tmp_path / "a")
        client = _app_locale(service)
        canari = "Canari-echo-mot-de-passe-5Tr"
        for corps in (
            {"email": 12, "password": canari},
            {"email": EMAIL, "password": [canari]},
            {"password": canari},
        ):
            reponse = client.post("/v1/account/login", json=corps)
            assert reponse.status_code == 422
            assert canari not in reponse.text, "le mot de passe est revenu en écho"
        brut = client.post(
            "/v1/account/login",
            content=b'{"password":"' + canari.encode() + b'",',
            headers={"Content-Type": "application/json"},
        )
        assert brut.status_code == 422 and canari not in brut.text
        service.fermer()

    @pytest.mark.parametrize(
        "chemin, corps",
        [
            ("/v1/account/login", b'{"email":"a@b.c","password":"x\\ud800y"}'),
            ("/v1/account/unlock", b'{"password":"x\\ud800y"}'),
            (
                "/v1/account/signup/start",
                b'{"email":"\\ud800@b.c","termsAccepted":true}',
            ),
            ("/v1/account/login", b"[" * 40000),
        ],
    )
    def test_un_texte_illisible_rend_422_et_non_500(self, vps, tmp_path, chemin, corps):
        """Le contrat : « le code seul, jamais le message ». Le 24/09/2026,
        un substitut isolé (``\\ud800``) dans le mot de passe ou l'adresse
        levait une UnicodeEncodeError, et 64 Kio de « [ » une
        RecursionError : 500, hors contrat."""
        service = appareil(vps, tmp_path / "a")
        client = TestClient(_app_locale(service).app, raise_server_exceptions=False)
        reponse = client.post(
            chemin, content=corps, headers={"Content-Type": "application/json"}
        )
        assert reponse.status_code == 422, reponse.text
        assert reponse.json()["error"]["code"] == "invalidRequest"
        service.fermer()


class TestLeSeauDuCompte:
    """§3.8 : « un seau de limitation propre dans auth_middleware.py » ;
    ``GET /v1/account/status`` exempté, le reste dans un seau large, distinct
    du seau commun que le poller vocal vide."""

    @staticmethod
    def _app() -> TestClient:
        app = FastAPI()

        @app.get("/v1/account/status")
        def status():
            return {}

        @app.post("/v1/account/login")
        def login():
            return {}

        @app.get("/v1/voice/poll")
        def poll():
            return {}

        app.add_middleware(RateLimitMiddleware, requests_per_minute=60, burst_size=10)
        app.add_middleware(AuthMiddleware, api_key="oj_sk_test123456789012345678901234")
        return TestClient(app)

    def test_le_statut_n_entre_dans_aucun_seau(self):
        client = self._app()
        cle = {"Authorization": "Bearer oj_sk_test123456789012345678901234"}
        for _ in range(100):
            assert client.get("/v1/account/status", headers=cle).status_code == 200

    def test_un_poller_qui_vide_le_seau_commun_ne_bloque_pas_le_compte(self):
        """Une inscription tapée pendant que le panneau vocal sonde ne doit
        pas rebondir en 429 au milieu du code reçu par courriel."""
        client = self._app()
        cle = {"Authorization": "Bearer oj_sk_test123456789012345678901234"}
        statuts = [
            client.get("/v1/voice/poll", headers=cle).status_code for _ in range(30)
        ]
        assert 429 in statuts, "le seau commun aurait dû se vider"
        assert client.post("/v1/account/login", headers=cle).status_code == 200

    def test_le_seau_du_compte_a_sa_propre_borne(self):
        client = self._app()
        cle = {"Authorization": "Bearer oj_sk_test123456789012345678901234"}
        statuts = [
            client.post("/v1/account/login", headers=cle).status_code for _ in range(60)
        ]
        assert statuts[:20] == [200] * 20, "la rafale du compte est de 20"
        assert 429 in statuts, "le seau du compte doit avoir une borne"

    def test_le_seau_ne_leve_pas_le_mur_de_la_cle(self):
        """Le seau ne sert qu'au limiteur : sans clé, 401 de la clé LOCALE —
        le seul 401 permis, celui qui fait rafraîchir la clé."""
        client = self._app()
        assert client.post("/v1/account/login").status_code == 401
        assert client.get("/v1/account/status").status_code == 401


class TestLeMontage:
    def test_create_app_monte_le_compte_dans_le_dossier_isole(self, tmp_path_factory):
        """§3.8 « montage : à côté des conversations » ; et la fixture
        ``_isoler_le_compte`` tient : le service vit dans le dossier jetable
        de la session, jamais dans ~/.diapason (ce Mac est le runner CI)."""
        from unittest.mock import MagicMock

        from diapason.core.config import DiapasonConfig
        from diapason.server.app import create_app

        engine = MagicMock()
        engine.engine_id = "mock"
        engine.health.return_value = True
        engine.list_models.return_value = ["test-model"]
        cfg = DiapasonConfig()
        cfg.analytics.enabled = False
        cfg.traces.enabled = False
        app = create_app(engine, "test-model", config=cfg)
        client = TestClient(app)
        reponse = client.get("/v1/account/status")
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["state"] in {"none", "locked", "unlocked"}
        service = app.state.compte()
        assert str(service.dossier.chemin).startswith(
            str(tmp_path_factory.getbasetemp())
        ), f"le compte d'un create_app de test vit en {service.dossier.chemin}"
        assert service.protecteur.nom == "memory", "le vrai trousseau a été choisi"
        assert not service.etat.existe() or service.etat.lire("accountId"), (
            "un simple statut a créé etat.key"
        )

    def test_sans_mock_transport_aucun_test_n_atteint_le_vrai_serveur(self):
        """La fixture remplace le client HTTP par défaut par un refus."""
        from diapason.compte import transport

        with pytest.raises(RuntimeError, match="VRAI serveur de comptes"):
            transport.client_http_par_defaut()

    def test_le_mot_de_passe_n_entre_ni_au_journal_ni_dans_les_bases(
        self, vps, tmp_path, monkeypatch, caplog
    ):
        """Étape 8 : « mot de passe absent des journaux (caplog, traces.db,
        telemetry.db de test) », par la vraie app, du corps HTTP au VPS."""
        from unittest.mock import MagicMock

        from diapason.core.config import DiapasonConfig
        from diapason.core.events import EventBus
        from diapason.server import app as module_app
        from diapason.server.app import create_app
        from diapason.telemetry.store import TelemetryStore

        monkeypatch.setattr(
            module_app,
            "_service_compte",
            lambda config, store: appareil(vps, tmp_path / "appareil"),
        )
        bus = EventBus()
        telemetrie = TelemetryStore(tmp_path / "telemetry.db")
        telemetrie.subscribe_to_bus(bus)
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.health.return_value = True
        engine.list_models.return_value = ["test-model"]
        cfg = DiapasonConfig()
        cfg.analytics.enabled = False
        cfg.traces.enabled = True
        cfg.traces.db_path = str(tmp_path / "traces.db")
        caplog.set_level(logging.DEBUG)
        app = create_app(engine, "test-model", bus=bus, config=cfg)
        with TestClient(app) as client:
            _inscrire_par_http(client, vps)
            client.post("/v1/account/lock", json={})
            client.post(
                "/v1/account/unlock", json={"password": "Faux-canari-journal-3Wd"}
            )
            client.post("/v1/account/unlock", json={"password": MDP})
            client.post(
                "/v1/account/password",
                json={"currentPassword": MDP, "newPassword": MDP_2},
            )
        telemetrie.flush()
        telemetrie.close()
        texte = caplog.text + "".join(
            r.getMessage() + repr(r.args) for r in caplog.records
        )
        octets = b""
        # Toutes les bases de l'appareil : traces, télémétrie, etat.key.
        for chemin in tmp_path.rglob("*"):
            if chemin.is_file() and "vps" not in chemin.parts:
                octets += chemin.read_bytes()
        for mdp in (MDP, MDP_2, "Faux-canari-journal-3Wd"):
            assert mdp not in texte, "un mot de passe est entré au journal"
            assert mdp.encode() not in octets, (
                "un mot de passe est dans une base locale"
            )
