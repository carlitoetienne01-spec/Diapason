"""Le mode gestes : armer, voir, et se refermer tout seul.

Spatial Mesh, gestes — 25 août 2026. Le §78 gouverne : rien ne guette en
permanence. Ces tests vérifient surtout ce qui ÉTEINT — un mode armé qu'on
oublierait laisserait la caméra allumée, et le voyant vert cesserait de
dire la vérité.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.server import gestes_routes as gr  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(gr.router)
    gr.desarmer()
    with TestClient(app) as c:
        yield c
    gr.desarmer()


def _image_factice() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"x" * 200  # en-tête JPEG plausible


class TestArmement:
    def test_rien_ne_guette_avant_l_armement(self, client):
        assert client.get("/v1/gestures/state").json() == {"armed": False}

    def test_une_image_sans_armement_est_refusee(self, client):
        """Poster des images sans armer serait une caméra qui tourne sans
        que personne ne l'ait demandé."""
        reponse = client.post("/v1/gestures/frame", content=_image_factice())
        assert reponse.status_code == 409
        assert "pas armé" in reponse.json()["detail"]

    def test_armer_puis_desarmer(self, client):
        assert client.post("/v1/gestures/arm").json()["armed"] is True
        assert client.get("/v1/gestures/state").json()["armed"] is True
        assert client.post("/v1/gestures/disarm").json()["armed"] is False
        assert client.get("/v1/gestures/state").json()["armed"] is False

    def test_sans_vision_l_armement_est_refuse_franchement(self, client):
        """Armer sans moteur de reconnaissance allumerait la caméra pour
        rien — le §5 interdit de faire semblant."""
        with patch("diapason.desktop.vision_mains.disponible", return_value=False):
            reponse = client.post("/v1/gestures/arm")
        assert reponse.status_code == 503
        assert "pyobjc-framework-Vision" in reponse.json()["detail"]


class TestLesImages:
    def test_une_image_fait_avancer_l_etat(self, client):
        client.post("/v1/gestures/arm")
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets", return_value=[]
        ):
            reponse = client.post("/v1/gestures/frame", content=_image_factice())
        corps = reponse.json()
        assert corps["state"] == "REPOS"
        assert corps["hand"] is False
        assert corps["frames"] == 1

    def test_une_main_vue_est_signalee(self, client):
        from diapason.desktop.gestes_main import Point

        client.post("/v1/gestures/arm")
        main = [
            Point("wrist", 0.5, 0.9),
            Point("indexMCP", 0.42, 0.7),
            Point("littleMCP", 0.62, 0.7),
            Point("indexTip", 0.42, 0.2),
            Point("middleMCP", 0.48, 0.7),
            Point("middleTip", 0.48, 0.2),
            Point("ringMCP", 0.55, 0.7),
            Point("ringTip", 0.55, 0.2),
            Point("littleTip", 0.62, 0.25),
            Point("thumbCMC", 0.38, 0.82),
            Point("thumbTip", 0.3, 0.5),
        ]
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets",
            return_value=[main],
        ):
            reponse = client.post("/v1/gestures/frame", content=_image_factice())
        assert reponse.json()["hand"] is True

    def test_une_image_vide_est_refusee(self, client):
        client.post("/v1/gestures/arm")
        assert client.post("/v1/gestures/frame", content=b"").status_code == 400

    def test_une_image_geante_est_refusee(self, client):
        client.post("/v1/gestures/arm")
        enorme = b"\xff\xd8" + b"x" * (5 * 1024 * 1024)
        assert client.post("/v1/gestures/frame", content=enorme).status_code == 413

    def test_une_image_illisible_ne_fait_pas_tomber_la_session(self, client):
        client.post("/v1/gestures/arm")
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets",
            side_effect=RuntimeError("pas une image"),
        ):
            assert client.post(
                "/v1/gestures/frame", content=_image_factice()
            ).status_code == 400
        # La session tient : une image ratée n'est pas une panne de mode.
        assert client.get("/v1/gestures/state").json()["armed"] is True


class TestCeQuiEteint:
    def test_le_silence_desarme_tout_seul(self, client, monkeypatch):
        """Un mode armé qu'on oublierait laisserait la caméra allumée."""
        client.post("/v1/gestures/arm")
        assert gr.session_active() is True
        import time as _t

        depart = _t.monotonic()
        monkeypatch.setattr(
            gr.time, "monotonic", lambda: depart + gr._INACTIVITE_MAX_S + 1
        )
        assert gr.session_active() is False
        assert client.get("/v1/gestures/state").json() == {"armed": False}

    def test_la_duree_maximale_desarme_meme_si_on_bouge(self, client, monkeypatch):
        """Le §83 : la caméra coûte. Une session ne tient pas une heure
        parce que quelqu'un agite la main devant."""
        client.post("/v1/gestures/arm")
        import time as _t

        depart = _t.monotonic()
        # Vu à l'instant, mais armé depuis trop longtemps.
        gr._session.vue_a = depart + gr._DUREE_MAX_S
        monkeypatch.setattr(
            gr.time, "monotonic", lambda: depart + gr._DUREE_MAX_S + 1
        )
        assert gr.session_active() is False


class TestLesDeuxChemins:
    """L'image arrive en binaire OU en base64 — et le second n'est pas un luxe.

    WKWebView, le moteur de la fenêtre Diapason, échoue sur un corps de
    requête binaire avec un « Load failed » opaque : ni CORS, ni le port, ni
    le type de corps (Blob puis ArrayBuffer) n'expliquaient l'échec, alors
    que la même requête passait en ligne de commande. Le JSON est le chemin
    que toute l'application emprunte déjà.
    """

    def _armer(self, client):
        client.post("/v1/gestures/arm")

    def test_le_chemin_binaire_marche(self, client):
        self._armer(client)
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets", return_value=[]
        ) as vision:
            reponse = client.post(
                "/v1/gestures/frame",
                content=_image_factice(),
                headers={"Content-Type": "image/jpeg"},
            )
        assert reponse.status_code == 200
        assert vision.call_args[0][0] == _image_factice()

    def test_le_chemin_base64_donne_les_memes_octets(self, client):
        """Ce qui arrive à Vision doit être IDENTIQUE par les deux chemins :
        sinon l'un des deux reconnaîtrait des mains que l'autre rate."""
        import base64

        self._armer(client)
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets", return_value=[]
        ) as vision:
            reponse = client.post(
                "/v1/gestures/frame",
                json={"image": base64.b64encode(_image_factice()).decode("ascii")},
            )
        assert reponse.status_code == 200
        assert vision.call_args[0][0] == _image_factice()

    def test_un_base64_invalide_le_dit_franchement(self, client):
        self._armer(client)
        reponse = client.post("/v1/gestures/frame", json={"image": "pas du base64!!"})
        assert reponse.status_code == 400
        assert "illisible" in reponse.json()["detail"]

    def test_un_json_sans_image_est_traite_comme_vide(self, client):
        self._armer(client)
        assert client.post("/v1/gestures/frame", json={}).status_code == 400


class TestLeDebitDesImages:
    """Le défaut qui a coûté quatre allers-retours de diagnostic.

    Douze images par seconde est un usage NORMAL du mode gestes. Le seau
    ordinaire — soixante par minute, rafale de dix — était épuisé en moins
    d'une seconde, et les images suivantes revenaient en 429. Pire : ce 429,
    émis par le middleware, court-circuitait CORSMiddleware et arrivait donc
    SANS en-têtes. Vu de la fenêtre, il devenait « Load failed » : un
    message qui ne dit ni le code, ni la raison, ni où chercher.
    """

    def test_les_gestes_ont_leur_propre_seau(self):
        from diapason.server.auth_middleware import est_route_de_gestes

        for chemin in ("/v1/gestures/arm", "/v1/gestures/frame",
                       "/v1/gestures/state", "/v1/gestures/disarm"):
            assert est_route_de_gestes(chemin), (
                f"{chemin} partagerait le seau ordinaire, épuisé en une seconde"
            )

    def test_le_seau_des_gestes_tient_douze_images_par_seconde(self):
        """Une rafale d'une seconde ne doit pas être refusée."""
        from diapason.security.rate_limiter import RateLimitConfig, RateLimiter
        from diapason.server.auth_middleware import RateLimitMiddleware

        mur = RateLimitMiddleware(app=None)
        refus = [
            i
            for i in range(24)  # deux secondes à douze images
            if not mur._gesture_limiter.check("test:gestures")[0]
        ]
        assert not refus, f"refusé dès l'image {refus[0] + 1} sur vingt-quatre"

    def test_un_refus_reste_lisible_par_celui_qu_il_refuse(self):
        """Un 429 sans en-tête CORS est un refus muet : le navigateur ne
        peut pas le lire et affiche un échec réseau générique."""
        from starlette.requests import Request

        from diapason.server.auth_middleware import _too_many

        portee = {
            "type": "http",
            "headers": [(b"origin", b"tauri://localhost")],
        }
        reponse = _too_many(2.0, Request(portee))
        assert reponse.status_code == 429
        assert reponse.headers["access-control-allow-origin"] == "tauri://localhost"
        assert reponse.headers["Retry-After"] == "2"

    def test_sans_origine_le_refus_reste_valide(self):
        """Une requête en ligne de commande n'a pas d'origine : elle ne doit
        pas pour autant recevoir un en-tête vide ou faux."""
        from starlette.requests import Request

        from diapason.server.auth_middleware import _too_many

        reponse = _too_many(1.0, Request({"type": "http", "headers": []}))
        assert reponse.status_code == 429
        assert "access-control-allow-origin" not in reponse.headers
