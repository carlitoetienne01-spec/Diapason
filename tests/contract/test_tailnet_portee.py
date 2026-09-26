"""Chaque route de l'application est classée pour le téléphone, ou rien ne passe.

26/09/2026, phase 2 du plan mobile (étape 3). La passerelle du tailnet
enveloppe l'application ENTIÈRE. Le risque silencieux que ce cliquet ferme :
une route ajoutée plus tard par une autre session, exposée au téléphone
sans que personne l'ait décidé. La passerelle la refuse déjà (liste
d'autorisation) ; ce test fait en plus échouer la suite, pour que le refus
soit une décision et pas une surprise sur l'appareil.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from diapason.server.portee_tailnet import (  # noqa: E402
    OUVERTE,
    REFUSEE,
    ROUTES_DE_LA_PASSERELLE,
    SESSION,
    classer,
    cles_autorisees,
)

ICI = Path(__file__).parent
INSTANTANE = ICI / "tailnet_portee.json"
GENERATEUR = ICI.parents[1] / "scripts" / "gen_tailnet_portee.py"
REGENERER = "  .venv/bin/python scripts/gen_tailnet_portee.py"


def _generateur():
    spec = importlib.util.spec_from_file_location("gen_tailnet_portee", GENERATEUR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def actuelle(tmp_path_factory) -> dict[str, str | None]:
    dossier = tmp_path_factory.mktemp("portee")
    foyer = dossier / "foyer"
    foyer.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DIAPASON_HOME", str(foyer))
        patch.setenv("DIAPASON_NO_UPDATE_CHECK", "1")
        return _generateur().portee(dossier)


def _figee() -> dict[str, str | None]:
    return json.loads(INSTANTANE.read_text(encoding="utf-8"))


class TestChaqueRouteEstClassee:
    def test_aucune_route_n_est_laissee_sans_decision(self, actuelle):
        """Une valeur null est une route qu'aucune règle ne nomme."""
        orphelines = sorted(cle for cle, classe in actuelle.items() if classe is None)
        assert not orphelines, (
            f"{len(orphelines)} route(s) que personne n'a classée(s) pour le "
            "téléphone :\n  "
            + "\n  ".join(orphelines)
            + "\n\nLa passerelle les refuse. Décide dans "
            "src/diapason/server/portee_tailnet.py (session ? refus ?), puis :\n"
            + REGENERER
        )

    def test_l_instantane_est_le_miroir_exact(self, actuelle):
        """Une classe qui change doit se voir dans le diff du commit."""
        figee = _figee()
        ecarts = sorted(
            f"{cle} : {figee.get(cle)!r} → {actuelle.get(cle)!r}"
            for cle in set(figee) | set(actuelle)
            if figee.get(cle) != actuelle.get(cle)
        )
        assert not ecarts, (
            f"{len(ecarts)} écart(s) avec l'instantané :\n  "
            + "\n  ".join(ecarts)
            + "\n\nRégénère DANS CE COMMIT :\n"
            + REGENERER
        )

    def test_aucune_autorisation_ne_vise_une_route_disparue(self, actuelle):
        """Une clé autorisée sans route est un reste : le jour où une route
        reprend ce nom pour faire autre chose, elle hériterait d'une
        décision prise pour une autre."""
        restes = sorted(cles_autorisees() - set(actuelle))
        assert not restes, (
            "clés ouvertes au téléphone qui ne désignent plus aucune route :\n  "
            + "\n  ".join(restes)
        )


class TestCeQuiSOuvreSansSession:
    def test_exactement_la_sante_les_neuf_portes_et_les_deux_d_appareil(self, actuelle):
        from diapason.server.app import _PORTES_LAN

        attendues = (
            {"GET /health"}
            | set(ROUTES_DE_LA_PASSERELLE)
            | {f"POST {chemin}" for chemin in _PORTES_LAN}
        )
        ouvertes = {cle for cle, classe in actuelle.items() if classe == OUVERTE}
        assert ouvertes == attendues, (
            "une route sans session de plus est une route que n'importe quel "
            "appareil du tailnet atteint"
        )

    def test_le_bundle_exige_la_session(self, actuelle):
        """Le rattrape-tout et les assets : la page 401 « Ouvre Diapason
        depuis l'app » plutôt qu'un bundle servi à n'importe qui."""
        assert actuelle["GET /{full_path:path}"] == SESSION
        assert actuelle["MOUNT /assets"] == SESSION


class TestLesRefusDuPlan:
    """La liste refusée du plan (étape 3), nommément."""

    @pytest.mark.parametrize(
        "cle",
        [
            "POST /v1/mesh/pairings",
            "POST /v1/mesh/commands",
            "GET /v1/mesh/inbox",
            "POST /v1/config/set",
            "POST /v1/cloud/reload",
            "POST /v1/tools/{tool_name}/credentials",
            "GET /v1/account/status",
            "POST /v1/account/login",
            "POST /v1/gestures/frame",
            "GET /v1/actions/capabilities",
            "GET /v1/succes/tasks",
            "POST /v1/vie/sync/pair",
            "GET /openapi.json",
        ],
    )
    def test_refusee(self, cle):
        assert classer(cle) == REFUSEE, f"{cle} ne doit pas atteindre le téléphone"

    def test_un_prefixe_n_ouvre_jamais_rien(self):
        """Seul le refus s'accorde par famille : une route inventée sous
        /v1/vie/ n'est PAS ouverte parce que ses voisines le sont."""
        assert classer("GET /v1/vie/route-inventee-demain") is None
        assert classer("GET /v1/chat/route-inventee-demain") is None


class TestLaVoixDuMac:
    """Phase 4 (26/09/2026) : la voix rouverte au téléphone, et elle seule."""

    def test_la_seance_et_sa_sante_sont_sous_session(self, actuelle):
        assert actuelle["WS /v1/voice/live"] == SESSION
        assert actuelle["GET /v1/voice/live/health"] == SESSION

    def test_une_route_de_voix_ajoutee_demain_reste_refusee(self):
        """La famille /v1/voice/ garde son refus : ouvrir la séance n'ouvre
        pas la prochaine route qu'on y mettra."""
        assert classer("GET /v1/voice/route-inventee-demain") == REFUSEE
