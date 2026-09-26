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

        client = TestClient(monde.passerelle(app), base_url=ICI)
        jeton = _ouvrir_une_session(client, monde)
        reponse = client.get(
            "/v1/ajoutee-demain", headers={"Cookie": f"{COOKIE_APPAREIL}={jeton}"}
        )
        assert reponse.status_code == 403
        assert "fuite" not in reponse.text

    def test_une_route_de_vie_inventee_n_herite_pas_de_ses_voisines(self, monde):
        app, _ = _vraie_app()

        @app.get("/v1/vie/inventee")
        def _inventee():  # pragma: no cover
            return {"fuite": True}

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

    def test_la_voix_reste_fermee_avec_une_session(self, banc):
        """§78 : aucune coupure automatique n'existe encore pour la voix ;
        elle n'ouvre au téléphone qu'en phase 4."""
        with pytest.raises(WebSocketDisconnect) as refus:
            with banc.websocket_connect(
                "/v1/voice/live", headers=_ws(banc.jeton)
            ) as ws:
                ws.receive_text()
        assert refus.value.code == 1008
        assert "phase 4" in refus.value.reason, refus.value.reason

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
        app, _ = _vraie_app()
        client = TestClient(monde.passerelle(app), base_url=ICI)
        reponse = client.post(
            "/v1/mesh/commands/poll",
            json={},
            headers={"Origin": "https://exemple.com"},
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


class TestLesEntetes:
    def test_la_passerelle_ouvre_le_micro_a_son_origine(self, telephone):
        reponse = telephone.get("/v1/models")
        assert "microphone=(self)" in reponse.headers["permissions-policy"]
        assert "wss://testserver" in reponse.headers["content-security-policy"]

    def test_la_boucle_locale_garde_le_micro_ferme(self):
        """Le plan : 8000 garde microphone=()."""
        app, _ = _vraie_app()
        reponse = TestClient(app).get("/health")
        assert "microphone=()" in reponse.headers["permissions-policy"]

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
