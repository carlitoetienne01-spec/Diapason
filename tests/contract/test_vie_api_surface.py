"""La surface du domaine vie (/v1/vie) et son alias /v1/succes.

25/09/2026, étape 4 du plan de la phase 1b. Le domaine répond sous deux
préfixes : /v1/vie, son nom, et /v1/succes, l'alias des clients d'avant le
renommage (la fenêtre installée, le mini-panneau, un bundle en cache, le
script lacite). Deux instantanés les figent. S'ils divergent, un client
appelle sous l'ancien nom une route que le nouveau n'a plus — ou
l'inverse — et le 404 tombe dans un outil qui ne l'affiche pas.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.vie import routes as routes_vie  # noqa: E402
from diapason.vie.routes import PREFIXE, PREFIXE_HERITE, surface_api  # noqa: E402

ICI = pathlib.Path(__file__).parent
SURFACE_VIE = ICI / "vie_api_surface.json"
SURFACE_ALIAS = ICI / "succes_api_surface.json"


def _figees(chemin: pathlib.Path) -> list[str]:
    return json.loads(chemin.read_text(encoding="utf-8"))


class TestLaSurfaceVieNeBougePasParAccident:
    """Le cliquet du nom neuf, jumeau de celui de l'alias."""

    def test_aucune_route_disparue_ni_renommee(self):
        perdues = set(_figees(SURFACE_VIE)) - set(surface_api(PREFIXE))
        assert not perdues, (
            f"{len(perdues)} route(s) de /v1/vie ont disparu :\n  "
            + "\n  ".join(sorted(perdues))
            + "\n\nSi c'est voulu, régénère les DEUX instantanés dans ce commit."
        )

    def test_les_routes_neuves_sont_declarees(self):
        neuves = set(surface_api(PREFIXE)) - set(_figees(SURFACE_VIE))
        assert not neuves, (
            f"{len(neuves)} route(s) neuve(s) hors instantané :\n  "
            + "\n  ".join(sorted(neuves))
            + "\n\nRégénère :\n  .venv/bin/python scripts/gen_vie_surface.py\n"
            "  .venv/bin/python scripts/gen_succes_surface.py"
        )


class TestLAliasEstLeMiroirDuNomNeuf:
    """Les deux instantanés sont égaux au préfixe près."""

    def test_les_deux_instantanes_ne_different_que_par_le_prefixe(self):
        vie = [r.replace(f" {PREFIXE}/", " ¤/") for r in _figees(SURFACE_VIE)]
        figees_alias = _figees(SURFACE_ALIAS)
        alias = [r.replace(f" {PREFIXE_HERITE}/", " ¤/") for r in figees_alias]
        assert vie == alias, (
            "vie_api_surface.json et succes_api_surface.json divergent : "
            f"{sorted(set(vie) ^ set(alias))[:5]}"
        )
        assert len(vie) >= 100, f"{len(vie)} routes seulement : l'instantané est vide ?"

    def test_l_alias_repond_comme_le_nom_neuf(self, tmp_path):
        """Même magasin, même liste — l'alias n'est pas une copie figée."""
        from diapason.vie.sync import VieSyncStore

        magasin = VieSyncStore(tmp_path / "vie.db")
        magasin.create_task({"title": "Témoin", "date": "2026-09-25"})
        routes_vie.set_store_for_tests(magasin)
        app = FastAPI()
        routes_vie.monter(app)
        client = TestClient(app)
        try:
            neuf = client.get(f"{PREFIXE}/tasks")
            ancien = client.get(f"{PREFIXE_HERITE}/tasks")
        finally:
            routes_vie.set_store_for_tests(None)
        assert neuf.status_code == ancien.status_code == 200
        assert neuf.json() == ancien.json(), "l'alias doit rendre la même liste"
        assert neuf.json()["count"] == 1, "la tâche témoin doit être listée"


class TestLeCompteurDeLAlias:
    """L'alias ne se retire qu'une fois son compteur resté à zéro (étape 14c)
    — un compteur qui ne compte pas le ferait retirer au jugé."""

    def _client(self, tmp_path) -> TestClient:
        from diapason.vie.sync import VieSyncStore

        routes_vie.set_store_for_tests(VieSyncStore(tmp_path / "vie.db"))
        app = FastAPI()
        routes_vie.monter(app)
        return TestClient(app)

    def test_seul_l_ancien_prefixe_est_compte(self, tmp_path):
        routes_vie.compteur_alias.remettre_a_zero()
        client = self._client(tmp_path)
        try:
            client.get(f"{PREFIXE}/tasks")
            client.get(f"{PREFIXE}/projects")
            assert routes_vie.compteur_alias.total == 0, (
                "un appel sous /v1/vie ne doit pas compter comme un client ancien"
            )
            client.get(f"{PREFIXE_HERITE}/tasks")
            client.get(f"{PREFIXE_HERITE}/tasks")
            assert routes_vie.compteur_alias.total == 2, "deux appels à l'alias"
            assert routes_vie.compteur_alias.par_chemin == {
                f"{PREFIXE_HERITE}/tasks": 2
            }
        finally:
            routes_vie.set_store_for_tests(None)
            routes_vie.compteur_alias.remettre_a_zero()

    def test_le_journal_est_borne_a_une_ligne_par_dix_minutes(self, caplog):
        compteur = routes_vie.CompteurAlias()
        with caplog.at_level("WARNING", logger="diapason.vie.routes"):
            compteur.noter("/v1/succes/tasks", maintenant=1000.0)
            for i in range(50):
                compteur.noter("/v1/succes/tasks", maintenant=1000.0 + i)
            compteur.noter("/v1/succes/notes", maintenant=1000.0 + 601)
        lignes = [r for r in caplog.records if "alias /v1/succes" in r.getMessage()]
        assert len(lignes) == 2, (
            f"{len(lignes)} lignes : une au premier accès, une après dix minutes"
        )
        assert "52 accès" in lignes[-1].getMessage(), lignes[-1].getMessage()
        assert compteur.total == 52


@pytest.fixture(scope="module")
def schema() -> dict:
    from diapason.server.app import create_app

    app = create_app(MagicMock(), "test-model")
    reponse = TestClient(app, raise_server_exceptions=False).get("/openapi.json")
    assert reponse.status_code == 200, reponse.text[:400]
    return reponse.json()


class TestLeSchemaNeDoublePasLesRoutes:
    """L'alias est hors du schéma : sinon chaque route y figurerait deux fois,
    et un client généré aurait deux méthodes pour un même geste."""

    def test_aucun_operation_id_en_double(self, schema):
        vus: dict[str, int] = {}
        for operations in schema["paths"].values():
            for operation in operations.values():
                if isinstance(operation, dict) and "operationId" in operation:
                    oid = operation["operationId"]
                    vus[oid] = vus.get(oid, 0) + 1
        doubles = sorted(o for o, n in vus.items() if n > 1)
        assert not doubles, f"operationId en double : {doubles[:5]}"

    def test_le_nom_neuf_est_decrit_et_l_alias_ne_l_est_pas(self, schema):
        chemins = schema["paths"]
        assert any(c.startswith(f"{PREFIXE}/") for c in chemins), (
            "aucune route /v1/vie dans le schéma"
        )
        assert not any(c.startswith(f"{PREFIXE_HERITE}/") for c in chemins), (
            "l'alias /v1/succes ne doit pas figurer dans le schéma"
        )
