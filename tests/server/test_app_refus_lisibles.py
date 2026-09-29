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


ETRANGERE = "https://evil.example"


def _app_au_seau_etroit():
    """Un seau à clé d'une requête par minute : la seconde rend 429, et
    le jeton suivant ne revient qu'après soixante secondes."""
    from diapason.core.config import DiapasonConfig
    from diapason.server.app import create_app

    moteur = MagicMock()
    moteur.list_models.return_value = ["test-model"]
    config = DiapasonConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    config.security.rate_limit_rpm = 1
    config.security.rate_limit_burst = 1
    return create_app(moteur, "test-model", api_key=CLE, config=config)


def _jusqu_au_429(client, methode: str, chemin: str, **options):
    """Frappe jusqu'au refus. Le seau des portes sans clé (rafale de vingt,
    deux jetons par seconde) se vide en vingt et une requêtes de quelques
    millisecondes ; cent laissent de quoi traverser une machine chargée."""
    for _ in range(100):
        reponse = client.request(methode, chemin, **options)
        if reponse.status_code == 429:
            return reponse
    raise AssertionError(f"{chemin} n'a jamais rendu 429 : {reponse.status_code}")


# Les deux familles de seaux : celui des routes à clé, et celui des portes du
# maillage qu'un inconnu atteint sans clé (/v1/mesh/pairings/redeem rend 422
# sur un corps vide, AVANT tout registre : aucun disque touché).
_SEAUX = {
    "a_cle": ("GET", "/v1/models", {"Authorization": f"Bearer {CLE}"}, {}),
    "porte_sans_cle": ("POST", "/v1/mesh/pairings/redeem", {}, {"json": {}}),
}


class TestUnRefusDeDebitNeSOuvreQuALaFenetre:
    """Revue du 28/09/2026 : _too_many reflétait toute Origin, avec
    Access-Control-Allow-Credentials. C'était la seule réponse que la liste
    des origines de CORS ne gouvernait pas : une page https://evil.example
    ouverte dans le navigateur d'une machine du Wi-Fi lisait le 429 et son
    Retry-After, donc l'état du seau des portes sans clé."""

    @pytest.mark.parametrize("seau", sorted(_SEAUX))
    def test_un_429_porte_les_en_tetes_cors_de_la_fenetre(self, seau):
        methode, chemin, entetes, options = _SEAUX[seau]
        client = TestClient(_app_au_seau_etroit())
        reponse = _jusqu_au_429(
            client, methode, chemin, headers={"Origin": FENETRE, **entetes}, **options
        )
        assert reponse.headers.get("access-control-allow-origin") == FENETRE, (
            "sans cet en-tête, WebKit rejette « Load failed » au lieu de lire 429"
        )
        assert reponse.headers.get("access-control-allow-credentials") == "true"
        assert reponse.headers.get("retry-after"), "le refus dit combien attendre"
        vary = [v.strip() for v in reponse.headers.get("vary", "").split(",")]
        assert vary.count("Origin") == 1, f"Vary dupliqué : {vary}"

    @pytest.mark.parametrize("seau", sorted(_SEAUX))
    def test_un_429_ne_s_ouvre_pas_a_une_origine_etrangere(self, seau):
        methode, chemin, entetes, options = _SEAUX[seau]
        client = TestClient(_app_au_seau_etroit())
        reponse = _jusqu_au_429(
            client, methode, chemin, headers={"Origin": ETRANGERE, **entetes}, **options
        )
        assert "access-control-allow-origin" not in reponse.headers, (
            "la liste des origines de CORS reste la seule autorité, 429 compris"
        )

    def test_le_socket_du_reseau_local_ne_s_ouvre_a_aucune_origine(self):
        """8001 écoute sur 0.0.0.0, sans CORSMiddleware : ses clients sont
        natifs (téléphone, autres Mac). Toute page du Wi-Fi y lisait le 429
        des portes sans clé. Le client natif, lui, lit toujours Retry-After."""
        from diapason.server.app import create_lan_app

        reponse = _jusqu_au_429(
            TestClient(create_lan_app()),
            "POST",
            "/v1/mesh/pairings/redeem",
            json={},
            headers={"Origin": ETRANGERE},
        )
        assert not [
            nom for nom in reponse.headers if nom.startswith("access-control-")
        ], f"en-têtes CORS sur le socket du réseau local : {dict(reponse.headers)}"
        assert reponse.headers.get("retry-after")
