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
        return serveur, port

    def test_le_chat_rend_404_pas_401(self):
        """La différence dit tout : 401 signifie « il faudrait une clé »,
        donc la route existe. 404 signifie que ce port ne sait pas ce qu'est
        le chat — aucune clé volée n'y donnerait accès."""
        import httpx

        serveur, port = self._servir()
        try:
            base = f"http://127.0.0.1:{port}"
            chat = httpx.post(f"{base}/v1/chat/completions", json={}, timeout=5)
            sante = httpx.get(f"{base}/health", timeout=5)
            docs = httpx.get(f"{base}/docs", timeout=5)
            porte = httpx.post(f"{base}/v1/mesh/presence", json={}, timeout=5)
        finally:
            serveur.should_exit = True

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

        from diapason.cli.serve import _servir_deux_sockets

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

        fil = threading.Thread(
            target=_servir_deux_sockets,
            args=(principal, "127.0.0.1", maison, lan, "127.0.0.1", reseau),
            daemon=True,
        )
        fil.start()
        for _ in range(100):
            try:
                httpx.get(f"http://127.0.0.1:{reseau}/porte", timeout=1)
                break
            except Exception:  # noqa: BLE001 - le serveur monte encore
                time.sleep(0.05)

        assert (
            httpx.get(f"http://127.0.0.1:{maison}/prive", timeout=5).status_code == 200
        )
        assert (
            httpx.get(f"http://127.0.0.1:{reseau}/porte", timeout=5).status_code == 200
        )
        # Le point qui compte : la même mémoire des deux côtés.
        assert pid_vu["principal"] == pid_vu["lan"] == os.getpid()
        # Et l'étanchéité : chaque port ignore les routes de l'autre.
        assert (
            httpx.get(f"http://127.0.0.1:{reseau}/prive", timeout=5).status_code == 404
        )
        assert (
            httpx.get(f"http://127.0.0.1:{maison}/porte", timeout=5).status_code == 404
        )
