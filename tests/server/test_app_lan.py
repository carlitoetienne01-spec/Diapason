"""Ce que le réseau local a le droit de voir — et comment on le prouve.

Spatial Mesh, transfert — 25 août 2026. Constaté ce jour sur la machine de
Carlito : le LaunchAgent installé porte `--host 0.0.0.0` alors que le plist
du dépôt dit `127.0.0.1`. L'application COMPLÈTE — deux cent dix routes —
écoutait donc sur le Wi-Fi. L'API restait protégée par la clé (401) et les
routes de maillage par leur signature (403), mais toutes étaient JOIGNABLES :
une seule route qui oublierait sa protection aurait été exposée le jour même.

La réponse n'est pas un middleware de filtrage. Ce serait une quatrième liste
de chemins à côté de trois qui ont déjà dérivé, et son mode de défaillance
serait silencieux — un `startswith` trop large, et le rattrape-tout SPA rend
cent quatre-vingt-cinq routes plus l'arborescence statique.

La réponse est une SECONDE APPLICATION. Le port ne sait pas ce qu'est le chat.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import Request  # noqa: E402

from diapason.server.app import _PORTES_LAN, create_lan_app  # noqa: E402
from diapason.server.auth_middleware import AuthMiddleware  # noqa: E402


def _chemins(app) -> set[str]:
    """TOUTES les routes montées, quel que soit leur type.

    Ce filtre écartait les routes sans méthodes HTTP — donc les WebSockets et
    les points de montage. Il était aveugle exactement là où le plafond
    l'était : les deux ont été corrigés le 26 août 2026, et il fallait les
    corriger ensemble, sinon le test serait resté vert au-dessus du trou.
    """
    return {r.path for r in app.routes if hasattr(r, "path")}


class TestCeQuiEstExpose:
    def test_exactement_les_neuf_portes(self):
        assert _chemins(create_lan_app()) == set(_PORTES_LAN)

    def test_le_chat_n_existe_pas_sur_ce_port(self):
        """Pas 401, pas 403 : la route n'existe pas dans cette application."""
        exposees = _chemins(create_lan_app())
        for interdit in (
            "/v1/chat/completions",
            "/v1/models",
            "/v1/voice/live",
            "/v1/gestures/frame",
            "/v1/succes/tasks",
            # Le nom neuf du domaine (25/09/2026) : fermé comme l'ancien.
            "/v1/vie/tasks",
        ):
            assert interdit not in exposees

    def test_le_plan_de_controle_reste_a_la_maison(self):
        """Émettre une invitation, envoyer une commande, révoquer un
        appareil : ce sont les gestes de CE poste, pas ceux d'un pair."""
        exposees = _chemins(create_lan_app())
        for interdit in (
            "/v1/mesh/pairings",
            "/v1/mesh/commands",
            "/v1/mesh/devices",
        ):
            assert interdit not in exposees

    def test_un_websocket_ajoute_ailleurs_ne_franchit_pas_le_plafond(self):
        """Le plafond doit tenir contre ce que personne n'a encore écrit.

        Le filtre gardait toute route dépourvue de méthodes HTTP. Aucune des
        neuf portes n'est dans ce cas, donc la clause ne gardait rien — mais
        un `@router.websocket(...)` ajouté à `mesh/routes.py` par une session
        future se serait retrouvé sur 0.0.0.0 sans que rien ne rougisse :
        hors du mur (cette application n'a pas d'AuthMiddleware) et hors du
        seau de débit (une poignée de main WebSocket ne traverse pas un
        BaseHTTPMiddleware).
        """
        from diapason.mesh.routes import router as mesh_router

        avant = list(mesh_router.routes)
        try:

            @mesh_router.websocket("/tunnel")
            async def _tunnel(websocket):  # pragma: no cover - jamais appelé
                await websocket.accept()

            expose = _chemins(create_lan_app())
        finally:
            mesh_router.routes[:] = avant

        assert "/v1/mesh/tunnel" not in expose, (
            "un WebSocket ajouté au routeur de maillage est arrivé sur le "
            "réseau local sans passer par _PORTES_LAN"
        )
        assert expose == set(_PORTES_LAN), (
            "le plafond doit rester une liste de chemins, sans exception de type"
        )

    def test_ni_documentation_ni_schema(self):
        """Une énumération de routes est un cadeau fait au réseau."""
        lan = create_lan_app()
        assert lan.docs_url is None
        assert lan.openapi_url is None


class TestLInvariantQuiEmpecheLaDerive:
    """La seule règle qui tienne quand quelqu'un ajoutera une route.

    Une porte du LAN doit être hors du mur d'authentification — parce qu'elle
    porte une créance PLUS FORTE que la clé (signature d'appareil, invitation
    à usage unique, jeton de session). Et réciproquement : toute route hors du
    mur est une porte que le LAN doit pouvoir franchir, sinon le maillage est
    à moitié joignable et personne ne sait laquelle.
    """

    def test_aucune_porte_du_lan_n_exige_la_cle_d_api(self):
        for chemin in sorted(_PORTES_LAN):
            concret = chemin.replace("{session_id}", "s1")
            assert not AuthMiddleware._requires_auth(concret), (
                f"{chemin} est exposée au LAN mais attend la clé d'API : "
                "l'une des deux décisions est fausse"
            )

    def test_toute_route_mesh_hors_du_mur_est_une_porte_du_lan(self):
        """L'autre sens, et c'est celui qui rouille.

        Ajouter une route de maillage exemptée sans l'exposer au LAN donne un
        maillage qui marche en loopback et se tait sur le réseau — le genre de
        panne qu'on cherche du mauvais côté pendant une heure.
        """
        from diapason.mesh.files_routes import router as files_router
        from diapason.mesh.routes import router as mesh_router

        for routeur in (mesh_router, files_router):
            for route in routeur.routes:
                chemin = getattr(route, "path", "")
                if not getattr(route, "methods", None):
                    continue
                concret = chemin.replace("{session_id}", "s1")
                if AuthMiddleware._requires_auth(concret):
                    continue
                assert chemin in _PORTES_LAN, (
                    f"{chemin} est hors du mur mais absente du LAN : "
                    "un pair ne pourra jamais l'atteindre"
                )


class TestSurUnVraiSocket:
    """La comparaison d'ensembles prouve le montage ; ceci prouve le PORT.

    Un test qui n'interroge que `app.routes` prouve ce qu'on a construit, pas
    ce qu'un pair rencontre. Ici on lie un vrai socket et on frappe dessus.
    """

    def _servir(self):
        import socket
        import threading
        import time

        import uvicorn

        prise = socket.socket()
        prise.bind(("127.0.0.1", 0))
        port = prise.getsockname()[1]
        prise.close()

        serveur = uvicorn.Server(
            uvicorn.Config(
                create_lan_app(), host="127.0.0.1", port=port, log_level="error"
            )
        )
        fil = threading.Thread(target=serveur.run, daemon=True)
        fil.start()
        for _ in range(100):
            if serveur.started:
                break
            time.sleep(0.05)
        return serveur, port, fil

    def test_le_chat_rend_404_pas_401(self):
        """La différence dit tout : 401 signifie « il faudrait une clé »,
        donc la route existe. 404 signifie que ce port ne sait pas ce qu'est
        le chat — aucune clé volée n'y donnerait accès."""
        import httpx

        serveur, port, fil = self._servir()
        try:
            base = f"http://127.0.0.1:{port}"
            chat = httpx.post(f"{base}/v1/chat/completions", json={}, timeout=5)
            sante = httpx.get(f"{base}/health", timeout=5)
            docs = httpx.get(f"{base}/docs", timeout=5)
            porte = httpx.post(f"{base}/v1/mesh/presence", json={}, timeout=5)
        finally:
            serveur.should_exit = True
            fil.join(timeout=5)
            assert not fil.is_alive(), "le serveur de banc a survécu au test"

        assert chat.status_code == 404, "le chat ne doit pas exister sur ce port"
        assert sante.status_code == 404, "même /health n'a rien à dire au réseau"
        assert docs.status_code == 404, "aucune énumération de routes"
        assert porte.status_code != 404, (
            "une porte du maillage doit exister — elle refusera faute de "
            "signature, mais elle doit répondre"
        )


class TestLesDeuxSocketsDemarrent:
    """Un seul PROCESSUS, deux sockets — et il faut le prouver.

    La boîte de réception des commandes et les sessions de transfert vivent
    dans des globales en mémoire : deux processus, et une commande reçue sur
    le réseau n'apparaîtrait jamais dans l'inbox lue en loopback.
    """

    def test_les_deux_ports_repondent_depuis_un_seul_processus(self):
        import os
        import socket
        import threading
        import time

        import httpx
        from fastapi import FastAPI

        from diapason.cli.serve import _Prise, _servir_les_sockets

        def _port_libre() -> int:
            p = socket.socket()
            p.bind(("127.0.0.1", 0))
            n = p.getsockname()[1]
            p.close()
            return n

        maison, reseau = _port_libre(), _port_libre()
        pid_vu: dict[str, int] = {}

        principal = FastAPI()

        @principal.get("/prive")
        def _prive():
            pid_vu["principal"] = os.getpid()
            return {"ok": True}

        lan = FastAPI()

        @lan.get("/porte")
        def _porte():
            pid_vu["lan"] = os.getpid()
            return {"ok": True}

        arret = threading.Event()
        fil = threading.Thread(
            target=_servir_les_sockets,
            args=(
                [
                    _Prise("principal", principal, "127.0.0.1", maison),
                    _Prise("maillage", lan, "127.0.0.1", reseau),
                ],
                arret,
            ),
            daemon=True,
        )
        fil.start()
        for _ in range(100):
            try:
                httpx.get(f"http://127.0.0.1:{reseau}/porte", timeout=1)
                break
            except Exception:  # noqa: BLE001 - le serveur monte encore
                time.sleep(0.05)

        try:
            assert (
                httpx.get(f"http://127.0.0.1:{maison}/prive", timeout=5).status_code
                == 200
            )
            assert (
                httpx.get(f"http://127.0.0.1:{reseau}/porte", timeout=5).status_code
                == 200
            )
            # Le point qui compte : la même mémoire des deux côtés.
            assert pid_vu["principal"] == pid_vu["lan"] == os.getpid()
            # Et l'étanchéité : chaque port ignore les routes de l'autre.
            assert (
                httpx.get(f"http://127.0.0.1:{reseau}/prive", timeout=5).status_code
                == 404
            )
            assert (
                httpx.get(f"http://127.0.0.1:{maison}/porte", timeout=5).status_code
                == 404
            )
        finally:
            arret.set()
            fil.join(timeout=5)
            assert not fil.is_alive(), "les deux sockets ont survécu au test"


class TestLesTroisSocketsDemarrent:
    """Le troisième socket, la passerelle du tailnet (26/09/2026, étape 4).

    Même processus que les deux autres — une commande reçue par le tailnet
    doit tomber dans la même boîte que celle lue en loopback —, mais avec
    un cycle de vie éteint et sans croire les en-têtes de relais.
    """

    @staticmethod
    def _port_libre() -> int:
        import socket

        p = socket.socket()
        p.bind(("127.0.0.1", 0))
        n = p.getsockname()[1]
        p.close()
        return n

    def test_la_prise_du_tailnet_est_bornee_a_la_boucle_sans_cycle_ni_relais(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
        from fastapi import FastAPI

        from diapason.cli.serve import _prises
        from diapason.server.passerelle_tailnet import PasserelleTailnet

        app = FastAPI()
        prises = _prises(
            app,
            "127.0.0.1",
            8000,
            lan_host="0.0.0.0",
            lan_port=8001,
            tailnet_port=8002,
            adresse_tailnet="",
        )
        assert [p.nom for p in prises] == ["principal", "maillage", "tailnet"]
        tailnet = prises[-1]
        assert tailnet.host == "127.0.0.1", (
            "sur 0.0.0.0, la passerelle serait joignable en HTTP clair par le Wi-Fi"
        )
        assert tailnet.port == 8002
        assert tailnet.lifespan == "off"
        assert tailnet.proxy_headers is False
        assert isinstance(tailnet.app, PasserelleTailnet)
        assert tailnet.app.app is app, "la passerelle doit envelopper l'app principale"
        # « La révocation coupe les WebSockets en 30 s au plus » : tous les
        # tests de coupure injectent 50 ms ; seul celui-ci lit l'intervalle
        # que la production reçoit (contre-épreuve du 26/09/2026 : 3 600 s
        # passaient inaperçues).
        assert tailnet.app._intervalle_s <= 30, tailnet.app._intervalle_s
        assert tailnet.timeout_graceful_shutdown is not None
        assert tailnet.timeout_graceful_shutdown <= 10, (
            "le socket du tailnet s'arrête le premier : sans borne, un flux "
            "tenu par le téléphone retient l'API locale jusqu'au SIGKILL"
        )
        # Les sockets d'avant ne changent pas de forme.
        assert (prises[0].lifespan, prises[0].proxy_headers) == ("auto", True)
        assert prises[0].timeout_graceful_shutdown is None

    def test_un_port_secondaire_tenu_ne_fait_pas_tomber_l_api_locale(self):
        """26/09/2026 (contre-épreuve) : un socket occupait le port du
        tailnet ; le serveur mourait en code 3 (uvicorn, Errno 48) sans que
        l'API locale ait jamais servi — et launchd l'aurait relancé toutes
        les dix secondes. Le téléphone injoignable ne doit pas priver le Mac
        de son serveur."""
        import socket
        import threading
        import time

        import httpx
        from fastapi import FastAPI

        from diapason.cli.serve import _Prise, _servir_les_sockets

        maison = self._port_libre()
        occupant = socket.socket()
        occupant.bind(("127.0.0.1", 0))
        occupant.listen(1)
        tenu = occupant.getsockname()[1]

        principal = FastAPI()

        @principal.get("/vivant")
        def _vivant():
            return {"ok": True}

        arret = threading.Event()
        erreurs: list[BaseException] = []

        def _servir():
            try:
                _servir_les_sockets(
                    [
                        _Prise("principal", principal, "127.0.0.1", maison),
                        _Prise(
                            "tailnet",
                            FastAPI(),
                            "127.0.0.1",
                            tenu,
                            lifespan="off",
                            proxy_headers=False,
                        ),
                    ],
                    arret,
                )
            except BaseException as exc:  # noqa: BLE001 - SystemExit compris
                erreurs.append(exc)

        fil = threading.Thread(target=_servir, daemon=True)
        fil.start()
        reponse = None
        try:
            for _ in range(100):
                try:
                    reponse = httpx.get(f"http://127.0.0.1:{maison}/vivant", timeout=1)
                    break
                except Exception:  # noqa: BLE001 - le serveur monte encore
                    if not fil.is_alive():
                        break
                    time.sleep(0.05)
        finally:
            arret.set()
            fil.join(timeout=10)
            occupant.close()
        assert not fil.is_alive(), "les sockets ont survécu au test"
        assert reponse is not None and reponse.status_code == 200, (
            f"l'API locale n'a jamais servi ; le serveur est tombé : {erreurs}"
        )
        assert erreurs == [], f"le serveur est sorti en erreur : {erreurs}"

    def test_un_port_secondaire_tenu_est_ecarte_avant_de_servir(self):
        """Le constat se dit en français, port et occupant nommés — pas en
        « [Errno 48] address already in use » au milieu du journal."""
        import io

        from fastapi import FastAPI
        from rich.console import Console

        from diapason.cli.serve import _Prise, _prises_liables
        from diapason.core import ports

        sortie = io.StringIO()
        prises = [
            _Prise("principal", FastAPI(), "127.0.0.1", 8000),
            _Prise("maillage", FastAPI(), "0.0.0.0", 8001),
            _Prise("tailnet", FastAPI(), "127.0.0.1", 8002),
        ]
        etats = {
            8000: (ports.OCCUPE, "PID 1 sur 127.0.0.1"),
            8001: (ports.LIBRE, ""),
            8002: (ports.OCCUPE, "PID 4242 sur 127.0.0.1"),
        }
        gardees = _prises_liables(
            prises,
            console=Console(file=sortie, width=200),
            etat_du_port=lambda port: etats[port],
        )
        assert [p.nom for p in gardees] == ["principal", "maillage"], (
            "le principal reste à attendre_le_port ; seul le tailnet tenu part"
        )
        texte = sortie.getvalue()
        assert "8002" in texte and "PID 4242" in texte, texte
        assert "téléphone" in texte, texte

    def test_sans_option_aucune_passerelle(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
        from fastapi import FastAPI

        from diapason.cli.serve import _prises

        prises = _prises(
            FastAPI(),
            "127.0.0.1",
            8000,
            lan_host=None,
            lan_port=8001,
            tailnet_port=None,
        )
        assert [p.nom for p in prises] == ["principal"]

    def test_trois_sockets_un_seul_cycle_de_vie_et_aucun_relais_cru(
        self, tmp_path, monkeypatch
    ):
        """Le banc à événement `arret`, étendu à trois sockets.

        Sans lifespan="off", le démarrage de l'app aurait couru deux fois.
        Sans proxy_headers=False, un X-Forwarded-For posé par n'importe quel
        processus local réécrirait `request.client`.
        """
        import dataclasses
        import os
        import threading
        import time
        from contextlib import asynccontextmanager

        import httpx
        from fastapi import FastAPI

        from diapason.cli.serve import _Prise, _prises, _servir_les_sockets

        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
        demarrages: list[int] = []
        arrets: list[int] = []

        @asynccontextmanager
        async def _cycle(_app):
            demarrages.append(os.getpid())
            yield
            arrets.append(os.getpid())

        principal = FastAPI(lifespan=_cycle)
        vu: dict = {}

        @principal.get("/qui")
        def _qui(request: Request):
            vu.setdefault("clients", []).append(request.client.host)
            return {"pid": os.getpid()}

        lan = FastAPI()

        @lan.get("/porte")
        def _porte():
            return {"pid": os.getpid()}

        maison, reseau, tailnet = (self._port_libre() for _ in range(3))
        # La prise telle que `serve` la construit, avec l'app témoin à la
        # place de la passerelle : c'est la CONFIGURATION du socket qu'on
        # éprouve ici, la passerelle a ses propres tests.
        (prise_tailnet,) = [
            p
            for p in _prises(
                principal,
                "127.0.0.1",
                maison,
                lan_host=None,
                lan_port=reseau,
                tailnet_port=tailnet,
                adresse_tailnet="",
            )
            if p.nom == "tailnet"
        ]
        prise_tailnet = dataclasses.replace(prise_tailnet, app=principal)
        arret = threading.Event()
        fil = threading.Thread(
            target=_servir_les_sockets,
            args=(
                [
                    _Prise("principal", principal, "127.0.0.1", maison),
                    _Prise("maillage", lan, "127.0.0.1", reseau),
                    prise_tailnet,
                ],
                arret,
            ),
            daemon=True,
        )
        fil.start()
        for _ in range(100):
            try:
                httpx.get(f"http://127.0.0.1:{tailnet}/qui", timeout=1)
                break
            except Exception:  # noqa: BLE001 - les serveurs montent encore
                time.sleep(0.05)
        vu.clear()
        try:
            forge = {"X-Forwarded-For": "203.0.113.7"}
            par_tailnet = httpx.get(
                f"http://127.0.0.1:{tailnet}/qui", headers=forge, timeout=5
            )
            par_maison = httpx.get(
                f"http://127.0.0.1:{maison}/qui", headers=forge, timeout=5
            )
            par_reseau = httpx.get(f"http://127.0.0.1:{reseau}/porte", timeout=5)
        finally:
            arret.set()
            fil.join(timeout=10)
        assert not fil.is_alive(), "les trois sockets ont survécu au test"
        assert par_tailnet.status_code == 200, par_tailnet.text
        assert par_maison.status_code == 200, par_maison.text
        assert par_tailnet.json()["pid"] == par_maison.json()["pid"] == os.getpid()
        assert par_reseau.status_code == 200
        assert demarrages == [os.getpid()], (
            f"le cycle de vie a démarré {len(demarrages)} fois pour trois sockets"
        )
        assert arrets == [os.getpid()], "l'arrêt doit courir une fois, et courir"
        client_tailnet, client_maison = vu["clients"]
        assert client_tailnet == "127.0.0.1", (
            "le socket du tailnet a cru un X-Forwarded-For forgé"
        )
        # Le contraste qui montre ce que l'option change : le socket
        # principal, lui, garde le défaut d'uvicorn (piège du §5).
        assert client_maison == "203.0.113.7"
