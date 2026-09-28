"""La passerelle du tailnet — plan de la phase 2, étape 3 (26/09/2026).

Chaque test nomme ce qui arriverait sans elle. Le fond : tailscaled se
connecte depuis 127.0.0.1, donc une requête du téléphone relayée vers 8000
aurait hérité des droits de la boucle locale. Ici, c'est le SOCKET (la
passerelle) et une session d'appareil qui décident, jamais un en-tête.
"""

from __future__ import annotations

import base64
import time
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request, WebSocket  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from diapason.mesh.commands import NonceStore  # noqa: E402
from diapason.mesh.identity import canonical_bytes  # noqa: E402
from diapason.mesh.registry import DeviceRegistry  # noqa: E402
from diapason.mesh.routes import set_registry_for_tests  # noqa: E402
from diapason.mesh.sessions import (  # noqa: E402
    SESSION_REQUEST_FIELDS,
    SESSION_TTL_MS,
    DeviceSessions,
    build_session_request,
)
from diapason.mesh.signed import signable  # noqa: E402
from diapason.security.signing import generate_keypair, sign_b64  # noqa: E402
from diapason.server.passerelle_tailnet import (  # noqa: E402
    COOKIE_APPAREIL,
    PasserelleTailnet,
    adresse_du_tailnet,
)

# Une fausse clé locale ; gitleaks voit une chaîne longue affectée à KEY.
KEY = "diapason_sk_test_key_for_the_tailnet_gateway_000"  # gitleaks:allow
MAC = "dev_atelier"
OWNER = "owner_la_flotte_de_carlito"
PHONE = "dev_le_telephone"
ICI = "https://testserver"


class _Monde:
    def __init__(self, tmp_path) -> None:
        self.registry = DeviceRegistry(tmp_path / "mesh.db")
        self.sessions = DeviceSessions(self.registry)
        self.nonces = NonceStore(tmp_path / "mesh.db")
        cles = generate_keypair()
        self.cle_privee = cles.private_key
        invitation = self.registry.create_pairing("Téléphone")
        self.registry.redeem_pairing(
            invitation["pairingToken"],
            device_id=PHONE,
            public_key_b64=base64.b64encode(cles.public_key).decode(),
            name="Téléphone",
            platform="ANDROID",
            device_type="PHONE",
            declared_capabilities=["app.navigate"],
        )

    def passerelle(self, app, **options) -> PasserelleTailnet:
        return PasserelleTailnet(
            app,
            sessions=self.sessions,
            registre=self.registry,
            nonces=self.nonces,
            identite=lambda: (MAC, OWNER),
            adresse=options.pop("adresse", ""),
            **options,
        )

    def demande_signee(self, **remplacements) -> dict:
        charge = build_session_request(owner_id=OWNER, device_id=PHONE, audience=MAC)
        charge.update(remplacements)
        signature = sign_b64(
            canonical_bytes(signable(charge, SESSION_REQUEST_FIELDS)), self.cle_privee
        )
        return {**charge, "signature": signature}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "foyer"))
    m = _Monde(tmp_path)
    set_registry_for_tests(m.registry)
    yield m
    set_registry_for_tests(None)


def _vraie_app():
    from diapason.core.config import DiapasonConfig
    from diapason.server.app import create_app

    engine = MagicMock()
    engine.engine_id = "mock"
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {"content": "réponse du modèle", "usage": {}}
    config = DiapasonConfig()
    # Même avec l'accès distant permis au pilotage, le tailnet reste dehors.
    config.desktop.lightning.allow_remote = True
    return create_app(engine, "test-model", api_key=KEY, config=config), engine


def _avant_le_repli(app) -> None:
    """Place la dernière route ajoutée AVANT l'attrape-tout du bundle.

    26/09/2026 : quand server/static est construit, ``GET /{full_path:path}``
    est enregistrée avant une route que le test ajoute après coup ; c'est lui
    qui répondait (index.html, 200), et le test échouait sans rien dire de la
    liste d'autorisation. Placée devant, la route est vraiment servable : seul
    le refus de la passerelle peut l'arrêter.
    """
    app.router.routes.insert(0, app.router.routes.pop())


def _ouvrir_une_session(client: TestClient, monde: _Monde) -> str:
    """Le parcours complet du téléphone : enveloppe → ticket → cookie."""
    ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
    assert ticket.status_code == 200, ticket.text
    ouverture = client.post(
        "/v1/appareil/ouvrir",
        data={"ticket": ticket.json()["ticket"]},
        follow_redirects=False,
    )
    assert ouverture.status_code == 303, ouverture.text
    jeton = ouverture.cookies.get(COOKIE_APPAREIL)
    assert jeton, "aucun cookie de session posé"
    return jeton


def _ws(jeton: str, origine: str = ICI) -> dict[str, str]:
    """En-têtes d'une poignée de main. Le cookie est posé à la main : le
    client de test ne joint pas un cookie Secure à une URL ws://, et un
    refus « sans session » ferait passer un test d'Origine pour ce qu'il
    n'est pas."""
    return {"Origin": origine, "Cookie": f"{COOKIE_APPAREIL}={jeton}"}


@pytest.fixture
def telephone(monde):
    app, engine = _vraie_app()
    client = TestClient(monde.passerelle(app), base_url=ICI)
    jeton = _ouvrir_une_session(client, monde)
    client.app_principale = app  # type: ignore[attr-defined]
    client.engine = engine  # type: ignore[attr-defined]
    client.jeton = jeton  # type: ignore[attr-defined]
    return client


@pytest.fixture
def banc(monde):
    """La passerelle devant l'app témoin, session ouverte. Pour les refus de
    WebSocket : si un refus cessait de tenir, le handler témoin fermerait
    en 4000 au bout de 3 s, et le test échouerait au lieu de pendre."""
    client = TestClient(monde.passerelle(_app_temoin()), base_url=ICI)
    client.jeton = _ouvrir_une_session(client, monde)  # type: ignore[attr-defined]
    return client


class TestLaCleLocaleNeSuffitPas:
    """Le plan : /v1/models rend 401 sans cookie, 401 avec la clé locale,
    200 avec le cookie."""

    def test_sans_cookie_401(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        assert client.get("/v1/models").status_code == 401

    def test_avec_la_cle_locale_401(self, monde):
        """La clé partagée prouve MOINS qu'une session : ni quel appareil,
        ni révocable seule. Sur ce chemin elle ne vaut rien."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.get("/v1/models", headers={"Authorization": f"Bearer {KEY}"})
        assert reponse.status_code == 401
        assert "clé locale" in reponse.json()["detail"]

    def test_la_cle_locale_est_refusee_meme_avec_une_session(self, telephone):
        reponse = telephone.get(
            "/v1/models", headers={"Authorization": f"Bearer {KEY}"}
        )
        assert reponse.status_code == 401, (
            "une clé locale jointe à une session ouvrirait un second chemin"
        )

    def test_avec_le_cookie_200(self, telephone):
        reponse = telephone.get("/v1/models")
        assert reponse.status_code == 200, reponse.text

    def test_le_meme_app_sur_la_boucle_locale_exige_toujours_la_cle(self, monde):
        """Le marqueur d'appareil n'existe que dans la portée posée par la
        passerelle : l'app servie directement (8000) n'en voit jamais."""
        app, _ = _vraie_app()
        direct = TestClient(app)
        assert direct.get("/v1/models").status_code == 401
        entetes = {"Authorization": f"Bearer {KEY}"}
        assert direct.get("/v1/models", headers=entetes).status_code == 200


class TestLOuvertureDeSession:
    def test_le_cookie_est_httponly_secure_strict_et_dure_douze_heures(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
        ouverture = client.post(
            "/v1/appareil/ouvrir",
            data={"ticket": ticket.json()["ticket"]},
            follow_redirects=False,
        )
        assert ouverture.status_code == 303
        assert ouverture.headers["location"] == "/"
        pose = ouverture.headers["set-cookie"]
        for attendu in (
            "HttpOnly",
            "Secure",
            "SameSite=strict",
            f"Max-Age={SESSION_TTL_MS // 1000}",
            "Path=/",
        ):
            assert attendu.lower() in pose.lower(), f"{attendu} manque : {pose}"
        assert ouverture.headers.get("cache-control") == "no-store"

    def test_le_jeton_ne_passe_jamais_par_un_corps(self, monde):
        """Le JavaScript ne doit jamais le voir : ni la réponse du ticket, ni
        celle de l'ouverture ne le portent."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
        assert "sessionToken" not in ticket.text
        ouverture = client.post(
            "/v1/appareil/ouvrir",
            data={"ticket": ticket.json()["ticket"]},
            follow_redirects=False,
        )
        jeton = ouverture.cookies.get(COOKIE_APPAREIL)
        assert jeton and jeton not in ouverture.text
        assert jeton not in ouverture.headers.get("location", "")

    def test_un_ticket_ne_sert_qu_une_fois(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
        corps = {"ticket": ticket.json()["ticket"]}
        premiere = client.post(
            "/v1/appareil/ouvrir", data=corps, follow_redirects=False
        )
        seconde = client.post("/v1/appareil/ouvrir", data=corps, follow_redirects=False)
        assert premiere.status_code == 303
        assert seconde.status_code == 401

    def test_une_enveloppe_rejouee_est_refusee(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        demande = monde.demande_signee()
        assert client.post("/v1/appareil/session", json=demande).status_code == 200
        rejeu = client.post("/v1/appareil/session", json=demande)
        assert rejeu.status_code == 403
        assert rejeu.json()["status"] == "DENIED"

    def test_une_audience_etrangere_est_refusee(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        demande = monde.demande_signee(audience="dev_un_autre_mac")
        assert client.post("/v1/appareil/session", json=demande).status_code == 403

    def test_un_corps_illisible_rend_400_pas_500(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.post(
            "/v1/appareil/session",
            content=b"{pas du json",
            headers={"Content-Type": "application/json"},
        )
        assert reponse.status_code == 400

    def test_une_origine_nulle_peut_poser_le_cookie(self, monde):
        """loadRequest d'Android poste le ticket sans document d'origine."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
        ouverture = client.post(
            "/v1/appareil/ouvrir",
            data={"ticket": ticket.json()["ticket"]},
            headers={"Origin": "null"},
            follow_redirects=False,
        )
        assert ouverture.status_code == 303


class TestLaPageRouverte:
    """La coquille poste la dernière page avec le ticket (lot 4 de la
    fluidité, 26/09/2026) : sans elle, chaque démarrage à froid qui rouvre
    une session atterrissait sur la Discussion."""

    @staticmethod
    def _ouvrir(monde, **champs) -> str:
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
        ouverture = client.post(
            "/v1/appareil/ouvrir",
            data={"ticket": ticket.json()["ticket"], **champs},
            follow_redirects=False,
        )
        assert ouverture.status_code == 303, ouverture.text
        assert ouverture.cookies.get(COOKIE_APPAREIL), (
            "la suite ne doit rien retirer au cookie"
        )
        return ouverture.headers["location"]

    def test_la_derniere_page_est_rouverte(self, monde):
        assert self._ouvrir(monde, suite="/vie/tasks") == "/vie/tasks", (
            "la WebView doit atterrir sur la page laissée, pas sur la Discussion"
        )

    def test_sans_suite_la_discussion_comme_avant(self, monde):
        assert self._ouvrir(monde) == "/"

    @pytest.mark.parametrize(
        "suite",
        [
            "//exemple.com/piege",
            "https://exemple.com/",
            "/\\exemple.com",
            "/vie/../v1/tasks",
            "/vie/tasks?x=1",
            "/vie/tasks#x",
            "/vie/tasks\r\nSet-Cookie: x=1",
            "vie/tasks",
            "/v1/vie/tasks",
            "/v1",
            "/api/x",
            "/ws/chat",
            "/assets/index.js",
            "/" + "a" * 250,
            "",
        ],
    )
    def test_une_suite_hors_des_pages_du_bundle_rend_la_racine(self, monde, suite):
        """Un Location fait de ce que le corps apporte serait une redirection
        ouverte ; un chemin d'API montrerait du JSON en pleine page."""
        assert self._ouvrir(monde, suite=suite) == "/", f"suite acceptée : {suite!r}"

    def test_deux_suites_rendent_la_racine(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
        ouverture = client.post(
            "/v1/appareil/ouvrir",
            content=f"ticket={ticket.json()['ticket']}&suite=/vie/tasks&suite=/settings",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert ouverture.status_code == 303
        assert ouverture.headers["location"] == "/", "laquelle croire ? aucune"


class TestLesRefus:
    def test_le_plan_de_controle_du_maillage_rend_403(self, telephone):
        """Le plan : POST /v1/mesh/pairings → 403, même avec une session."""
        reponse = telephone.post(
            "/v1/mesh/pairings",
            json={"deviceName": "intrus"},
            headers={"Origin": ICI},
        )
        assert reponse.status_code == 403
        assert "maillage" in reponse.json()["detail"]

    def test_sans_session_aussi_403(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        assert client.post("/v1/mesh/pairings", json={}).status_code == 403

    @pytest.mark.parametrize(
        ("methode", "chemin"),
        [
            ("GET", "/v1/account/status"),
            ("GET", "/v1/gestures/state"),
            ("POST", "/v1/config/set"),
            ("GET", "/v1/mesh/inbox"),
            ("GET", "/v1/succes/tasks"),
            ("GET", "/openapi.json"),
        ],
    )
    def test_la_liste_refusee(self, telephone, methode, chemin):
        reponse = telephone.request(methode, chemin, headers={"Origin": ICI})
        assert reponse.status_code == 403, f"{methode} {chemin} a franchi la passerelle"

    def test_une_route_que_personne_n_a_classee_est_refusee(self, monde):
        """La liste d'autorisation : une route ajoutée demain par une autre
        session ne passe pas parce que rien ne la nomme."""
        app, _ = _vraie_app()

        @app.get("/v1/ajoutee-demain")
        def _ajoutee():  # pragma: no cover - ne doit jamais être appelée
            return {"fuite": True}

        _avant_le_repli(app)
        client = TestClient(monde.passerelle(app), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        reponse = client.get(
            "/v1/ajoutee-demain", headers={"Cookie": f"{COOKIE_APPAREIL}={jeton}"}
        )
        assert reponse.status_code == 403
        assert "fuite" not in reponse.text

    def test_un_chemin_inconnu_rend_404_sans_atteindre_l_app(self, telephone):
        reponse = telephone.get("/v1/nulle-part")
        assert reponse.status_code == 404
        assert "n'existe pas" in reponse.json()["detail"], reponse.text

    def test_un_chemin_d_api_ne_retombe_jamais_sur_le_bundle(self, monde):
        """26/09/2026 : avec server/static construit, /v1/nulle-part rendait
        index.html en 200 au téléphone — un fetch qui attend du JSON lisait
        « Unexpected token < ». Le repli du bundle est posé ici à la main
        quand server/static manque, pour que le test tienne dans les deux cas.
        """
        from starlette.responses import HTMLResponse

        app, _ = _vraie_app()
        if not any(getattr(r, "path", None) == "/{full_path:path}" for r in app.routes):

            @app.get("/{full_path:path}")
            def _repli(full_path: str):
                return HTMLResponse("<!doctype html><p>bundle</p>")

        client = TestClient(monde.passerelle(app), base_url=ICI)
        _ouvrir_une_session(client, monde)
        for chemin in ("/v1/nulle-part", "/api/nulle-part", "/ws/nulle-part"):
            reponse = client.get(chemin)
            assert reponse.status_code == 404, f"{chemin} rend {reponse.status_code}"
            assert "n'existe pas" in reponse.json()["detail"], reponse.text
        page = client.get("/vie/tasks")
        assert page.status_code == 200, "une page du bundle doit rester servie"
        assert "text/html" in page.headers["content-type"], page.headers

    def test_une_methode_que_la_route_ne_sert_pas_rend_405(self, telephone):
        reponse = telephone.delete("/v1/models", headers={"Origin": ICI})
        assert reponse.status_code == 405, reponse.text

    def test_un_corps_trop_gros_est_refuse_avant_d_etre_lu(self, monde):
        """Une route sans session ne fait pas lire des mégaoctets à un inconnu."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.post(
            "/v1/appareil/session",
            content=b"x" * (17 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert reponse.status_code == 413

    def test_une_route_de_vie_inventee_n_herite_pas_de_ses_voisines(self, monde):
        app, _ = _vraie_app()

        @app.get("/v1/vie/inventee")
        def _inventee():  # pragma: no cover
            return {"fuite": True}

        _avant_le_repli(app)
        client = TestClient(monde.passerelle(app), base_url=ICI)
        _ouvrir_une_session(client, monde)
        assert client.get("/v1/vie/inventee").status_code == 403

    def test_la_voix_est_fermee_1008_sans_cookie(self, monde):
        """Le plan : /v1/voice/live fermé 1008 sans cookie."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        with pytest.raises(WebSocketDisconnect) as refus:
            with client.websocket_connect(
                "/v1/voice/live", headers={"Origin": ICI}
            ) as ws:
                ws.receive_text()
        assert refus.value.code == 1008

    def test_la_voix_s_ouvre_avec_une_session(self, banc):
        """Phase 4 (26/09/2026) : rouverte une fois la coupure serveur posée
        et la séance du téléphone bornée (TestLaVoixDuTelephone, plus bas)."""
        with banc.websocket_connect("/v1/voice/live", headers=_ws(banc.jeton)) as ws:
            ws.send_text("allô")
            assert ws.receive_text() == "écho:allô"

    def test_le_flux_du_chat_sans_cookie_1008(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        with pytest.raises(WebSocketDisconnect) as refus:
            with client.websocket_connect(
                "/v1/chat/stream", headers={"Origin": ICI}
            ) as ws:
                ws.receive_text()
        assert refus.value.code == 1008
        assert "session" in refus.value.reason, refus.value.reason

    def test_un_jeton_de_websocket_en_requete_est_refuse(self, banc):
        with pytest.raises(WebSocketDisconnect) as refus:
            with banc.websocket_connect(
                f"/v1/chat/stream?token={KEY}", headers=_ws(banc.jeton)
            ) as ws:
                ws.receive_text()
        assert refus.value.code == 1008
        assert "clé locale" in refus.value.reason, refus.value.reason

    def test_un_sous_protocole_porteur_de_cle_est_refuse(self, banc):
        entetes = {
            **_ws(banc.jeton),
            "Sec-WebSocket-Protocol": f"diapason, diapason-auth.{KEY}",
        }
        with pytest.raises(WebSocketDisconnect) as refus:
            with banc.websocket_connect("/v1/chat/stream", headers=entetes) as ws:
                ws.receive_text()
        assert refus.value.code == 1008
        assert "clé locale" in refus.value.reason, refus.value.reason


class TestLesVraisFluxAvecUneSession:
    """Jusqu'ici, les WebSockets n'étaient éprouvés avec session que sur
    l'app témoin, qui n'appelle jamais websocket_authorized : l'exemption du
    marqueur d'appareil pouvait disparaître sans qu'un test échoue, et la
    Discussion du téléphone être fermée en 1008 (contre-épreuve du
    26/09/2026, mutant M36)."""

    def test_le_flux_du_chat_repond_au_telephone(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        with client.websocket_connect("/v1/chat/stream", headers=_ws(jeton)) as ws:
            ws.send_text("pas du json")
            assert ws.receive_json() == {"type": "error", "detail": "Invalid JSON"}

    def test_le_flux_des_agents_accepte_le_telephone(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        # Refusé, le handler fermerait AVANT l'accept : websocket_connect
        # lèverait ici même.
        with client.websocket_connect("/v1/agents/events", headers=_ws(jeton)) as ws:
            ws.close()


class TestRienDeLApiNeResteSurLeTelephone:
    """26/09/2026, contre-épreuve : GET /v1/vie/tasks sortait de la passerelle
    sans aucun Cache-Control. Chromium garde sur disque toute réponse GET qui
    ne l'interdit pas : les données de Carlito restaient dans le cache de la
    WebView, et « Quitter l'appairage » ne le vidait pas."""

    def test_une_lecture_de_l_api_n_est_jamais_gardee(self, telephone):
        for chemin in ("/v1/models", "/v1/vie/tasks?include_done=true", "/health"):
            reponse = telephone.get(chemin)
            assert reponse.status_code == 200, (chemin, reponse.text[:200])
            if chemin.startswith("/v1/"):
                assert reponse.headers.get("cache-control") == "no-store", chemin

    def test_un_refus_non_plus(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.get("/v1/models")
        assert reponse.status_code == 401
        assert reponse.headers.get("cache-control") == "no-store"

    def test_le_no_cache_d_un_flux_devient_no_store_jamais_l_inverse(self, monde):
        """Un seul Cache-Control sort, le plus strict : le ``no-cache`` des
        flux SSE n'empêche pas de garder, ``no-store`` si."""
        import asyncio

        app, _ = _vraie_app()
        recus: list[dict] = []

        async def send(message):
            recus.append(message)

        envoyer = monde.passerelle(app)._reecrire_les_entetes(send, None, "/v1/x")
        asyncio.run(
            envoyer(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"cache-control", b"no-cache"),
                        (b"content-type", b"text/event-stream"),
                    ],
                }
            )
        )
        valeurs = [v for n, v in recus[0]["headers"] if n.lower() == b"cache-control"]
        assert valeurs == [b"no-store"], valeurs


class TestLOrigine:
    def test_une_ecriture_d_une_autre_origine_est_refusee(self, telephone):
        reponse = telephone.put(
            "/v1/conversations/c1",
            json={},
            headers={"Origin": "https://exemple.com"},
        )
        assert reponse.status_code == 403
        assert "Origine" in reponse.json()["detail"]

    def test_une_ecriture_sans_origine_est_refusee(self, telephone):
        """Le cookie seul ne suffit pas pour écrire : sans Origin, rien ne
        dit que ce n'est pas une page tierce qui a trouvé un contournement
        de SameSite."""
        assert telephone.put("/v1/conversations/c1", json={}).status_code == 403

    def test_un_websocket_d_une_autre_origine_est_ferme(self, banc):
        with pytest.raises(WebSocketDisconnect) as refus:
            with banc.websocket_connect(
                "/v1/chat/stream",
                headers=_ws(banc.jeton, "https://exemple.com"),
            ) as ws:
                ws.receive_text()
        assert refus.value.code == 1008
        assert "Origine" in refus.value.reason, refus.value.reason

    def test_l_adresse_posee_vaut_origine_meme_si_host_differe(self, monde):
        """Si tailscale serve réécrit Host, l'adresse [tailnet] posée par
        Carlito reste reconnue comme la nôtre."""
        app, _ = _vraie_app()
        passerelle = monde.passerelle(app, adresse="https://atelier.exemple.ts.net")
        client = TestClient(passerelle, base_url="https://127.0.0.1:8002")
        _ouvrir_une_session(client, monde)
        reponse = client.put(
            "/v1/conversations/c1",
            json={"id": "c1", "title": "t", "messages": []},
            headers={"Origin": "https://atelier.exemple.ts.net"},
        )
        assert reponse.status_code != 403, reponse.text


class TestLesPortesSansSession:
    def test_la_sante_repond_sans_session(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        assert client.get("/health").status_code == 200

    def test_une_porte_du_maillage_atteint_sa_route(self, monde):
        """La porte refuse faute de signature — mais c'est ELLE qui refuse,
        pas la passerelle."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.post("/v1/mesh/commands/poll", json={})
        assert reponse.status_code not in (401, 404)
        assert "passerelle" not in reponse.text
        assert "session d'appareil" not in reponse.text

    def test_une_page_tierce_ne_frappe_pas_aux_portes(self, monde):
        """Sur une porte qui RÉUSSIRAIT sans le contrôle : la version d'avant
        postait {} sur /v1/mesh/commands/poll, que la porte refuse elle-même
        en 403 faute de signature — le 403 attendu arrivait avec ou sans
        contrôle d'Origin (contre-épreuve du 26/09/2026)."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        assert client.get("/health").status_code == 200, "sans Origin : permis"
        reponse = client.get("/health", headers={"Origin": "https://exemple.com"})
        assert reponse.status_code == 403
        assert "Origine" in reponse.json()["detail"]

    def test_une_page_tierce_ne_pose_pas_de_cookie(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        ticket = client.post("/v1/appareil/session", json=monde.demande_signee())
        reponse = client.post(
            "/v1/appareil/ouvrir",
            data={"ticket": ticket.json()["ticket"]},
            headers={"Origin": "https://exemple.com"},
            follow_redirects=False,
        )
        assert reponse.status_code == 403
        assert COOKIE_APPAREIL not in reponse.headers.get("set-cookie", "")

    def test_l_origine_nulle_n_ouvre_pas_de_session(self, monde):
        """L'exception « null » ne vaut que pour /ouvrir (loadRequest)."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.post(
            "/v1/appareil/session",
            json=monde.demande_signee(),
            headers={"Origin": "null"},
        )
        assert reponse.status_code == 403

    def test_le_bundle_sans_session_dit_quoi_faire(self, monde):
        """Un navigateur qui tombe ici lit une phrase, pas un JSON."""
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.get("/v1/models", headers={"Accept": "text/html"})
        assert reponse.status_code == 401
        assert "Ouvre Diapason depuis l" in reponse.text


class TestLeTelephoneNePilotePasLeMac:
    def test_action_mode_auto_ne_touche_pas_le_mac(self, telephone):
        """Le plan : action_mode=auto → aucune action sur le Mac, même avec
        allow_remote vrai. Avant, seule une ValueError sur « appareil:… »
        tenait la porte fermée — par hasard."""
        app = telephone.app_principale
        app.state.lightning_actions.handle = MagicMock()
        reponse = telephone.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "ouvre Notes"}],
                "action_mode": "auto",
            },
            headers={"Origin": ICI},
        )
        assert reponse.status_code == 200, reponse.text
        app.state.lightning_actions.handle.assert_not_called()
        telephone.engine.generate.assert_called_once()


class TestLaVoixDuTelephone:
    """La voix du Mac par la VRAIE passerelle, avec une vraie session
    d'appareil (phase 4, 26/09/2026). Whisper, Kokoro et Ollama sont
    remplacés par un banc ; le reste — la route, la fabrique, la séance
    locale, l'exécuteur d'outils, le plafond — est le vrai."""

    @pytest.fixture
    def banc_vocal(self, telephone, monkeypatch):
        import asyncio

        from diapason.core.registry import ToolRegistry
        from diapason.speech.realtime import local_voice, tools
        from diapason.speech.realtime.local_voice import LocalVoiceSession

        espions = {}
        for nom in ("clipboard_read", "screen_read_text", "current_time"):
            espions[nom] = _espion_d_outil(nom)
            espions[nom].executions = []
            ToolRegistry.register_value(nom, espions[nom])
        monkeypatch.setattr(tools, "_executeurs", {})
        monkeypatch.setattr(local_voice, "ollama_reachable", lambda *_a, **_k: True)
        tours: list = []

        def llm(messages):
            tours.append(messages)
            file: asyncio.Queue = asyncio.Queue()
            if len(tours) == 1:
                appel = {"function": {"name": "clipboard_read", "arguments": {}}}
                file.put_nowait(("tools", [appel]))
            else:
                file.put_nowait("Pas depuis le téléphone.")
            file.put_nowait(None)
            return file

        class _SeanceDeBanc(LocalVoiceSession):
            def __init__(self, **options):
                super().__init__(
                    stt=lambda _a: "",
                    llm=llm,
                    tts=lambda _t: b"\x00\x00" * 240,
                    **options,
                )

        monkeypatch.setattr(local_voice, "LocalVoiceSession", _SeanceDeBanc)
        # Une séance qui ne finit pas son tour est coupée en 5 s au lieu de
        # 120 : le test échoue vite au lieu de pendre deux minutes.
        monkeypatch.setattr("diapason.speech.realtime.bridge.SILENCE_MAX_S", 5.0)
        telephone.espions = espions  # type: ignore[attr-defined]
        telephone.tours = tours  # type: ignore[attr-defined]
        return telephone

    @staticmethod
    def _demarrer(ws, **trame) -> None:
        ws.send_json({"type": "start", "include_memory": False, **trame})

    def test_le_presse_papiers_du_mac_ne_se_lit_pas_a_la_voix(self, banc_vocal):
        """Le client demande clipboard_read (tools: …) et le modèle l'appelle :
        l'outil rend ok=false et ne s'exécute pas. Sans le plafond, « qu'est-ce
        que j'ai copié ? » dit au téléphone rendait le presse-papiers du Mac."""
        with banc_vocal.websocket_connect(
            "/v1/voice/live", headers=_ws(banc_vocal.jeton)
        ) as ws:
            # current_time garde les outils allumés : sans lui, la trousse du
            # téléphone serait vide et les outils coupés avant tout appel.
            self._demarrer(
                ws,
                provider="local",
                tools="clipboard_read,screen_read_text,current_time",
            )
            assert ws.receive_json() == {"type": "ready"}
            ws.send_json({"type": "text", "text": "qu'est-ce que j'ai copié ?"})
            recus = []
            while len(recus) < 60:
                message = ws.receive_json()
                recus.append(message)
                fin = message["type"] == "transcript" and message["role"] == "assistant"
                if (fin and message.get("final")) or message["type"] == "error":
                    break
            ws.send_json({"type": "stop"})
        outils = [m for m in recus if m["type"] == "tool"]
        assert outils and outils[0]["name"] == "clipboard_read", recus
        assert outils[0]["ok"] is False, "l'outil du Mac a répondu au téléphone"
        assert banc_vocal.espions["clipboard_read"].executions == [], (
            "le presse-papiers du Mac a été lu depuis le téléphone"
        )
        premier_tour = " ".join(str(m.get("content")) for m in banc_vocal.tours[0])
        assert "screen_read_text" not in premier_tour

    @staticmethod
    def _instructions_recues(banc_vocal, monkeypatch, **trame) -> str:
        """Ouvre une séance comme le VRAI client (``include_memory: true``,
        ``useVoiceLive.ts``) et rend les instructions que la séance a reçues
        de la route."""
        from diapason.speech.realtime import local_voice

        recues: list = []
        seance_de_banc = local_voice.LocalVoiceSession

        class _SeanceQuiNote(seance_de_banc):
            def __init__(self, **options):
                recues.append(options.get("instructions"))
                super().__init__(**options)

        monkeypatch.setattr(local_voice, "LocalVoiceSession", _SeanceQuiNote)
        with banc_vocal.websocket_connect(
            "/v1/voice/live", headers=_ws(banc_vocal.jeton)
        ) as ws:
            ws.send_json(
                {"type": "start", "provider": "local", "include_memory": True, **trame}
            )
            assert ws.receive_json() == {"type": "ready"}
            ws.send_json({"type": "stop"})
        assert len(recues) == 1, recues
        return recues[0] or ""

    def test_le_vrai_prompt_de_la_voix_du_telephone_n_apprend_pas_les_outils_du_mac(
        self, banc_vocal, monkeypatch
    ):
        """26/09/2026, contre-épreuve : le client envoie toujours
        ``include_memory: true``, et ce sont alors les instructions de la
        ROUTE qui remplacent le modèle de la séance. Le test de la séance
        passait ``instructions=""``, un chemin que le vrai client ne prend
        jamais : ``telephone=False`` passé à ``_load_system_instructions``
        laissait tout vert, et la voix réapprenait « **open_anything** »
        — elle promettait d'ouvrir Safari, puis l'exécuteur refusait."""
        instructions = self._instructions_recues(
            banc_vocal, monkeypatch, tools="current_time,vie_tasks"
        )
        assert "from the phone" in instructions, (
            "la voix du téléphone doit recevoir le prompt du téléphone"
        )
        for outil_du_mac in ("open_anything", "screen_read_text", "clipboard_read"):
            assert f"**{outil_du_mac}**" not in instructions, (
                f"le prompt du téléphone apprend {outil_du_mac}, un outil du Mac"
            )

    def test_sans_aucun_outil_permis_le_prompt_ne_promet_aucun_outil(
        self, banc_vocal, monkeypatch
    ):
        """Le client ne demande que des outils du Mac : la trousse du
        téléphone est vide, les outils sont coupés — et le prompt ne doit
        pas en décrire. Sans le rétrécissement de ``enable_tools`` dans la
        route, il listait **vie_tasks** à une séance qui ne l'a pas."""
        instructions = self._instructions_recues(
            banc_vocal, monkeypatch, tools="clipboard_read,open_anything"
        )
        assert "## Tools" not in instructions, (
            "une séance sans outil ne doit pas se voir décrire des outils"
        )
        assert "**vie_tasks**" not in instructions

    def test_un_fournisseur_distant_est_refuse(self, banc_vocal):
        with banc_vocal.websocket_connect(
            "/v1/voice/live", headers=_ws(banc_vocal.jeton)
        ) as ws:
            self._demarrer(ws, provider="gemini")
            refus = ws.receive_json()
        assert refus["type"] == "error"
        assert "téléphone" in refus["detail"], refus

    def test_la_voix_muette_du_telephone_est_coupee_par_le_mac(
        self, banc_vocal, monkeypatch
    ):
        """§78 : la coupure vit sur le Mac. Le téléphone qui ne dit plus rien
        — ou qu'on a mis en poche — est coupé, et la dernière trame dit
        pourquoi."""
        monkeypatch.setattr("diapason.speech.realtime.bridge.SILENCE_MAX_S", 0.3)
        with banc_vocal.websocket_connect(
            "/v1/voice/live", headers=_ws(banc_vocal.jeton)
        ) as ws:
            self._demarrer(ws, provider="local")
            assert ws.receive_json() == {"type": "ready"}
            assert ws.receive_json() == {"type": "closed", "reason": "inactivity"}
            with pytest.raises(WebSocketDisconnect) as fin:
                ws.receive_json()
        assert fin.value.code == 1000

    def test_la_sante_ne_promet_au_telephone_que_la_voix_locale(
        self, telephone, monkeypatch
    ):
        from diapason.core.origine_telephone import OUTILS_DU_TELEPHONE
        from diapason.speech.realtime import local_voice

        monkeypatch.setattr(
            local_voice, "local_voice_readiness", lambda *_a, **_k: (True, "ready")
        )
        # 28/09/2026 : Orion est la seule voix (depart-vocal-et-expression.md) ;
        # la santé dit la voix locale non configurée tant que son moteur manque.
        # Le test supposait un Mac où Orion est installé sans le simuler.
        monkeypatch.setattr(
            "diapason.speech.realtime.voix_expressive.moteur_installe", lambda: True
        )
        # Des clés présentes sur le Mac : le téléphone ne doit pas les voir
        # comme une voix qu'il peut démarrer.
        monkeypatch.setattr(
            "diapason.core.cloud_keys.get_cloud_key", lambda *_noms: "cle-du-mac"
        )
        reponse = telephone.get("/v1/voice/live/health")
        assert reponse.status_code == 200, reponse.text
        sante = reponse.json()
        assert sante["default_provider"] == "local"
        assert sante["providers"]["gemini"]["configured"] is False
        assert sante["providers"]["openai"]["configured"] is False
        assert sante["providers"]["local"]["configured"] is True
        assert set(sante["tools"]) <= OUTILS_DU_TELEPHONE, sante["tools"]

    def test_sans_le_moteur_d_orion_la_voix_locale_se_dit_non_configuree(
        self, telephone, monkeypatch
    ):
        """§100 : sans le moteur de la seule voix, la santé ne promet rien au
        téléphone et en dit la raison."""
        from diapason.speech.realtime import local_voice

        monkeypatch.setattr(
            local_voice, "local_voice_readiness", lambda *_a, **_k: (True, "ready")
        )
        monkeypatch.setattr(
            "diapason.speech.realtime.voix_expressive.moteur_installe", lambda: False
        )
        sante = telephone.get("/v1/voice/live/health").json()
        assert sante["providers"]["local"] == {
            "configured": False,
            "reason": "missing-expressive-voice",
        }, "un moteur absent ne se dit pas prêt"


class TestLaDicteeDuTelephone:
    """/v1/dictation/finalize est ouverte au téléphone sous session. Elle
    reconnaît les ordres dictés et les EXÉCUTAIT sur le Mac, par
    execute_voice_action, hors de ToolExecutor (26/09/2026)."""

    def test_ouvre_safari_dicte_au_telephone_reste_du_texte(
        self, telephone, monkeypatch
    ):
        from diapason.desktop import voice_commands

        actes: list = []
        monkeypatch.setattr(
            voice_commands,
            "execute_voice_action",
            lambda action: actes.append(action) or {"handled": True, "success": True},
        )
        reponse = telephone.post(
            "/v1/dictation/finalize",
            json={"text": "ouvre Safari", "polish": False},
            headers={"Origin": ICI},
        )
        assert reponse.status_code == 200, reponse.text
        assert actes == [], "la dictée du téléphone a ouvert une app sur le Mac"
        assert reponse.json()["mode"] != "command", reponse.json()
        assert "Safari" in reponse.json()["text"], "la dictée a perdu son texte"

    def test_temoin_sur_la_boucle_locale_la_dictee_commande(self, monde, monkeypatch):
        from diapason.desktop import voice_commands

        actes: list = []
        monkeypatch.setattr(
            voice_commands,
            "execute_voice_action",
            lambda action: actes.append(action) or {"handled": True, "success": True},
        )
        app, _ = _vraie_app()
        reponse = TestClient(app).post(
            "/v1/dictation/finalize",
            json={"text": "ouvre Safari", "polish": False},
            headers={"Authorization": f"Bearer {KEY}"},
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["mode"] == "command"
        assert actes and actes[0].kind == "focus_app"


def _espion_d_outil(nom: str):
    """Une classe d'outil enregistrable sous *nom*, qui note ses exécutions."""
    from diapason.core.types import ToolResult
    from diapason.tools._stubs import BaseTool, ToolSpec

    class _Espion(BaseTool):
        tool_id = nom
        executions: list = []

        @property
        def spec(self):
            return ToolSpec(name=nom, description=f"espion {nom}")

        def execute(self, **params):
            type(self).executions.append(params)
            return ToolResult(
                tool_name=nom, content="TEXTE-DE-L-ECRAN-DU-MAC", success=True
            )

    return _Espion


def _app_de_discussion(outil_reclame: str):
    """Une vraie app dont le moteur réclame *outil_reclame* au premier tour."""
    from diapason.core.config import DiapasonConfig
    from diapason.core.registry import ToolRegistry
    from diapason.engine._stubs import StreamChunk
    from diapason.server.app import create_app

    espions = {}
    for nom in ("screen_read_text", "clipboard_read", "vie_tasks"):
        espions[nom] = _espion_d_outil(nom)
        ToolRegistry.register_value(nom, espions[nom])

    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    vu: dict = {"schemas": [], "messages": []}

    async def stream_full(messages, **kwargs):
        vu["messages"].append(list(messages))
        vu["schemas"].append(
            [t["function"]["name"] for t in (kwargs.get("tools") or [])]
        )
        if len(vu["messages"]) == 1:
            yield StreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c0",
                        "type": "function",
                        "function": {"name": outil_reclame, "arguments": "{}"},
                    }
                ]
            )
        else:
            yield StreamChunk(content="Voilà.")

    engine.stream_full = stream_full
    config = DiapasonConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    config.agent.tools = "screen_read_text,clipboard_read,vie_tasks"
    app = create_app(engine, "test-model", api_key=KEY, config=config)
    return app, espions, vu


def _discuter(client: TestClient, texte: str, **entetes) -> list[tuple[str, dict]]:
    import json

    reponse = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": texte}],
            "stream": True,
        },
        headers=entetes,
    )
    assert reponse.status_code == 200, reponse.text
    evenements, nom = [], None
    for ligne in reponse.text.splitlines():
        if ligne.startswith("event: "):
            nom = ligne[7:].strip()
        elif ligne.startswith("data: ") and ligne[6:] != "[DONE]":
            try:
                evenements.append((nom or "chunk", json.loads(ligne[6:])))
            except ValueError:
                pass
            nom = None
    return evenements


class TestLaDiscussionDuTelephoneNeLitPasLeMac:
    """26/09/2026. La passerelle refusait /v1/context/* et /v1/screen_share/*,
    mais la Discussion portait screen_read_text et clipboard_read sans
    confirmation : « lis mon écran » depuis le téléphone rendait l'écran du
    Mac. Décidé : aucune action ni lecture du Mac depuis la Discussion du
    téléphone avant la phase 6."""

    @pytest.mark.parametrize("outil", ["screen_read_text", "clipboard_read"])
    def test_le_modele_qui_reclame_l_ecran_recoit_un_refus(self, monde, outil):
        app, espions, vu = _app_de_discussion(outil)
        client = TestClient(monde.passerelle(app), base_url=ICI)
        _ouvrir_une_session(client, monde)
        evts = _discuter(client, "lis mon écran", Origin=ICI)
        fin = next(d for n, d in evts if n == "tool_call_end")
        assert fin["success"] is False, f"{outil} a répondu au téléphone"
        assert "TEXTE-DE-L-ECRAN-DU-MAC" not in str(evts)
        assert espions[outil].executions == [], f"{outil} s'est exécuté"
        assert outil not in vu["schemas"][0], "le modèle voyait l'outil refusé"
        assert "vie_tasks" in vu["schemas"][0], "la trousse de données a disparu"

    def test_sur_la_boucle_locale_le_meme_appel_s_execute(self, monde):
        """La contre-épreuve : c'est bien l'origine qui décide, pas l'outil."""
        app, espions, vu = _app_de_discussion("screen_read_text")
        evts = _discuter(
            TestClient(app), "lis mon écran", Authorization=f"Bearer {KEY}"
        )
        fin = next(d for n, d in evts if n == "tool_call_end")
        assert fin["success"] is True
        assert espions["screen_read_text"].executions == [{}]
        assert "screen_read_text" in vu["schemas"][0]

    def test_le_cliche_du_bureau_n_entre_pas_dans_le_prompt(self, monde, monkeypatch):
        """L'ancre du prompt nomme l'onglet et la fenêtre au premier plan du
        Mac : le modèle l'aurait récitée au téléphone."""
        from diapason.desktop import etat_bureau

        cliche = etat_bureau.EtatBureau(
            premier_plan="Safari",
            en_marche=("Safari",),
            quand=0.0,
            onglet="Gmail — BROUILLON-SECRET",
        )
        monkeypatch.setattr(etat_bureau, "_cache", cliche)
        app, _, vu = _app_de_discussion("vie_tasks")
        client = TestClient(monde.passerelle(app), base_url=ICI)
        _ouvrir_une_session(client, monde)
        _discuter(client, "bonjour", Origin=ICI)
        assert "BROUILLON-SECRET" not in str(vu["messages"][0])
        _discuter(TestClient(app), "bonjour", Authorization=f"Bearer {KEY}")
        assert "BROUILLON-SECRET" in str(vu["messages"][-1]), (
            "contre-épreuve : sur la boucle locale le cliché doit y être"
        )

    @pytest.mark.parametrize(
        ("methode", "chemin"),
        [
            ("POST", "/v1/managed-agents"),
            ("POST", "/v1/managed-agents/a1/run"),
            ("POST", "/v1/managed-agents/a1/messages"),
            ("PATCH", "/v1/managed-agents/a1"),
            ("POST", "/v1/agents"),
            ("POST", "/v1/templates/t1/instantiate"),
        ],
    )
    def test_un_agent_ne_se_pose_ni_ne_se_lance_depuis_le_telephone(
        self, monde, methode, chemin
    ):
        """Un agent lancé dans un threading.Thread ou au prochain battement
        tourne hors du contexte de la requête, donc hors du plafond."""
        from diapason.core.config import DiapasonConfig
        from diapason.server.app import create_app

        gestionnaire = MagicMock()
        app = create_app(
            MagicMock(),
            "test-model",
            api_key=KEY,
            config=DiapasonConfig(),
            agent_manager=gestionnaire,
        )
        client = TestClient(monde.passerelle(app), base_url=ICI)
        _ouvrir_une_session(client, monde)
        reponse = client.request(methode, chemin, json={}, headers={"Origin": ICI})
        assert reponse.status_code == 403, reponse.text
        assert "agents" in reponse.json()["detail"]
        lances = [
            appel
            for appel in gestionnaire.method_calls
            if not appel[0].startswith(("list", "get"))
        ]
        assert lances == [], f"le gestionnaire a été sollicité : {lances}"


class TestLesEntetes:
    def test_la_passerelle_ouvre_le_micro_a_son_origine(self, telephone):
        reponse = telephone.get("/v1/models")
        assert "microphone=(self)" in reponse.headers["permissions-policy"]
        assert "wss://testserver" in reponse.headers["content-security-policy"]

    def test_la_csp_est_la_seule_garde_des_cadres_et_des_formulaires(self, telephone):
        """26/09/2026, contre-épreuve : la coquille ne voit ni les cadres
        (le greffon ne lui passe que le cadre principal) ni les navigations
        POST (Android n'appelle pas ``shouldOverrideUrlLoading`` pour elles).
        Un formulaire de la page du Mac posté vers un tiers aurait chargé
        sa page là où ``DiapasonNatif`` est injecté. ``form-action`` ne
        retombe pas sur ``default-src`` : sans lui, rien ne l'interdit."""
        for reponse in (
            telephone.get("/v1/models"),
            telephone.get("/v1/triggers/poll"),
        ):
            directives = {
                morceau.strip().split()[0]: morceau.strip().split()[1:]
                for morceau in reponse.headers["content-security-policy"].split(";")
                if morceau.strip()
            }
            assert directives.get("default-src") == ["'self'"], (
                "default-src 'self' est ce qui ferme les cadres d'une autre origine"
            )
            assert directives.get("frame-src", ["'self'"]) == ["'self'"], (
                "un frame-src plus large rouvrirait les cadres"
            )
            assert directives.get("child-src", ["'self'"]) == ["'self'"]
            assert directives.get("form-action") == ["'self'"], (
                f"{reponse.status_code} : un formulaire peut emmener la coquille "
                "ailleurs"
            )
            assert directives.get("object-src") == ["'none'"]
            assert directives.get("frame-ancestors") == ["'none'"]

    def test_la_boucle_locale_garde_le_micro_ferme(self):
        """Le plan : 8000 garde microphone=()."""
        app, _ = _vraie_app()
        reponse = TestClient(app).get("/health")
        assert "microphone=()" in reponse.headers["permissions-policy"]

    def test_chaque_reponse_de_la_passerelle_dit_qu_elle_vient_du_tailnet(
        self, telephone
    ):
        """26/09/2026 : sans ce signal, le bundle servi au téléphone sondait
        sans relâche les routes refusées — 403 toutes les 2 s. Le refus
        lui-même doit le porter : c'est souvent la première réponse lue."""
        servie = telephone.get("/v1/models")
        refusee = telephone.get("/v1/triggers/poll")
        sans_session = telephone.get(
            "/v1/models", headers={"Cookie": f"{COOKIE_APPAREIL}=faux"}
        )
        assert servie.status_code == 200, servie.text
        assert refusee.status_code == 403, "la route doit rester refusée"
        assert sans_session.status_code == 401
        for reponse in (servie, refusee, sans_session):
            assert reponse.headers.get("x-diapason-passerelle") == "tailnet", (
                f"{reponse.request.url.path} ({reponse.status_code}) ne dit pas "
                "qu'elle vient de la passerelle"
            )

    def test_la_boucle_locale_ne_se_dit_jamais_servie_par_le_tailnet(self):
        """Sur 8000, le Mac ne doit jamais se croire un téléphone : il
        cesserait de relever ses déclencheurs et sa voix."""
        app, _ = _vraie_app()
        reponse = TestClient(app).get("/health")
        assert "x-diapason-passerelle" not in reponse.headers

    def test_un_en_tete_forge_par_l_application_est_remplace(self, monde):
        """Un seul en-tête, celui de la passerelle : une valeur posée plus
        bas ne doit ni s'y ajouter ni le contredire."""
        app = FastAPI()

        @app.get("/health")
        def _sante():
            from fastapi.responses import JSONResponse

            return JSONResponse({"ok": True}, headers={"X-Diapason-Passerelle": "non"})

        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.get("/health")
        assert reponse.headers.get_list("x-diapason-passerelle") == ["tailnet"]

    def test_un_hote_forge_n_ecrit_pas_dans_la_csp(self, monde):
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.get("/health", headers={"Host": "x; script-src *"})
        assert "script-src *" not in reponse.headers["content-security-policy"]


# Au bout de ce délai, les handlers de banc ferment eux-mêmes en 4000. Sans
# lui, une passerelle qui ne couperait plus ferait PENDRE le test (le client
# de test n'a pas de délai de réception) au lieu de le faire échouer —
# constaté le 26/09/2026 en retirant la surveillance pour contre-épreuve.
_BANC_EXPIRE_S = 3.0
_CODE_BANC_EXPIRE = 4000


def _app_temoin():
    """Une app minuscule dont le WebSocket porte une clé « session »."""
    import asyncio

    app = FastAPI()
    vu: dict = {}

    @app.websocket("/v1/chat/stream")
    @app.websocket("/v1/voice/live")
    async def _flux(websocket: WebSocket):
        vu["scope"] = dict(websocket.scope)
        await websocket.accept()
        try:
            while True:
                try:
                    texte = await asyncio.wait_for(
                        websocket.receive_text(), _BANC_EXPIRE_S
                    )
                except TimeoutError:
                    await websocket.close(_CODE_BANC_EXPIRE)
                    return
                await websocket.send_text(f"écho:{texte}")
        except WebSocketDisconnect as fin:
            vu["fin"] = fin.code

    app.state.vu = vu
    return app


class TestLeMarquage:
    def test_ni_la_boucle_locale_ni_les_entetes_forgeables_ne_passent(self, monde):
        vu: dict = {}
        app = FastAPI()

        @app.get("/v1/models")
        async def _temoin(request: Request):
            vu.update(
                client=request.client.host,
                scheme=request.url.scheme,
                appareil=request.scope.get("diapason.appareil"),
                entetes={k.lower() for k in request.headers.keys()},
                cookie=request.headers.get("cookie", ""),
            )
            return {}

        client = TestClient(monde.passerelle(app), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        client.get(
            "/v1/models",
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "Tailscale-User-Login": "carlito@example.com",
                "Cookie": f"{COOKIE_APPAREIL}={jeton}; autre=1",
            },
        )
        assert vu["client"] == f"appareil:{PHONE}"
        assert vu["scheme"] == "https"
        assert vu["appareil"] == PHONE
        assert "x-forwarded-for" not in vu["entetes"]
        assert "tailscale-user-login" not in vu["entetes"]
        assert jeton not in vu["cookie"], "le jeton de session a atteint l'app"
        assert "autre=1" in vu["cookie"]

    def test_le_limiteur_range_le_telephone_dans_le_seau_de_l_appareil(
        self, telephone, monkeypatch
    ):
        """26/09/2026, contre-épreuve : un constat, et le commentaire de
        l'exemption de la cloche, disaient tout le trafic du téléphone rangé
        sous ``127.0.0.1:unauthenticated`` — un seau commun à tout client du
        tailnet. C'est le seau de l'APPAREIL : la passerelle réécrit le
        client avant que le limiteur ne le lise. Un autre appareil, ou la
        boucle locale, ne vident pas celui du téléphone."""
        import diapason.server.auth_middleware as am

        cles: list[str] = []
        original = am.RateLimiter.check

        def noter(limiteur, cle, *a, **k):
            cles.append(cle)
            return original(limiteur, cle, *a, **k)

        monkeypatch.setattr(am.RateLimiter, "check", noter)
        assert telephone.get("/v1/models").status_code == 200
        assert cles == [f"appareil:{PHONE}:unauthenticated"], cles


class TestLaMarqueDuTelephoneSuitLaRequete:
    """Le plafond d'outils lit une variable de contexte que seule la
    passerelle pose. Elle doit atteindre les trois endroits où un outil
    s'exécute : une route ``def`` (servie dans un fil par Starlette), un
    ``asyncio.to_thread`` (la boucle d'outils du chat) et le générateur d'une
    réponse en flux (le chat SSE) — et rester absente sur la boucle locale."""

    def test_route_synchrone_fil_et_flux(self, monde):
        import asyncio

        from starlette.responses import StreamingResponse

        from diapason.core.origine_telephone import depuis_le_telephone

        vu: dict = {}
        app = FastAPI()

        @app.get("/v1/models")
        def _synchrone():
            vu["def"] = depuis_le_telephone()
            return {}

        @app.get("/v1/info")
        async def _fil():
            vu["to_thread"] = await asyncio.to_thread(depuis_le_telephone)
            return {}

        @app.get("/v1/traces")
        async def _flux():
            async def morceaux():
                vu["flux"] = depuis_le_telephone()
                yield b"x"

            return StreamingResponse(morceaux())

        client = TestClient(monde.passerelle(app), base_url=ICI)
        _ouvrir_une_session(client, monde)
        for chemin in ("/v1/models", "/v1/info", "/v1/traces"):
            assert client.get(chemin).status_code == 200
        assert vu == {"def": True, "to_thread": True, "flux": True}, vu

        vu.clear()
        direct = TestClient(app)
        for chemin in ("/v1/models", "/v1/info", "/v1/traces"):
            direct.get(chemin)
        assert vu == {"def": False, "to_thread": False, "flux": False}, (
            "la marque a fui hors de la passerelle"
        )


class TestLaRevocation:
    def test_fermer_les_sessions_coupe_la_requete_suivante(self, telephone, monde):
        """Le plan (étape 9) : fermer depuis le Mac → 401 à la suivante."""
        assert telephone.get("/v1/models").status_code == 200
        monde.sessions.close_device_sessions(PHONE)
        assert telephone.get("/v1/models").status_code == 401

    def test_revoquer_coupe_la_requete_suivante(self, telephone, monde):
        assert telephone.get("/v1/models").status_code == 200
        monde.registry.revoke(PHONE)
        assert telephone.get("/v1/models").status_code == 401

    def test_un_websocket_ouvert_est_ferme_1008_apres_revocation(self, monde):
        """30 s au plus en production ; 50 ms ici, même mécanique."""
        app = _app_temoin()
        client = TestClient(monde.passerelle(app, intervalle_s=0.05), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        with client.websocket_connect("/v1/chat/stream", headers=_ws(jeton)) as ws:
            ws.send_text("un")
            assert ws.receive_text() == "écho:un"
            monde.registry.revoke(PHONE)
            debut = time.monotonic()
            with pytest.raises(WebSocketDisconnect) as coupure:
                ws.receive_text()
            assert coupure.value.code == 1008
            assert time.monotonic() - debut < 5, "la coupure a trop tardé"
        assert app.state.vu["fin"] == 1008, "le handler n'a pas appris la coupure"

    def test_un_flux_qui_ne_fait_qu_emettre_est_coupe_aussi(self, monde):
        """/v1/agents/events n'écoute jamais le client : il émet. Une coupure
        qui n'arriverait que par receive() ne l'atteindrait pas."""
        import asyncio

        app = FastAPI()
        fin: dict = {}

        @app.websocket("/v1/agents/events")
        async def _evenements(websocket: WebSocket):
            await websocket.accept()
            debut = time.monotonic()
            try:
                while time.monotonic() - debut < _BANC_EXPIRE_S:
                    await websocket.send_text("tic")
                    await asyncio.sleep(0.02)
                await websocket.close(_CODE_BANC_EXPIRE)
            except WebSocketDisconnect as coupure:
                fin["code"] = coupure.code

        client = TestClient(monde.passerelle(app, intervalle_s=0.05), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        with client.websocket_connect("/v1/agents/events", headers=_ws(jeton)) as ws:
            assert ws.receive_text() == "tic"
            monde.sessions.close_device_sessions(PHONE)
            debut = time.monotonic()
            with pytest.raises(WebSocketDisconnect) as coupure:
                while time.monotonic() - debut < 5:
                    ws.receive_text()
            assert coupure.value.code == 1008
            # Laisser au handler le temps de tenter son envoi suivant avant
            # que la sortie du bloc n'annule sa tâche.
            time.sleep(0.2)
        assert "code" in fin, "l'émetteur a continué d'écrire dans le vide"

    def test_un_websocket_vivant_reste_ouvert_tant_que_la_session_vit(self, monde):
        app = _app_temoin()
        client = TestClient(monde.passerelle(app, intervalle_s=0.05), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        with client.websocket_connect("/v1/chat/stream", headers=_ws(jeton)) as ws:
            for rang in range(3):
                time.sleep(0.12)
                ws.send_text(str(rang))
                assert ws.receive_text() == f"écho:{rang}"
        assert app.state.vu["scope"]["diapason.appareil"] == PHONE


class TestLIntervalleDeProduction:
    def test_trente_secondes_au_plus(self):
        """Décidé au plan : la révocation coupe un WebSocket en 30 s au plus.
        Les tests de coupure injectent 50 ms ; celui-ci lit la valeur que la
        passerelle reçoit quand personne ne lui en donne."""
        from diapason.server.passerelle_tailnet import INTERVALLE_DE_CONTROLE_S

        assert INTERVALLE_DE_CONTROLE_S <= 30
        passerelle = PasserelleTailnet(FastAPI(), adresse="")
        assert passerelle._intervalle_s == INTERVALLE_DE_CONTROLE_S


def _pilote_asgi(passerelle, scope: dict, *, apres_premier_morceau=None):
    """Pilote la passerelle en ASGI direct et rend (morceaux, durée).

    TestClient met toute la réponse en tampon : un flux coupé ou non s'y lit
    pareil. Ici, chaque ``http.response.body`` arrive à son heure."""
    import asyncio

    async def scenario():
        morceaux: list[bytes] = []
        fin = asyncio.Event()
        corps_envoye = False

        async def recevoir():
            nonlocal corps_envoye
            if not corps_envoye:
                corps_envoye = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await fin.wait()
            return {"type": "http.disconnect"}

        async def envoyer(message):
            if message["type"] == "http.response.body":
                morceaux.append(message.get("body", b""))
                if len(morceaux) == 1 and apres_premier_morceau:
                    apres_premier_morceau()
                if not message.get("more_body"):
                    fin.set()

        debut = time.monotonic()
        try:
            await asyncio.wait_for(passerelle(scope, recevoir, envoyer), 6)
        finally:
            fin.set()
        return b"".join(morceaux), time.monotonic() - debut

    return asyncio.run(scenario())


def _portee_http(chemin: str, jeton: str) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": chemin,
        "raw_path": chemin.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"cookie", f"{COOKIE_APPAREIL}={jeton}".encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8002),
    }


class TestUnFluxHttpEstCoupeAussi:
    def test_la_revocation_coupe_une_reponse_en_flux(self, monde):
        """Le SSE du chat est une réponse HTTP qui dure : sans la surveillance,
        un téléphone révoqué garderait sa réponse jusqu'au bout."""
        import asyncio

        from starlette.responses import StreamingResponse

        app = FastAPI()

        @app.get("/v1/models")
        async def _flux():
            async def morceaux():
                debut = time.monotonic()
                while time.monotonic() - debut < 4:
                    yield b"tic\n"
                    await asyncio.sleep(0.02)
                yield b"FIN-NATURELLE\n"

            return StreamingResponse(morceaux())

        passerelle = monde.passerelle(app, intervalle_s=0.05)
        client = TestClient(passerelle, base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        corps, duree = _pilote_asgi(
            passerelle,
            _portee_http("/v1/models", jeton),
            apres_premier_morceau=lambda: monde.registry.revoke(PHONE),
        )
        assert b"tic" in corps
        assert b"FIN-NATURELLE" not in corps, "le flux a survécu à la révocation"
        assert duree < 2, f"la coupure a pris {duree:.2f} s"


def _trou_maximal(passerelle, requete) -> float:
    """Le plus long silence d'un cœur qui bat toutes les 10 ms pendant
    *requete* — démarré AVANT elle, pour voir la boucle geler."""
    import asyncio

    from httpx import ASGITransport, AsyncClient

    async def scenario():
        instants: list[float] = []
        arret = asyncio.Event()

        async def coeur():
            # Un battement AUSSI au réveil qui suit l'arrêt : une requête qui
            # ne suspend jamais (ASGITransport) finit avant que le cœur ne se
            # réveille, et sans ce dernier instant le gel ne se mesurerait pas.
            while True:
                instants.append(time.monotonic())
                if arret.is_set():
                    return
                await asyncio.sleep(0.01)

        battre = asyncio.ensure_future(coeur())
        await asyncio.sleep(0.05)
        async with AsyncClient(
            transport=ASGITransport(app=passerelle), base_url=ICI
        ) as client:
            await requete(client)
        arret.set()
        await battre
        return max(b - a for a, b in zip(instants, instants[1:]))

    return asyncio.run(scenario())


_LENT_S = 0.5
_TROU_TOLERE_S = 0.3


def _ralentir(objet, nom: str) -> None:
    lente = getattr(objet, nom)

    def appel(*args, **kwargs):
        time.sleep(_LENT_S)
        return lente(*args, **kwargs)

    setattr(objet, nom, appel)


class TestLaBoucleResteLibre:
    """CLAUDE.md §5 : une route async qui appelle du bloquant gèle TOUT —
    le flux du chat, la voix, la cloche. verify_session écrit sur mesh.db
    (la dernière activité) ; les quatre asyncio.to_thread de la passerelle
    pouvaient être retirés sans qu'un test le voie (mutants M67 à M70)."""

    def test_pendant_la_verification_de_session(self, monde):
        _ralentir(monde.sessions, "verify_session")
        app, _ = _vraie_app()

        async def requete(client):
            await client.get(
                "/v1/models", headers={"Cookie": f"{COOKIE_APPAREIL}=inconnu"}
            )

        trou = _trou_maximal(monde.passerelle(app), requete)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s"

    def test_pendant_l_echange_du_ticket(self, monde):
        _ralentir(monde.sessions, "redeem_ticket")
        app, _ = _vraie_app()

        async def requete(client):
            await client.post("/v1/appareil/ouvrir", data={"ticket": "t"})

        trou = _trou_maximal(monde.passerelle(app), requete)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s"

    def test_pendant_la_verification_de_l_enveloppe(self, monde):
        _ralentir(monde.sessions, "issue_ticket")
        app, _ = _vraie_app()
        demande = monde.demande_signee()

        async def requete(client):
            reponse = await client.post("/v1/appareil/session", json=demande)
            assert reponse.status_code == 200, reponse.text

        trou = _trou_maximal(monde.passerelle(app), requete)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s"

    def test_pendant_la_surveillance_d_un_flux(self, monde):
        import asyncio

        from starlette.responses import StreamingResponse

        app = FastAPI()

        @app.get("/v1/models")
        async def _flux():
            async def morceaux():
                for _ in range(40):
                    yield b"."
                    await asyncio.sleep(0.02)

            return StreamingResponse(morceaux())

        passerelle = monde.passerelle(app, intervalle_s=0.05)
        jeton = _ouvrir_une_session(TestClient(passerelle, base_url=ICI), monde)
        # La première vérification (à l'entrée) reste rapide ; ce sont les
        # suivantes, celles de la surveillance, qui traînent.
        verifier = monde.sessions.verify_session
        appels = {"n": 0}

        def lente(j):
            appels["n"] += 1
            if appels["n"] > 1:
                time.sleep(_LENT_S)
            return verifier(j)

        monde.sessions.verify_session = lente

        async def requete(client):
            await client.get(
                "/v1/models", headers={"Cookie": f"{COOKIE_APPAREIL}={jeton}"}
            )

        trou = _trou_maximal(passerelle, requete)
        assert appels["n"] > 1, "la surveillance n'a pas tourné"
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s"


class TestLeCycleDeVie:
    def test_la_passerelle_ne_relance_pas_le_cycle_de_vie_de_l_app(self, monde):
        """Sans cela : deux battements du maillage, deux tâches de synchro
        du compte, et le magasin des conversations fermé deux fois."""
        from contextlib import asynccontextmanager

        demarrages = []

        @asynccontextmanager
        async def _cycle(_app):
            demarrages.append(1)
            yield

        app = FastAPI(lifespan=_cycle)
        with TestClient(monde.passerelle(app), base_url=ICI):
            pass
        assert demarrages == [], "le lifespan de l'app a tourné via la passerelle"


class TestLAdresseDuTailnet:
    @pytest.mark.parametrize(
        ("posee", "attendue"),
        [
            ("", None),
            ("atelier.tail6efbba.ts.net", "https://atelier.tail6efbba.ts.net"),
            ("https://Atelier.tail6efbba.ts.net/", "https://atelier.tail6efbba.ts.net"),
            ("http://atelier.tail6efbba.ts.net", None),
            ("https://x; script-src *", None),
        ],
    )
    def test_jamais_devinee_toujours_https(self, posee, attendue):
        from diapason.core.config import DiapasonConfig

        config = DiapasonConfig()
        config.tailnet.adresse = posee
        assert adresse_du_tailnet(config) == attendue

    def test_la_cle_se_lit_dans_config_toml(self, tmp_path):
        from diapason.core.config import load_config

        chemin = tmp_path / "config.toml"
        chemin.write_text(
            '[tailnet]\nadresse = "https://atelier.tail6efbba.ts.net"\n',
            encoding="utf-8",
        )
        assert load_config(chemin).tailnet.adresse == (
            "https://atelier.tail6efbba.ts.net"
        )
