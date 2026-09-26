"""Les anciens noms d'outils mènent aux neufs — et jamais au-delà.

25/09/2026, étape 7 du plan de la phase 1b (docs/development/
diapason-mobile.md). Les sept outils ``succes_*`` s'appellent ``vie_*``. Le
défaut évité : un agent sauvegardé, ``config.toml``, ``SOUL.md`` ou un client
vocal pas encore reconstruit qui cite ``succes_tasks`` perdait l'outil sans
un mot, et le modèle lisait « Unknown tool ». Le défaut qu'il ne fallait pas
créer à la place : un alias appliqué APRÈS le plafond de la voix (celui de
``DEFAULT_VOICE_TOOL_IDS``), ou montré au modèle à côté du vrai nom.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from diapason.core.noms_outils import (
    ALIAS_OUTILS,
    nom_canonique,
    noms_canoniques,
    signaler_outil_inconnu,
)
from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolCall
from diapason.tools._stubs import ToolExecutor
from diapason.tools.vie_continuity import VieContinuityTool, VieDeleteContinuityTool
from diapason.tools.vie_finances import VieFinancesTool
from diapason.tools.vie_tasks import VieDeleteTaskTool, VieTasksTool
from diapason.tools.vie_workspace import VieDeleteItemTool, VieWorkspaceTool
from diapason.vie.sync import VieSyncStore

_CLASSES = {
    "vie_tasks": VieTasksTool,
    "vie_workspace": VieWorkspaceTool,
    "vie_continuity": VieContinuityTool,
    "vie_finances": VieFinancesTool,
    "vie_delete_task": VieDeleteTaskTool,
    "vie_delete_item": VieDeleteItemTool,
    "vie_delete_continuity": VieDeleteContinuityTool,
}


@pytest.fixture
def registre(tmp_path, monkeypatch) -> None:
    """Le conftest vide ToolRegistry, et l'import en cache ne le repeuple
    pas : on inscrit les classes soi-même, dans un foyer temporaire."""
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
    for nom, classe in _CLASSES.items():
        ToolRegistry.register_value(nom, classe)


class TestLaTable:
    def test_sept_anciens_noms_menent_chacun_a_un_outil_vie(self):
        assert len(ALIAS_OUTILS) == 7, "les sept outils succes_* du 25/09/2026"
        for ancien, neuf in ALIAS_OUTILS.items():
            assert ancien.startswith("succes_") and neuf.startswith("vie_"), ancien
            assert neuf == "vie_" + ancien.removeprefix("succes_"), ancien
            assert classe_de(neuf)().spec.name == neuf, (
                f"{neuf} doit être le nom que l'outil porte réellement"
            )

    def test_un_nom_sans_alias_reste_tel_quel(self):
        assert nom_canonique("web_search") == "web_search"
        assert nom_canonique("vie_tasks") == "vie_tasks"

    def test_une_liste_editee_a_moitie_ne_donne_pas_l_outil_deux_fois(self):
        assert noms_canoniques(["succes_tasks", "vie_tasks", "web_search"]) == [
            "vie_tasks",
            "web_search",
        ], "l'ancien et le neuf nom désignent UN outil"

    def test_la_table_ne_se_modifie_pas(self):
        with pytest.raises(TypeError):
            ALIAS_OUTILS["succes_x"] = "shell_exec"  # type: ignore[index]


def classe_de(nom: str) -> type:
    return _CLASSES[nom]


class TestLeRegistre:
    def test_l_ancien_nom_trouve_l_outil_neuf(self, registre):
        assert ToolRegistry.contains("succes_tasks"), "un agent qui le cite le garde"
        assert ToolRegistry.get("succes_tasks") is VieTasksTool
        assert ToolRegistry.create("succes_finances").spec.name == "vie_finances"

    def test_le_catalogue_ne_montre_que_le_nom_canonique(self, registre):
        cles = set(ToolRegistry.keys())
        assert not cles & set(ALIAS_OUTILS), (
            "un alias au catalogue montrerait deux outils identiques au 9b"
        )

    def test_un_ancien_nom_ne_peut_pas_etre_enregistre(self, registre):
        with pytest.raises(ValueError, match="ancien nom"):
            ToolRegistry.register_value("succes_tasks", VieTasksTool)
        with pytest.raises(ValueError, match="ancien nom"):
            ToolRegistry.register("succes_workspace")


class TestLExecuteur:
    def test_un_appel_a_l_ancien_nom_s_execute(self, tmp_path):
        """SOUL.md apprend encore succes_tasks au modèle."""
        magasin = VieSyncStore(tmp_path / "vie.db")
        magasin.create_task({"title": "Relire le plan", "date": "2026-09-25"})
        resultat = ToolExecutor([VieTasksTool(magasin)]).execute(
            ToolCall(
                id="t1",
                name="succes_tasks",
                arguments=json.dumps({"action": "list", "date": "2026-09-25"}),
            )
        )
        assert "Unknown tool" not in resultat.content, resultat.content
        assert resultat.success is True, resultat.content
        assert resultat.tool_name == "vie_tasks", "jugé sous son vrai nom"

    def test_la_suppression_garde_sa_cloche_sous_l_ancien_nom(self, tmp_path):
        """L'alias ne contourne pas la confirmation : il mène au même outil."""
        magasin = VieSyncStore(tmp_path / "vie.db")
        tache = magasin.create_task({"title": "Ne pas supprimer sans accord"})
        refus = ToolExecutor(
            [VieDeleteTaskTool(magasin)],
            interactive=True,
            confirm_callback=lambda _question: False,
        ).execute(
            ToolCall(
                id="d1",
                name="succes_delete_task",
                arguments=json.dumps({"task_id": tache["id"]}),
            )
        )
        assert refus.success is False
        assert magasin.get_task(tache["id"]), "refusée, la tâche reste"


class TestLaVoix:
    def test_la_trame_ancienne_ne_donne_que_l_outil_neuf(self):
        """succes_tasks traduit PUIS confronté au plafond ; mesh_send, hors du
        plafond, reste dehors — restreindre, jamais élargir."""
        from diapason.server.voice_live_routes import outils_demandes_par_le_client

        assert outils_demandes_par_le_client("succes_tasks,mesh_send") == ["vie_tasks"]

    def test_un_alias_ne_fait_pas_passer_un_outil_hors_plafond(self):
        from diapason.server.voice_live_routes import outils_demandes_par_le_client

        assert outils_demandes_par_le_client("shell_exec,mesh_send") is None

    def test_le_modele_qui_appelle_l_ancien_nom_est_servi(self, registre):
        from diapason.speech.realtime.tools import (
            execute_voice_tool,
            list_voice_tool_ids,
        )

        assert "vie_tasks" in list_voice_tool_ids(["succes_tasks"])
        assert "succes_tasks" not in list_voice_tool_ids(), "jamais au catalogue"
        resultat = execute_voice_tool("succes_tasks", {"action": "list"})
        assert "not allowed" not in str(resultat.get("error", "")), resultat


class TestLesEcartsSeDisent:
    def test_un_nom_inconnu_se_journalise_une_fois(self, caplog):
        with caplog.at_level(logging.WARNING, logger="diapason.core.noms_outils"):
            signaler_outil_inconnu("essai", "outil_fantome_123")
            signaler_outil_inconnu("essai", "outil_fantome_123")
        lignes = [r for r in caplog.records if "outil_fantome_123" in r.message]
        assert len(lignes) == 1, "une fois par lieu et par nom, pas à chaque appel"

    def test_la_liste_vocale_dit_ce_qu_elle_ecarte(self, registre, caplog):
        from diapason.speech.realtime.tools import list_voice_tool_ids

        with caplog.at_level(logging.WARNING, logger="diapason.core.noms_outils"):
            retenus = list_voice_tool_ids(["vie_tasks", "outil_vocal_absent_456"])
        assert retenus == ["vie_tasks"]
        assert any("outil_vocal_absent_456" in r.message for r in caplog.records), (
            "un outil écarté de la voix doit se dire au niveau WARNING"
        )


class TestLaPolitiqueDeCapacites:
    def test_une_permission_ecrite_pour_l_ancien_nom_vaut_pour_le_neuf(
        self, tmp_path: Path
    ):
        """La ressource vérifiée est le nom de l'outil : une politique écrite
        avant le 25/09/2026 aurait cessé de correspondre sans un mot."""
        from diapason.security.capabilities import CapabilityPolicy

        fichier = tmp_path / "capabilities.json"
        fichier.write_text(
            json.dumps(
                {
                    "agents": [
                        {
                            "agent_id": "voice",
                            "grants": [
                                {"capability": "file:read", "pattern": "succes_tasks"}
                            ],
                        }
                    ]
                }
            )
        )
        politique = CapabilityPolicy(policy_path=str(fichier), default_deny=True)
        assert politique.check("voice", "file:read", "vie_tasks"), (
            "la permission accordée à succes_tasks doit valoir pour vie_tasks"
        )
