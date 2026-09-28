"""Un refus doit pouvoir être lu par celui qu'il refuse — la fenêtre aussi.

28/09/2026 : la fenêtre Tauri (``tauri://localhost``) appelle
``http://127.0.0.1:8000`` en cross-origin. CORSMiddleware était ajouté SOUS
AuthMiddleware : un 401 sortait sans en-tête CORS, WebKit ne pouvait pas le
lire et fetch() rejetait « Load failed ». Le chat le présentait comme un
serveur injoignable (frontend/src/lib/coupureDuFlux.ts) et proposait
« Renvoyer », qui rejouait le même refus. Une 500 levée avant la réponse,
émise par ServerErrorMiddleware hors de CORS, faisait de même.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from fastapi.testclient import TestClient

FENETRE = "tauri://localhost"
CLE = "oj_sk_cle_du_test_refus_lisibles"


def _app():
    from diapason.core.config import DiapasonConfig
    from diapason.server.app import create_app

    moteur = MagicMock()
    moteur.list_models.return_value = ["test-model"]
    config = DiapasonConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    app = create_app(moteur, "test-model", api_key=CLE, config=config)

    @app.get("/v1/panne-avant-la-reponse")
    async def _panne():
        raise RuntimeError("le chat n'a pas pu choisir son modèle")

    # Devant l'attrape-tout du bundle, qui servirait index.html sinon.
    app.router.routes.insert(0, app.router.routes.pop())
    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_app(), raise_server_exceptions=False)


class TestUnRefusResteLisibleParLaFenetre:
    """§5 : une réponse que la fenêtre ne peut pas lire devient « Load
    failed », que le chat lit comme un serveur arrêté — une cause fausse."""

    @pytest.mark.parametrize(
        "entetes",
        [{}, {"Authorization": "Bearer cle-perimee"}],
        ids=["sans_cle", "cle_perimee"],
    )
    def test_un_401_porte_les_en_tetes_cors_de_la_fenetre(self, client, entetes):
        reponse = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": []},
            headers={"Origin": FENETRE, **entetes},
        )
        assert reponse.status_code == 401, reponse.text
        assert reponse.headers.get("access-control-allow-origin") == FENETRE, (
            "sans cet en-tête, WebKit rejette « Load failed » au lieu de lire 401"
        )
        assert reponse.headers.get("access-control-allow-credentials") == "true"

    def test_une_origine_etrangere_ne_lit_toujours_pas_le_refus(self, client):
        reponse = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": []},
            headers={"Origin": "http://evil.example"},
        )
        assert reponse.status_code == 401
        assert "access-control-allow-origin" not in reponse.headers, (
            "la liste des origines de CORS reste la seule autorité"
        )

    def test_une_500_avant_la_reponse_porte_les_en_tetes_cors(self, client):
        reponse = client.get(
            "/v1/panne-avant-la-reponse",
            headers={"Origin": FENETRE, "Authorization": f"Bearer {CLE}"},
        )
        assert reponse.status_code == 500
        assert reponse.text == "Internal Server Error", (
            "le corps ne change pas : aucun détail de l'exception ne sort"
        )
        assert reponse.headers.get("access-control-allow-origin") == FENETRE, (
            "une 500 illisible se lit « serveur injoignable » dans la fenêtre"
        )

    def test_une_500_ne_s_ouvre_pas_a_une_origine_etrangere(self, client):
        reponse = client.get(
            "/v1/panne-avant-la-reponse",
            headers={"Origin": "http://evil.example", "Authorization": f"Bearer {CLE}"},
        )
        assert reponse.status_code == 500
        assert "access-control-allow-origin" not in reponse.headers

    def test_l_exception_remonte_toujours_au_serveur(self):
        """Le journal d'uvicorn doit garder la trace : le gestionnaire rend
        une réponse lisible, il n'avale pas l'exception."""
        with pytest.raises(RuntimeError, match="choisir son modèle"):
            TestClient(_app()).get(
                "/v1/panne-avant-la-reponse",
                headers={"Origin": FENETRE, "Authorization": f"Bearer {CLE}"},
            )

    def test_le_preflight_reste_repondu_sans_cle(self, client):
        reponse = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": FENETRE,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert reponse.status_code == 200
        assert reponse.headers.get("access-control-allow-origin") == FENETRE
