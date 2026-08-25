"""Le mode gestes : armer, voir, et se refermer tout seul.

Spatial Mesh, gestes — 25 août 2026. Le §78 gouverne : rien ne guette en
permanence. Ces tests vérifient surtout ce qui ÉTEINT — un mode armé qu'on
oublierait laisserait la caméra allumée, et le voyant vert cesserait de
dire la vérité.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
    gr._ecouteur_claps = None
    with TestClient(app) as c:
        yield c
    gr.desarmer()
    # Un micro laissé ouvert par un test le laisserait ouvert pour les
    # suivants — et pour la machine.
    gr._ecouteur_claps = None


def _image_factice() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"x" * 200  # en-tête JPEG plausible


class TestArmement:
    def test_rien_ne_guette_avant_l_armement(self, client):
        etat = client.get("/v1/gestures/state").json()
        assert etat["armed"] is False

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
        assert client.get("/v1/gestures/state").json()["armed"] is False

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


class TestLesChiffresQuiPermettentDeJuger:
    """§141 : un geste n'est fini que quand ses faux positifs sont MESURÉS.

    Le serveur ne peut pas savoir ce que l'utilisateur voulait — il compte
    donc ce qui s'est produit, et c'est l'humain qui dit combien étaient
    voulus. Compter à sa place serait inventer.
    """

    def _main_ouverte(self):
        from diapason.desktop.gestes_main import Point

        pts = [
            Point("wrist", 0.5, 0.9),
            Point("indexMCP", 0.42, 0.7),
            Point("littleMCP", 0.62, 0.7),
            Point("thumbCMC", 0.38, 0.82),
            Point("thumbTip", 0.3, 0.25),
        ]
        for i, doigt in enumerate(("index", "middle", "ring", "little")):
            base = 0.42 + i * 0.066
            pts.append(Point(f"{doigt}MCP", base, 0.7))
            pts.append(Point(f"{doigt}Tip", base, 0.18))
        return pts

    def test_les_compteurs_partent_de_zero(self, client):
        client.post("/v1/gestures/arm")
        etat = client.get("/v1/gestures/state").json()
        assert etat["grabs"] == 0 and etat["releases"] == 0 and etat["losses"] == 0

    def test_la_proportion_de_mains_vues_se_mesure(self, client):
        """Un mauvais éclairage ou une main hors champ se voient là, et
        expliquent pourquoi les gestes « ne marchent pas »."""
        client.post("/v1/gestures/arm")
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets", return_value=[]
        ):
            for _ in range(3):
                client.post("/v1/gestures/frame", content=_image_factice())
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets",
            return_value=[self._main_ouverte()],
        ):
            client.post("/v1/gestures/frame", content=_image_factice())
        etat = client.get("/v1/gestures/state").json()
        assert etat["frames"] == 4
        assert etat["handsSeen"] == 1
        assert etat["handRatio"] == 0.25

    def test_la_confiance_moyenne_est_rapportee(self, client):
        from diapason.desktop.gestes_main import Point

        client.post("/v1/gestures/arm")
        floue = [Point(p.nom, p.x, p.y, confiance=0.4) for p in self._main_ouverte()]
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets",
            return_value=[floue],
        ):
            client.post("/v1/gestures/frame", content=_image_factice())
        assert client.get("/v1/gestures/state").json()["confidence"] == 0.4

    def test_le_serveur_ne_pretend_pas_savoir_ce_qui_etait_voulu(self, client):
        """Aucun champ ne prétend distinguer un vrai geste d'un faux : ce
        jugement appartient à l'humain, et l'inventer serait mentir."""
        client.post("/v1/gestures/arm")
        etat = client.get("/v1/gestures/state").json()
        for invente in ("falsePositives", "intended", "accuracy", "reliability"):
            assert invente not in etat


class TestAttraperEtDeposer:
    """Le geste agit — mais ne devine jamais où (§34).

    Aucun capteur de cette flotte ne mesure une direction. Un geste qui
    enverrait un document à un appareil choisi au hasard serait l'échec le
    plus grave de cette fonctionnalité.
    """

    def _contexte(self):
        from diapason.desktop import contexte_app as ca

        ca.poser_contexte(
            "/succes/projects", ressource_type="project",
            ressource_id="p1", ressource_titre="Zéro à Héro",
        )

    def _appareil(self, nom, etat, capacites=("app.show_resource", "app.navigate")):
        """Un appareil de la flotte — capacités comprises.

        Les capacités ne sont pas décoratives : un appareil joignable qui ne
        déclare pas « app.show_resource » n'est pas un candidat, et le
        proposer ferait poser une question dont l'une des réponses est un
        refus garanti. Le registre réel les porte toujours ; les omettre ici
        revenait à tester une flotte qui n'existe pas.
        """
        return {
            "deviceId": f"dev_{nom}",
            "name": nom,
            "trustLevel": "TRUSTED",
            "capabilities": list(capacites),
        }

    def test_rien_de_tenu_se_dit_au_lieu_de_rien_faire(self):
        from diapason.desktop import presse_papiers_spatial as pp
        from diapason.server.gestes_routes import _deposer

        pp.vider()
        resultat = _deposer()
        assert resultat["done"] is False
        assert resultat["reason"] == "NOTHING_HELD"

    def test_tous_hors_ligne_le_dit_avec_les_noms(self):
        from diapason.desktop import presse_papiers_spatial as pp
        from diapason.server.gestes_routes import _deposer

        self._contexte()
        pp.attraper()
        with patch(
            "diapason.mesh.registry.DeviceRegistry.list_devices",
            return_value=[self._appareil("PC du bureau", "OFFLINE")],
        ), patch(
            "diapason.mesh.presence.presence_of", return_value={"state": "OFFLINE"}
        ):
            resultat = _deposer()
        assert resultat["done"] is False
        assert resultat["reason"] == "ALL_OFFLINE"
        assert "PC du bureau" in resultat["message"]
        assert "Zéro à Héro" in resultat["message"]

    def test_deux_candidats_font_poser_la_question(self):
        """§81 : deux appareils joignables, aucune direction mesurée — on
        demande, on ne tire pas au sort."""
        from diapason.desktop import presse_papiers_spatial as pp
        from diapason.server.gestes_routes import _deposer

        self._contexte()
        pp.attraper()
        with patch(
            "diapason.mesh.registry.DeviceRegistry.list_devices",
            return_value=[self._appareil("iPad", "ONLINE"),
                          self._appareil("PC", "ONLINE")],
        ), patch(
            "diapason.mesh.presence.presence_of", return_value={"state": "ONLINE"}
        ), patch("diapason.mesh.dispatch.dispatch_command") as envoi:
            resultat = _deposer()
        assert resultat["reason"] == "AMBIGUOUS"
        assert set(resultat["candidates"]) == {"iPad", "PC"}
        envoi.assert_not_called(), "rien ne doit partir vers un appareil deviné"

    def test_un_seul_appareil_joignable_recoit(self):
        from diapason.desktop import presse_papiers_spatial as pp
        from diapason.server.gestes_routes import _deposer

        self._contexte()
        pp.attraper()
        with patch(
            "diapason.mesh.registry.DeviceRegistry.list_devices",
            return_value=[self._appareil("iPad", "ONLINE")],
        ), patch(
            "diapason.mesh.presence.presence_of", return_value={"state": "ONLINE"}
        ), patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS",
                          "userSafeMessage": "Le projet est affiché sur Succès."},
        ) as envoi:
            resultat = _deposer()
        assert resultat["done"] is True
        assert resultat["target"] == "iPad"
        # La phrase vient du RÉCEPTEUR, jamais de ce qu'on a envoyé.
        assert resultat["message"] == "Le projet est affiché sur Succès."
        assert envoi.call_args.kwargs["arguments"] == {
            "resourceType": "project",
            "resourceId": "p1",
        }


class TestTrancherEntreDeuxAppareils:
    """« Vers lequel ? » est une question — encore faut-il pouvoir répondre.

    Le §81 la fait poser dès que deux appareils sont capables, et c'est
    juste. Mais une question sans moyen d'y répondre n'est pas de la
    prudence, c'est une impasse : la main se vidait en la posant, si bien
    que refaire le geste ne pouvait que la reposer, indéfiniment.
    """

    def _contexte(self):
        from diapason.desktop import contexte_app as ca

        ca.poser_contexte(
            "/succes/projects", ressource_type="project",
            ressource_id="p1", ressource_titre="Zéro à Héro",
        )

    def _appareil(self, nom, capacites=("app.show_resource", "app.navigate")):
        return {
            "deviceId": f"dev_{nom}",
            "name": nom,
            "trustLevel": "TRUSTED",
            "capabilities": list(capacites),
        }

    def _poser_la_question(self, client, *appareils):
        """Armer, attraper, puis ouvrir la main devant plusieurs appareils."""
        from diapason.desktop import presse_papiers_spatial as pp
        from diapason.server import gestes_routes as gr

        client.post("/v1/gestures/arm")
        self._contexte()
        pp.attraper()
        joignables = appareils or (self._appareil("iPad"), self._appareil("PC"))
        with patch(
            "diapason.mesh.registry.DeviceRegistry.list_devices",
            return_value=list(joignables),
        ), patch(
            "diapason.mesh.presence.presence_of", return_value={"state": "ONLINE"}
        ), patch("diapason.mesh.dispatch.dispatch_command") as envoi:
            resultat = gr._deposer()
            gr._session.dernier_depot = resultat
            if resultat.get("reason") == "AMBIGUOUS":
                envoi.assert_not_called(), "rien ne part tant qu'on n'a pas tranché"
        return resultat

    def test_un_depot_ambigu_ne_perd_pas_l_objet(self, client):
        """Le défaut historique : `lacher()` vidait la main AVANT de savoir
        s'il existait une cible. La question consommait ce qu'elle
        proposait d'envoyer."""
        from diapason.desktop import presse_papiers_spatial as pp

        resultat = self._poser_la_question(client)
        assert resultat["reason"] == "AMBIGUOUS"
        assert pp.tenu() is not None, "la main reste fermée le temps de répondre"
        assert pp.tenu().id == "p1"

    def test_l_etat_publie_la_question(self, client):
        """Le geste se fait sur la page d'un projet, pas sur la page
        Appareils : la question doit voyager par le sondage d'état."""
        self._poser_la_question(client)
        attente = client.get("/v1/gestures/state").json()["pendingDrop"]
        assert attente is not None
        assert attente["object"]["title"] == "Zéro à Héro"
        assert {c["name"] for c in attente["candidates"]} == {"iPad", "PC"}
        assert all(c["deviceId"] for c in attente["candidates"])
        assert 0 < attente["secondsLeft"] <= 45.0

    def test_le_choix_envoie_vers_l_appareil_nomme(self, client):
        from diapason.desktop import presse_papiers_spatial as pp

        jeton = self._poser_la_question(client)["token"]
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS",
                          "userSafeMessage": "Le projet est affiché sur Succès."},
        ) as envoi:
            reponse = client.post(
                "/v1/gestures/drop/target",
                json={"token": jeton, "deviceId": "dev_iPad"},
            )
        corps = reponse.json()
        assert reponse.status_code == 200
        assert corps["done"] is True
        assert corps["target"] == "iPad"
        # La phrase vient du RÉCEPTEUR, jamais de ce qu'on a envoyé.
        assert corps["message"] == "Le projet est affiché sur Succès."
        assert envoi.call_args.kwargs["target_device_id"] == "dev_iPad"
        assert envoi.call_args.kwargs["arguments"] == {
            "resourceType": "project",
            "resourceId": "p1",
        }
        assert pp.tenu() is None, "l'envoi fait, la main s'ouvre pour de bon"

    def test_la_main_ne_garde_pas_de_fantome_apres_un_depot(self, client):
        """`held` venait de la session, le presse-papiers de son module :
        les deux pouvaient se contredire, et le voyant annonçait « dans ta
        main : Zéro à Héro » sur une main vide."""
        jeton = self._poser_la_question(client)["token"]
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS", "userSafeMessage": "Affiché."},
        ):
            client.post(
                "/v1/gestures/drop/target",
                json={"token": jeton, "deviceId": "dev_iPad"},
            )
        etat = client.get("/v1/gestures/state").json()
        assert etat["held"] is None
        assert etat["pendingDrop"] is None

    def test_un_appareil_hors_liste_est_refuse(self, client):
        """Le client choisit PARMI ce qu'on lui a proposé. Sinon cette route
        serait un « envoie n'importe quoi à n'importe qui » déguisé."""
        jeton = self._poser_la_question(client)["token"]
        with patch("diapason.mesh.dispatch.dispatch_command") as envoi:
            reponse = client.post(
                "/v1/gestures/drop/target",
                json={"token": jeton, "deviceId": "dev_le-mac-du-voisin"},
            )
        assert reponse.status_code == 409
        assert "candidats" in reponse.json()["detail"]
        envoi.assert_not_called(), "rien ne part vers un appareil non proposé"

    def test_un_jeton_qui_ne_correspond_pas_est_refuse(self, client):
        self._poser_la_question(client)
        with patch("diapason.mesh.dispatch.dispatch_command") as envoi:
            reponse = client.post(
                "/v1/gestures/drop/target",
                json={"token": "un-jeton-inventé", "deviceId": "dev_iPad"},
            )
        assert reponse.status_code == 409
        envoi.assert_not_called()

    def test_une_question_perimee_ne_se_repond_plus(self, client):
        """Le jeton est plus court que le TTL de l'objet : il ne doit jamais
        survivre à ce qu'il désigne."""
        from diapason.server import gestes_routes as gr

        jeton = self._poser_la_question(client)["token"]
        gr._session.depot_en_attente["a"] -= gr._CHOIX_MAX_S + 1.0
        with patch("diapason.mesh.dispatch.dispatch_command") as envoi:
            reponse = client.post(
                "/v1/gestures/drop/target",
                json={"token": jeton, "deviceId": "dev_iPad"},
            )
        assert reponse.status_code == 409
        assert "expiré" in reponse.json()["detail"]
        envoi.assert_not_called()

    def test_deux_clics_n_envoient_qu_une_fois(self, client):
        jeton = self._poser_la_question(client)["token"]
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS", "userSafeMessage": "Affiché."},
        ) as envoi:
            premier = client.post(
                "/v1/gestures/drop/target",
                json={"token": jeton, "deviceId": "dev_iPad"},
            )
            second = client.post(
                "/v1/gestures/drop/target",
                json={"token": jeton, "deviceId": "dev_iPad"},
            )
        assert premier.status_code == 200
        assert second.status_code == 409
        assert envoi.call_count == 1
        # Et si le second passait tout de même, la clé le rendrait inoffensif.
        assert envoi.call_args.kwargs["idempotency_key"] == jeton

    def test_renoncer_vide_la_main_et_le_dit(self, client):
        """Sans cette sortie, la seule issue serait d'attendre l'expiration
        pour apprendre qu'il ne se passera rien."""
        from diapason.desktop import presse_papiers_spatial as pp

        self._poser_la_question(client)
        corps = client.post("/v1/gestures/drop/cancel").json()
        assert corps["cancelled"] is True
        assert "Zéro à Héro" in corps["message"]
        assert pp.tenu() is None
        assert client.get("/v1/gestures/state").json()["pendingDrop"] is None

    def test_renoncer_sans_question_ne_pretend_rien(self, client):
        client.post("/v1/gestures/arm")
        assert client.post("/v1/gestures/drop/cancel").json()["cancelled"] is False

    def test_une_nouvelle_saisie_annule_la_question(self, client):
        """Refermer le poing, c'est RECOMMENCER : le jeton tomberait sinon
        sur l'objet suivant."""
        from diapason.desktop.gestes_main import Etat
        from diapason.server import gestes_routes as gr

        self._poser_la_question(client)
        gr._session.moteur.observer = lambda points: Etat.SAISI
        with patch(
            "diapason.desktop.vision_mains.mains_dans_les_octets", return_value=[]
        ):
            client.post("/v1/gestures/frame", content=_image_factice())
        assert gr._session.depot_en_attente is None
        assert client.get("/v1/gestures/state").json()["pendingDrop"] is None

    def test_un_appareil_sans_la_capacite_n_est_pas_propose(self, client):
        """Un appareil joignable qui ne sait pas afficher une ressource
        n'est pas un candidat : le proposer ferait poser une question dont
        une réponse est un refus garanti."""
        from diapason.desktop import presse_papiers_spatial as pp
        from diapason.server import gestes_routes as gr

        client.post("/v1/gestures/arm")
        self._contexte()
        pp.attraper()
        with patch(
            "diapason.mesh.registry.DeviceRegistry.list_devices",
            return_value=[
                self._appareil("iPad"),
                self._appareil("Ampoule", capacites=("notifications.show",)),
            ],
        ), patch(
            "diapason.mesh.presence.presence_of", return_value={"state": "ONLINE"}
        ), patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS", "userSafeMessage": "Affiché."},
        ) as envoi:
            resultat = gr._deposer()
        assert resultat["reason"] != "AMBIGUOUS", (
            "un seul appareil CAPABLE : il n'y a rien à demander"
        )
        assert envoi.call_args.kwargs["target_device_id"] == "dev_iPad"

    def test_aucun_appareil_capable_le_dit_sans_mentir(self, client):
        """« Aucun appareil n'est joignable » serait faux : ils le sont, ils
        ne savent simplement pas faire cela."""
        resultat = self._poser_la_question(
            client,
            self._appareil("Ampoule", capacites=("notifications.show",)),
        )
        assert resultat["reason"] == "INCAPABLE"
        assert "Ampoule" in resultat["message"]
        assert "ne sait l'afficher" in resultat["message"]

    def test_le_choix_est_journalise(self, client):
        jeton = self._poser_la_question(client)["token"]
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS", "userSafeMessage": "Affiché."},
        ):
            client.post(
                "/v1/gestures/drop/target",
                json={"token": jeton, "deviceId": "dev_PC"},
            )
        entree = client.get("/v1/gestures/state").json()["journal"][0]
        assert entree["what"] == "déposé"
        assert entree["ok"] is True

    def test_desarmer_vide_la_main(self, client):
        """Un objet ne survit pas 120 s à la session qui l'a saisi : la
        caméra est éteinte, le voyant a disparu, plus rien ne l'affiche."""
        from diapason.desktop import presse_papiers_spatial as pp

        self._poser_la_question(client)
        client.post("/v1/gestures/disarm")
        assert pp.tenu() is None


class TestLeJournalDesGestes:
    """« Je pense que cela a fonctionné » est déjà un échec.

    Un geste réussi dont le message disparaît laisse l'utilisateur dans le
    doute. Le journal garde ce qui s'est passé, avec l'heure, pour que ça
    se SACHE au lieu de se supposer.
    """

    def _main_fermee(self):
        from diapason.desktop.gestes_main import Point

        pts = [
            Point("wrist", 0.5, 0.9),
            Point("indexMCP", 0.42, 0.7),
            Point("littleMCP", 0.62, 0.7),
            Point("thumbCMC", 0.38, 0.82),
            Point("thumbTip", 0.42, 0.55),
        ]
        for i, doigt in enumerate(("index", "middle", "ring", "little")):
            base = 0.42 + i * 0.066
            pts.append(Point(f"{doigt}MCP", base, 0.7))
            pts.append(Point(f"{doigt}Tip", base, 0.53))
        return pts

    def test_le_journal_est_vide_au_depart(self, client):
        client.post("/v1/gestures/arm")
        assert client.get("/v1/gestures/state").json()["journal"] == []

    def test_une_saisie_laisse_une_trace_horodatee(self, client):
        from diapason.desktop import contexte_app as ca
        from diapason.server import gestes_routes as gr

        ca.poser_contexte(
            "/succes/projects", ressource_type="project",
            ressource_id="p1", ressource_titre="Zéro à Héro",
        )
        client.post("/v1/gestures/arm")
        gr._noter("attrapé", "Zéro à Héro", reussi=True)
        journal = client.get("/v1/gestures/state").json()["journal"]
        assert len(journal) == 1
        assert journal[0]["what"] == "attrapé"
        assert journal[0]["detail"] == "Zéro à Héro"
        assert journal[0]["ok"] is True
        assert ":" in journal[0]["at"], "l'heure doit être lisible"
        ca.oublier()

    def test_le_plus_recent_est_en_tete(self, client):
        from diapason.server import gestes_routes as gr

        client.post("/v1/gestures/arm")
        gr._noter("attrapé", "premier", reussi=True)
        gr._noter("déposé", "second", reussi=True)
        journal = client.get("/v1/gestures/state").json()["journal"]
        assert journal[0]["detail"] == "second"

    def test_le_journal_ne_grossit_pas_sans_fin(self, client):
        from diapason.server import gestes_routes as gr

        client.post("/v1/gestures/arm")
        for i in range(30):
            gr._noter("attrapé", f"objet {i}", reussi=True)
        assert len(client.get("/v1/gestures/state").json()["journal"]) <= 8

    def test_un_refus_est_journalise_comme_tel(self, client):
        from diapason.server import gestes_routes as gr

        client.post("/v1/gestures/arm")
        gr._noter("dépôt refusé", "aucun appareil n'est joignable", reussi=False)
        entree = client.get("/v1/gestures/state").json()["journal"][0]
        assert entree["ok"] is False
        assert "joignable" in entree["detail"]


class TestLeDoubleClap:
    """§78 — une quatrième voie d'armement, au coût explicite.

    Le bouton n'ouvre rien tant qu'on ne clique pas ; entendre un clap
    suppose un micro OUVERT en continu. Ce coût ne se subit pas, il se
    choisit : l'écoute est éteinte par défaut.
    """

    def test_le_micro_est_ferme_par_defaut(self, client):
        """Rien ne guette sans qu'on l'ait demandé."""
        assert client.get("/v1/gestures/state").json()["clapListening"] is False

    def test_l_ecoute_s_allume_et_s_eteint(self, client):
        faux = MagicMock()
        with patch("diapason.speech.clap_listener.ClapListener", return_value=faux):
            assert client.post("/v1/gestures/clap/on").json()["listening"] is True
            faux.start.assert_called_once()
            assert client.get("/v1/gestures/state").json()["clapListening"] is True
        assert client.post("/v1/gestures/clap/off").json()["listening"] is False
        faux.stop.assert_called_once()

    def test_deux_claps_arment_puis_desarment(self, client):
        """Le même geste dans les deux sens : un mode qu'on ne sait pas
        couper sans souris n'est pas vraiment mains libres."""
        from diapason.server import gestes_routes as gr

        capture = {}

        def _capturer(rappel, **_kw):
            capture["rappel"] = rappel
            return MagicMock()

        with patch(
            "diapason.speech.clap_listener.ClapListener", side_effect=_capturer
        ):
            client.post("/v1/gestures/clap/on")
        rappel = capture["rappel"]

        assert gr.session_active() is False
        rappel()
        assert gr.session_active() is True, "le premier double-clap arme"
        rappel()
        assert gr.session_active() is False, "le second désarme"
        client.post("/v1/gestures/clap/off")

    def test_un_micro_indisponible_le_dit_franchement(self, client):
        """Prétendre écouter sans micro laisserait attendre un clap qui ne
        serait jamais entendu."""
        with patch(
            "diapason.speech.clap_listener.ClapListener",
            side_effect=RuntimeError("aucun périphérique d'entrée"),
        ):
            reponse = client.post("/v1/gestures/clap/on")
        assert reponse.status_code == 503
        assert "micro" in reponse.json()["detail"]

    def test_un_clap_rate_n_arrete_pas_l_ecoute(self, client):
        """Une erreur pendant l'armement ne doit pas rendre le micro sourd
        pour la suite de la session."""
        from diapason.server import gestes_routes as gr

        capture = {}

        def _capturer(rappel, **_kw):
            capture["rappel"] = rappel
            return MagicMock()

        with patch(
            "diapason.speech.clap_listener.ClapListener", side_effect=_capturer
        ):
            client.post("/v1/gestures/clap/on")
        with patch.object(gr, "armer", side_effect=RuntimeError("panne")):
            capture["rappel"]()  # ne lève pas
        assert gr.claps_actifs() is True
        client.post("/v1/gestures/clap/off")


class TestLEcouteSeConstate:
    """Le mensonge le plus coûteux de la session : « écoute active ».

    Le fil d'écoute meurt en silence quand sounddevice manque ou que le
    micro refuse. start() rendait la main sans rien dire, et la route
    répondait « listening: true » à quelqu'un qui pouvait claper jusqu'au
    soir sans que rien n'arrive. Proclamer sans constater est la faute que
    ce projet corrige partout ailleurs.
    """

    def test_un_fil_mort_ne_passe_pas_pour_une_ecoute(self, client):
        mort = MagicMock()
        mort.ecoute = False
        mort.panne = "sounddevice manque"
        with patch("diapason.speech.clap_listener.ClapListener", return_value=mort):
            reponse = client.post("/v1/gestures/clap/on")
        assert reponse.status_code == 503
        assert "sounddevice" in reponse.json()["detail"]
        mort.stop.assert_called_once(), "un fil mort doit être rangé"
        assert client.get("/v1/gestures/state").json()["clapListening"] is False

    def test_un_ecouteur_qui_meurt_apres_coup_cesse_de_compter(self, client):
        """Un objet gardé n'est pas une preuve : l'état doit refléter le
        micro, pas la variable."""
        vivant = MagicMock()
        vivant.ecoute = True
        vivant.claps_entendus = 3
        with patch("diapason.speech.clap_listener.ClapListener", return_value=vivant):
            client.post("/v1/gestures/clap/on")
        assert client.get("/v1/gestures/state").json()["clapListening"] is True
        vivant.ecoute = False  # le fil meurt en cours de route
        assert client.get("/v1/gestures/state").json()["clapListening"] is False
        client.post("/v1/gestures/clap/off")

    def test_les_claps_entendus_sont_rapportes(self, client):
        """Sans ce compte, on ne sait pas distinguer « le micro n'entend
        rien » de « mes deux claps sont trop espacés »."""
        ecouteur = MagicMock()
        ecouteur.ecoute = True
        ecouteur.claps_entendus = 7
        with patch("diapason.speech.clap_listener.ClapListener", return_value=ecouteur):
            client.post("/v1/gestures/clap/on")
        assert client.get("/v1/gestures/state").json()["clapsHeard"] == 7
        client.post("/v1/gestures/clap/off")


def _piece(niveau=0.006, maximum=0.008, bruyants=0):
    from diapason.speech.clap_listener import Piece

    return Piece(
        niveau=niveau, dispersion=0.3, maximum=maximum, blocs_bruyants=bruyants
    )


class TestLeSeuilSeMesureEnDeuxTemps:
    """En un seul appel, l'interface devait DEVINER quand le serveur passait
    de « j'écoute la pièce » à « clape maintenant ».

    Elle armait son minuteur avant d'envoyer la requête, alors que le compte
    du serveur ne démarre qu'une fois le micro ouvert : « Maintenant ! Clape »
    s'affichait pendant que le serveur écoutait encore le silence, et celui
    qui obéissait à l'écran polluait sa propre mesure. Trois échecs sur
    quatre le 25 août 2026. En deux temps, personne n'a plus à deviner.
    """

    @pytest.fixture(autouse=True)
    def _isoler(self, tmp_path, monkeypatch):
        from diapason.speech import clap_listener as cl

        monkeypatch.setattr(cl, "chemin_reglage_claps", lambda: tmp_path / "claps.json")
        monkeypatch.setattr(gr, "_piece_mesuree", None)
        monkeypatch.setattr(gr, "_ecouteur_claps", None)
        self.fichier = tmp_path / "claps.json"

    def test_les_deux_temps_posent_le_seuil_entre_la_piece_et_les_claps(self, client):
        from diapason.speech import clap_listener as cl

        with patch.object(cl, "ecouter_la_piece", return_value=_piece()):
            r = client.post("/v1/gestures/clap/calibrate/room")
        assert r.status_code == 200, r.text
        assert r.json()["disturbed"] is False

        ecoute = cl.Ecoute(piece=_piece(), claps=[0.44, 0.45, 0.51], ecartes=[0.03])
        with patch.object(cl, "ecouter_les_claps", return_value=ecoute):
            r = client.post("/v1/gestures/clap/calibrate/claps")
        assert r.status_code == 200, r.text
        vu = r.json()
        assert vu["calibrated"] is True
        assert vu["discarded"] == [0.03], "le bruit écarté doit se voir"
        assert _piece().haute < vu["threshold"] < 0.44
        assert self.fichier.exists()

    def test_claper_sans_avoir_mesure_la_piece_est_refuse(self, client):
        r = client.post("/v1/gestures/clap/calibrate/claps")
        assert r.status_code == 409
        assert "pas été mesurée juste avant" in r.json()["detail"]

    def test_une_piece_mesuree_il_y_a_trop_longtemps_ne_sert_plus(
        self, client, monkeypatch
    ):
        """Le fond sonore d'une pièce vieille d'une minute n'est plus le sien."""
        monkeypatch.setattr(
            gr,
            "_piece_mesuree",
            {"piece": _piece(), "ecoutait": False, "intention": 0, "a": 0.0},
        )
        r = client.post("/v1/gestures/clap/calibrate/claps")
        assert r.status_code == 409

    def test_deux_mesures_ne_se_partagent_pas_le_micro(self, client):
        """Il a cliqué quatre fois de suite ; sans verrou, deux mesures
        s'arrachent le micro et la dernière écrase la première."""
        assert gr._verrou_calibration.acquire(blocking=False)
        try:
            assert client.post("/v1/gestures/clap/calibrate/room").status_code == 409
            assert client.post("/v1/gestures/clap/calibrate/claps").status_code == 409
        finally:
            gr._verrou_calibration.release()

    def test_le_refus_dit_quoi_corriger_et_n_ecrit_rien(self, client):
        from diapason.speech import clap_listener as cl

        with patch.object(cl, "ecouter_la_piece", return_value=_piece()):
            client.post("/v1/gestures/clap/calibrate/room")
        vide = cl.Ecoute(piece=_piece(), claps=[], ecartes=[])
        with patch.object(cl, "ecouter_les_claps", return_value=vide):
            r = client.post("/v1/gestures/clap/calibrate/claps")
        assert r.status_code == 422
        assert "Aucun clap" in r.json()["detail"]
        assert not self.fichier.exists()


class TestLaMesureRendLeMicroCommeElleLAPris:
    """Le micro doit revenir dans l'état où l'utilisateur l'a laissé —
    et SEULEMENT si c'est encore ce qu'il veut."""

    @pytest.fixture(autouse=True)
    def _isoler(self, tmp_path, monkeypatch):
        from diapason.speech import clap_listener as cl

        monkeypatch.setattr(cl, "chemin_reglage_claps", lambda: tmp_path / "claps.json")
        monkeypatch.setattr(gr, "_piece_mesuree", None)

    def _ecouteur_vivant(self):
        vivant = MagicMock()
        vivant.ecoute = True
        vivant.claps_entendus = 0
        vivant.seuil = 0.05
        vivant.fond_sonore = 0.006
        return vivant

    def test_decocher_pendant_la_mesure_ne_rouvre_pas_le_micro(
        self, client, monkeypatch
    ):
        """Constaté le 25 août 2026 : la calibration rouvrait le micro huit
        secondes après que l'utilisateur l'avait coupé. L'état du serveur
        disait « écoute active » et l'interface affichait le micro éteint,
        jusqu'au prochain redémarrage."""
        from diapason.speech import clap_listener as cl

        monkeypatch.setattr(gr, "_ecouteur_claps", self._ecouteur_vivant())
        with patch.object(cl, "ecouter_la_piece", return_value=_piece()):
            assert client.post("/v1/gestures/clap/calibrate/room").status_code == 200

        # L'utilisateur décoche la case pendant que la mesure court.
        client.post("/v1/gestures/clap/off")

        ecoute = cl.Ecoute(piece=_piece(), claps=[0.44, 0.45], ecartes=[])
        with (
            patch.object(cl, "ecouter_les_claps", return_value=ecoute),
            patch.object(cl, "ClapListener") as fabrique,
        ):
            assert client.post("/v1/gestures/clap/calibrate/claps").status_code == 200
        fabrique.assert_not_called(), "le micro a été rouvert contre sa volonté"
        assert client.get("/v1/gestures/state").json()["clapListening"] is False

    def test_un_echec_ne_prive_pas_d_ecoute_celui_qui_en_avait(
        self, client, monkeypatch
    ):
        """L'écriture du réglage était hors du try : un échec disque perdait
        l'écoute en silence."""
        from diapason.speech import clap_listener as cl

        monkeypatch.setattr(gr, "_ecouteur_claps", self._ecouteur_vivant())
        with patch.object(cl, "ecouter_la_piece", return_value=_piece()):
            client.post("/v1/gestures/clap/calibrate/room")

        vide = cl.Ecoute(piece=_piece(), claps=[], ecartes=[])
        with (
            patch.object(cl, "ecouter_les_claps", return_value=vide),
            patch.object(cl, "ClapListener") as fabrique,
        ):
            fabrique.return_value = self._ecouteur_vivant()
            r = client.post("/v1/gestures/clap/calibrate/claps")
        assert r.status_code == 422, "le 422 doit survivre à la reprise d'écoute"
        assert "Aucun clap" in r.json()["detail"]
        fabrique.assert_called_once(), "l'écoute n'a pas été reprise"


class TestUnFilMortNeBloquePasLaRelance:
    """Tester la présence d'un objet plutôt que son état faisait répondre
    « déjà en écoute » à toute tentative de relance : le micro restait fermé
    à vie après la mort silencieuse du fil."""

    def test_un_cadavre_est_range_puis_l_ecoute_repart(self, client, monkeypatch):
        from diapason.speech import clap_listener as cl

        mort = MagicMock()
        mort.ecoute = False
        monkeypatch.setattr(gr, "_ecouteur_claps", mort)
        assert gr.claps_actifs() is False
        assert gr._ecouteur_claps is None, "le cadavre n'a pas été rangé"

        monkeypatch.setattr(gr, "_ecouteur_claps", mort)
        neuf = MagicMock()
        neuf.ecoute = True
        neuf.panne = None
        with patch.object(cl, "ClapListener", return_value=neuf):
            r = client.post("/v1/gestures/clap/on")
        assert r.status_code == 200
        assert r.json() == {"listening": True}, "une relance a été refusée"

    def test_l_etat_montre_le_fond_sonore_et_la_raison_d_un_echec(
        self, client, monkeypatch
    ):
        """Le seuil seul ne suffit pas : c'est son rapport au fond appris qui
        dit si la marge est confortable."""
        vivant = MagicMock()
        vivant.ecoute = True
        vivant.claps_entendus = 5
        vivant.seuil = 0.09
        vivant.fond_sonore = 0.0061
        monkeypatch.setattr(gr, "_ecouteur_claps", vivant)
        monkeypatch.setattr(gr, "_echec_de_clap", "La caméra a refusé de s'ouvrir.")

        vu = client.get("/v1/gestures/state").json()
        assert vu["clapThreshold"] == 0.09
        assert vu["clapNoiseFloor"] == 0.0061
        assert vu["clapsHeard"] == 5
        assert vu["clapFailure"] == "La caméra a refusé de s'ouvrir."
