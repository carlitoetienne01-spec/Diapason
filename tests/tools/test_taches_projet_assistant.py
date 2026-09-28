"""§100 — 27/09/2026 : l'outil ignorait le projet lors de la création."""

import pytest

from diapason.tools.vie_tasks import VieTasksTool
from diapason.vie.workspace import VieWorkspaceStore


class TestCreerDansLeProjetDemande:
    @pytest.mark.parametrize("par_nom", [False, True])
    def test_le_projet_recoit_la_tache(self, tmp_path, par_nom):
        magasin = VieWorkspaceStore(tmp_path / "audit.db")
        projet = magasin.create_project({"name": "Apprendre"})
        cible = {"project": projet["name"]} if par_nom else {"project_id": projet["id"]}
        resultat = VieTasksTool(magasin).execute(action="create", title="Lire", **cible)
        assert resultat.success, "la création dans un projet existant réussit"
        assert resultat.metadata["task"]["projectId"] == projet["id"], (
            "ne pas créer une tâche détachée en annonçant un succès"
        )
        assert magasin.get_project(projet["id"])["taskTotal"] == 1
        magasin.create_task({"title": "Tâche personnelle"})
        liste = VieTasksTool(magasin).execute(action="list", **cible)
        assert [t["title"] for t in liste.metadata["tasks"]] == ["Lire"], (
            "relire le projet ne doit pas mélanger les tâches personnelles"
        )

    @pytest.mark.parametrize("cible", [{"project_id": "absent"}, {"project": "Appr"}])
    def test_un_projet_absent_ou_ambigu_ne_cree_rien(self, tmp_path, cible):
        magasin = VieWorkspaceStore(tmp_path / "audit.db")
        magasin.create_project({"name": "Apprendre le code"})
        magasin.create_project({"name": "Apprendre les langues"})
        resultat = VieTasksTool(magasin).execute(action="create", title="Lire", **cible)
        assert not resultat.success, "une destination incertaine reste un refus"
        assert magasin.list_tasks() == [], "aucune écriture hors du projet demandé"
