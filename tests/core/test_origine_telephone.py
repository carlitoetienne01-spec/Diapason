"""Le plafond d'outils du téléphone (core/origine_telephone.py), 26/09/2026.

La passerelle du tailnet refusait /v1/context/*, /v1/screen_share/* et
/v1/actions/* — et laissait la Discussion lancer screen_read_text et
clipboard_read sans confirmation. Ces tests éprouvent le plafond là où il
vit : l'exécuteur d'outils, et l'enveloppe de chaque outil.
"""

from __future__ import annotations

import pytest

from diapason.core.events import EventBus, EventType
from diapason.core.origine_telephone import (
    OUTILS_DU_TELEPHONE,
    depuis_le_telephone,
    marquer_le_telephone,
)
from diapason.core.types import ToolCall, ToolResult
from diapason.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class _Espion(BaseTool):
    """Un outil qui note chaque exécution, sous le nom qu'on lui donne."""

    def __init__(self, nom: str) -> None:
        self.nom = nom
        self.tool_id = nom
        self.executions: list[dict] = []

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.nom, description="espion")

    def execute(self, **params) -> ToolResult:
        self.executions.append(params)
        return ToolResult(tool_name=self.nom, content="contenu du Mac", success=True)


def _executer(executeur: ToolExecutor, nom: str) -> ToolResult:
    return executeur.execute(ToolCall(id="c1", name=nom, arguments="{}"))


class TestLePlafondDeLExecuteur:
    @pytest.mark.parametrize(
        "nom",
        [
            "screen_read_text",
            "screen_describe",
            "screen_snap",
            "clipboard_read",
            "system_vitals",
            "open_anything",
            "app_install",
            "file_trash",
            "mail_send",
            "messages_send",
            "mesh_send",
            "geste_deposer",
            "shell_exec",
        ],
    )
    def test_depuis_le_telephone_ce_qui_touche_le_mac_est_refuse(self, nom):
        """Sans le plafond, « lis mon écran » rendait l'écran du Mac au
        téléphone — sans confirmation pour les quatre premiers."""
        espion = _Espion(nom)
        bus = EventBus()
        refus: list[dict] = []
        bus.subscribe(EventType.CAPABILITY_DENIED, lambda e: refus.append(e.data))
        executeur = ToolExecutor([espion], bus, autoload_capability_policy=False)
        with marquer_le_telephone():
            resultat = _executer(executeur, nom)
        assert resultat.success is False, f"{nom} a répondu au téléphone"
        assert "téléphone" in resultat.content
        assert espion.executions == [], f"{nom} s'est exécuté malgré le refus"
        assert refus and refus[0]["capability"] == "tailnet", (
            "un refus sans CAPABILITY_DENIED se lit comme un succès (§5)"
        )

    def test_hors_du_telephone_le_meme_outil_s_execute(self):
        espion = _Espion("screen_read_text")
        executeur = ToolExecutor([espion], autoload_capability_policy=False)
        assert _executer(executeur, "screen_read_text").success is True
        assert espion.executions == [{}]

    def test_un_outil_de_donnees_reste_permis_au_telephone(self):
        espion = _Espion("vie_tasks")
        executeur = ToolExecutor([espion], autoload_capability_policy=False)
        with marquer_le_telephone():
            assert _executer(executeur, "vie_tasks").success is True
        assert espion.executions == [{}]

    def test_un_ancien_nom_est_juge_sous_son_nom_canonique(self):
        """succes_tasks devient vie_tasks AVANT le plafond : il reste permis."""
        espion = _Espion("vie_tasks")
        executeur = ToolExecutor([espion], autoload_capability_policy=False)
        with marquer_le_telephone():
            assert _executer(executeur, "succes_tasks").success is True


class TestLeContournementDeLExecuteur:
    def test_un_appel_direct_a_l_outil_est_refuse_aussi(self):
        """api_routes.py, agents/hybrid et welcome_runner appellent
        Tool().execute sans l'exécuteur : l'enveloppe de chaque outil porte
        le même plafond."""
        espion = _Espion("clipboard_read")
        with marquer_le_telephone():
            resultat = espion.execute()
        assert resultat.success is False
        assert espion.executions == []
        assert espion.execute().success is True, "hors du téléphone : permis"


class TestLaMarque:
    def test_absente_par_defaut_et_retiree_a_la_sortie(self):
        assert depuis_le_telephone() is False
        with marquer_le_telephone():
            assert depuis_le_telephone() is True
        assert depuis_le_telephone() is False

    def test_la_liste_ne_porte_rien_qui_lise_l_ecran_ou_agisse(self):
        """Un garde contre l'élargissement distrait de la liste."""
        interdits = {
            "screen_read_text",
            "screen_describe",
            "screen_snap",
            "clipboard_read",
            "system_vitals",
            "open_anything",
            "app_install",
            "file_trash",
            "mail_send",
            "messages_send",
            "mail_compose",
            "messages_compose",
            "mesh_send",
            "geste_deposer",
            "handoff_continue",
            "browser_tabs",
            "volume_control",
            "media_control",
            "spotify_play",
            "shell_exec",
            "file_write",
            "apply_patch",
        }
        assert not (OUTILS_DU_TELEPHONE & interdits), OUTILS_DU_TELEPHONE & interdits
