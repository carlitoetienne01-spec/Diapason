"""Les cinq formes de projet : arbre, carte, pipeline, réseau, cycle.

Chaque test couvre un comportement qui pourrait mentir en silence : une étape
fantôme qui entre en base, une boucle qui rend le réseau irrésolvable, une
carte « Fait » non cochée, un tour de cycle déclenché par une simple lecture.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from diapason.succes.store import SuccesError
from diapason.succes.structures import (
    DEFAULT_STAGES,
    PROJECT_STRUCTURES,
    normalize_cadence,
    normalize_structure,
    normalize_structure_config,
)
from diapason.succes.sync import SuccesSyncStore


@pytest.fixture
def store() -> SuccesSyncStore:
    return SuccesSyncStore(pathlib.Path(tempfile.mkdtemp()) / "succes.db")


# ── la forme elle-même ────────────────────────────────────────────────────


class TestLaFormeDuProjet:
    def test_les_cinq_formes_plus_la_liste_existent(self) -> None:
        assert set(PROJECT_STRUCTURES) == {
            "flat",
            "tree",
            "mindmap",
            "pipeline",
            "network",
            "cycle",
        }

    @pytest.mark.parametrize("forme", PROJECT_STRUCTURES)
    def test_chaque_forme_se_cree(self, store: SuccesSyncStore, forme: str) -> None:
        projet = store.create_project({"name": f"P-{forme}", "structure": forme})
        assert projet["structure"] == forme

    def test_une_forme_inconnue_est_refusee_en_les_nommant(self) -> None:
        with pytest.raises(SuccesError, match="pipeline"):
            normalize_structure("spirale")

    def test_un_kit_force_l_arbre_seulement_depuis_la_liste(self) -> None:
        assert normalize_structure("flat", kit_id="moving") == "tree"
        assert normalize_structure("mindmap", kit_id="moving") == "mindmap"

    def test_la_configuration_ne_garde_que_ce_que_la_forme_connait(self) -> None:
        """Des réglages morts se synchroniseraient à jamais."""
        config = normalize_structure_config(
            "cycle", {"stages": ["a", "b"], "levelLabels": ["x"]}
        )
        assert config == {}

    def test_les_etages_de_l_arbre_sont_bornes_et_sans_doublon(self) -> None:
        with pytest.raises(SuccesError, match="doublon"):
            normalize_structure_config("tree", {"levelLabels": ["But", "but"]})
        with pytest.raises(SuccesError, match="6"):
            normalize_structure_config(
                "tree", {"levelLabels": ["a", "b", "c", "d", "e", "f", "g"]}
            )

    def test_un_pipeline_sans_etapes_recoit_les_defauts(self) -> None:
        config = normalize_structure_config("pipeline", None)
        assert config["stages"] == list(DEFAULT_STAGES)

    def test_un_pipeline_d_une_seule_etape_est_refuse(self) -> None:
        with pytest.raises(SuccesError, match="deux"):
            normalize_structure_config("pipeline", {"stages": ["Fait"]})

    def test_la_configuration_survit_a_l_aller_retour(
        self, store: SuccesSyncStore
    ) -> None:
        projet = store.create_project(
            {
                "name": "Portfolio",
                "structure": "tree",
                "structureConfig": {"levelLabels": ["Objectif", "Livrables"]},
            }
        )
        relu = store.get_project(projet["id"])
        assert relu["structureConfig"] == {"levelLabels": ["Objectif", "Livrables"]}


# ── le pipeline : l'étape et le sort de « done » ──────────────────────────


class TestLePipeline:
    def _pipeline(self, store: SuccesSyncStore) -> dict:
        return store.create_project(
            {
                "name": "Vidéos",
                "structure": "pipeline",
                "structureConfig": {"stages": ["Idée", "Montage", "Publié"]},
            }
        )

    def test_une_tache_sans_etape_recoit_la_premiere(
        self, store: SuccesSyncStore
    ) -> None:
        projet = self._pipeline(store)
        tache = store.create_task({"title": "Vidéo 1", "projectId": projet["id"]})
        assert tache["stage"] == "Idée"

    def test_une_etape_fantome_est_refusee_en_nommant_les_vraies(
        self, store: SuccesSyncStore
    ) -> None:
        projet = self._pipeline(store)
        with pytest.raises(SuccesError, match="Idée, Montage, Publié"):
            store.create_task(
                {"title": "X", "projectId": projet["id"], "stage": "Brouillon"}
            )

    def test_entrer_dans_la_derniere_etape_coche_la_tache(
        self, store: SuccesSyncStore
    ) -> None:
        """Deux vérités séparées finiraient par se contredire."""
        projet = self._pipeline(store)
        tache = store.create_task({"title": "V", "projectId": projet["id"]})
        avance = store.update_task(tache["id"], {"stage": "Publié"})
        assert avance["done"] is True
        assert avance["completedDate"] != ""

    def test_sortir_de_la_derniere_etape_decoche(self, store: SuccesSyncStore) -> None:
        projet = self._pipeline(store)
        tache = store.create_task(
            {"title": "V", "projectId": projet["id"], "stage": "Publié"}
        )
        assert tache["done"] is True
        recule = store.update_task(tache["id"], {"stage": "Montage"})
        assert recule["done"] is False
        assert recule["completedDate"] == ""

    def test_demenager_hors_pipeline_efface_l_etape(
        self, store: SuccesSyncStore
    ) -> None:
        """Une étape qui suivrait la tâche ne voudrait plus rien dire."""
        pipeline = self._pipeline(store)
        liste = store.create_project({"name": "Divers", "structure": "flat"})
        tache = store.create_task({"title": "V", "projectId": pipeline["id"]})
        parti = store.update_task(tache["id"], {"projectId": liste["id"]})
        assert parti["stage"] == ""

    def test_hors_pipeline_l_etape_demandee_est_ignoree(
        self, store: SuccesSyncStore
    ) -> None:
        liste = store.create_project({"name": "Divers", "structure": "flat"})
        tache = store.create_task(
            {"title": "T", "projectId": liste["id"], "stage": "Publié"}
        )
        assert tache["stage"] == ""


# ── le réseau : des synapses sans boucle ──────────────────────────────────


class TestLeReseau:
    def _reseau(self, store: SuccesSyncStore) -> tuple[dict, dict, dict, dict]:
        projet = store.create_project({"name": "Démgt", "structure": "network"})
        a = store.create_task({"title": "permis", "projectId": projet["id"]})
        b = store.create_task({"title": "camion", "projectId": projet["id"]})
        c = store.create_task({"title": "cartons", "projectId": projet["id"]})
        return projet, a, b, c

    def test_une_arete_se_cree_et_se_relit(self, store: SuccesSyncStore) -> None:
        projet, a, b, _ = self._reseau(store)
        store.create_task_edge(projet["id"], a["id"], b["id"])
        edges = store.list_task_edges(projet["id"])
        assert [(e["fromTaskId"], e["toTaskId"]) for e in edges] == [(a["id"], b["id"])]

    def test_une_boucle_est_refusee_meme_indirecte(
        self, store: SuccesSyncStore
    ) -> None:
        """Avec un cycle, « que puis-je faire maintenant ? » n'a plus de réponse."""
        projet, a, b, c = self._reseau(store)
        store.create_task_edge(projet["id"], a["id"], b["id"])
        store.create_task_edge(projet["id"], b["id"], c["id"])
        with pytest.raises(SuccesError, match="boucle"):
            store.create_task_edge(projet["id"], c["id"], a["id"])

    def test_une_tache_ne_se_debloque_pas_elle_meme(
        self, store: SuccesSyncStore
    ) -> None:
        projet, a, _, _ = self._reseau(store)
        with pytest.raises(SuccesError, match="elle-même"):
            store.create_task_edge(projet["id"], a["id"], a["id"])

    def test_une_tache_d_un_autre_projet_est_refusee(
        self, store: SuccesSyncStore
    ) -> None:
        projet, a, _, _ = self._reseau(store)
        autre = store.create_project({"name": "Autre", "structure": "network"})
        etrangere = store.create_task({"title": "x", "projectId": autre["id"]})
        with pytest.raises(SuccesError, match="n'appartient pas"):
            store.create_task_edge(projet["id"], a["id"], etrangere["id"])

    def test_supprimer_une_arete_absente_est_un_404_pas_un_succes(
        self, store: SuccesSyncStore
    ) -> None:
        projet, a, b, _ = self._reseau(store)
        with pytest.raises(SuccesError):
            store.delete_task_edge(projet["id"], a["id"], b["id"])

    def test_supprimer_puis_relire(self, store: SuccesSyncStore) -> None:
        projet, a, b, _ = self._reseau(store)
        store.create_task_edge(projet["id"], a["id"], b["id"])
        store.delete_task_edge(projet["id"], a["id"], b["id"])
        assert store.list_task_edges(projet["id"]) == []


# ── le cycle : la cadence et le nouveau tour ──────────────────────────────


class TestLeCycle:
    def test_la_cadence_se_valide_et_survit(self, store: SuccesSyncStore) -> None:
        projet = store.create_project({"name": "Routines", "structure": "cycle"})
        tache = store.create_task(
            {
                "title": "Revue",
                "projectId": projet["id"],
                "cadence": {"every": "week", "day": 6},
            }
        )
        assert tache["cadence"] == {"every": "week", "day": 6}

    @pytest.mark.parametrize(
        "cadence, motif",
        [
            ({"every": "année"}, "day, week ou month"),
            ({"every": "week"}, "jour"),
            ({"every": "week", "day": 9}, "0 .lundi. à 6"),
            ({"every": "month", "day": 31}, "1 à 28"),
        ],
    )
    def test_une_cadence_invalide_est_refusee(self, cadence, motif) -> None:
        with pytest.raises(SuccesError, match=motif):
            normalize_cadence(cadence)

    def test_le_jour_mensuel_s_arrete_a_28_pour_exister_tous_les_mois(self) -> None:
        assert normalize_cadence({"every": "month", "day": 28})

    def test_un_nouveau_tour_decoche_tout_et_compte(
        self, store: SuccesSyncStore
    ) -> None:
        projet = store.create_project({"name": "Routines", "structure": "cycle"})
        t1 = store.create_task({"title": "a", "projectId": projet["id"], "done": True})
        store.create_task({"title": "b", "projectId": projet["id"]})
        assert t1["done"] is True
        resultat = store.reset_cycle(projet["id"])
        assert resultat["reopened"] == 1
        taches = [t for t in store.list_tasks() if t["projectId"] == projet["id"]]
        assert all(not t["done"] for t in taches)

    def test_un_tour_hors_cycle_est_refuse(self, store: SuccesSyncStore) -> None:
        """Décocher les tâches d'une liste serait une perte, pas un tour."""
        projet = store.create_project({"name": "Liste", "structure": "flat"})
        with pytest.raises(SuccesError, match="cycle"):
            store.reset_cycle(projet["id"])


# ── les kits des nouvelles formes ─────────────────────────────────────────


class TestLesKitsDeFormes:
    def test_le_kit_pipeline_cree_un_pipeline_avec_ses_etapes(
        self, store: SuccesSyncStore
    ) -> None:
        projet = store.create_project({"name": "Chaîne", "kitId": "video-release"})
        assert projet["structure"] == "pipeline"
        assert projet["structureConfig"]["stages"][0] == "Idée"
        taches = [t for t in store.list_tasks() if t["projectId"] == projet["id"]]
        assert taches and all(t["stage"] == "Idée" for t in taches)

    def test_le_kit_cycle_cree_des_taches_cadencees(
        self, store: SuccesSyncStore
    ) -> None:
        projet = store.create_project({"name": "Routines", "kitId": "weekly-reset"})
        assert projet["structure"] == "cycle"
        taches = [t for t in store.list_tasks() if t["projectId"] == projet["id"]]
        assert taches and all(t["cadence"] for t in taches)

    def test_les_kits_arborescents_restent_des_arbres(
        self, store: SuccesSyncStore
    ) -> None:
        projet = store.create_project({"name": "Démgt", "kitId": "moving"})
        assert projet["structure"] == "tree"
