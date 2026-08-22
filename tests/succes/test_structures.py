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


# ── ce que la réfutation a trouvé, et qui ne doit pas revenir ─────────────


class TestLaSynchronisationPorteLesFormes:
    """Une arête suffisait à briser TOUTE la réplication, définitivement.

    « task_edges » manquait à SYNC_ENTITIES. À la réception, l'entité inconnue
    faisait lever _apply_operation — qui tourne DANS une transaction : le lot
    entier était annulé. L'opération restant au journal de l'émetteur, chaque
    échange suivant échouait au même endroit. Mesuré : zéro projet, zéro tâche
    répliqués.
    """

    def _pair(self, tmp_path) -> tuple[SuccesSyncStore, SuccesSyncStore]:
        return (
            SuccesSyncStore(tmp_path / "a.db"),
            SuccesSyncStore(tmp_path / "b.db"),
        )

    def _repliquer(self, source: SuccesSyncStore, cible: SuccesSyncStore) -> dict:
        ops = source.list_operations(after=0, limit=500)["operations"]
        return cible.apply_inbound_operations(ops)

    def test_une_arete_ne_brise_plus_la_replication(self, tmp_path) -> None:
        a, b = self._pair(tmp_path)
        projet = a.create_project({"name": "N", "structure": "network"})
        t1 = a.create_task({"title": "un", "projectId": projet["id"]})
        t2 = a.create_task({"title": "deux", "projectId": projet["id"]})
        a.create_task_edge(projet["id"], t1["id"], t2["id"])
        a.create_task({"title": "après l'arête", "projectId": projet["id"]})

        self._repliquer(a, b)
        assert len(b.list_projects()) == 1
        assert len(b.list_tasks()) == 3, "tout ce qui suit l'arête doit arriver"
        assert len(b.list_task_edges(projet["id"])) == 1

    def test_la_suppression_d_arete_traverse(self, tmp_path) -> None:
        a, b = self._pair(tmp_path)
        projet = a.create_project({"name": "N", "structure": "network"})
        t1 = a.create_task({"title": "un", "projectId": projet["id"]})
        t2 = a.create_task({"title": "deux", "projectId": projet["id"]})
        a.create_task_edge(projet["id"], t1["id"], t2["id"])
        self._repliquer(a, b)
        a.delete_task_edge(projet["id"], t1["id"], t2["id"])
        self._repliquer(a, b)
        assert b.list_task_edges(projet["id"]) == []

    def test_l_etape_et_la_cadence_traversent(self, tmp_path) -> None:
        """Un pipeline arrivait vidé de ses colonnes, ses tâches nulle part."""
        a, b = self._pair(tmp_path)
        pipeline = a.create_project(
            {
                "name": "V",
                "structure": "pipeline",
                "structureConfig": {"stages": ["Idée", "Monté", "Publié"]},
            }
        )
        a.create_task({"title": "v1", "projectId": pipeline["id"], "stage": "Monté"})
        cycle = a.create_project({"name": "R", "structure": "cycle"})
        a.create_task(
            {
                "title": "revue",
                "projectId": cycle["id"],
                "cadence": {"every": "week", "day": 6},
            }
        )
        self._repliquer(a, b)

        projets = {p["name"]: p for p in b.list_projects()}
        assert projets["V"]["structureConfig"]["stages"] == ["Idée", "Monté", "Publié"]
        taches = {t["title"]: t for t in b.list_tasks()}
        assert taches["v1"]["stage"] == "Monté"
        assert taches["revue"]["cadence"] == {"every": "week", "day": 6}

    def test_une_arete_recue_qui_fermerait_une_boucle_est_acceptee(
        self, tmp_path
    ) -> None:
        """Refuser à la RÉCEPTION ferait échouer le lot et figerait les pairs.

        Deux appareils peuvent créer chacun une arête qui ne ferme un cycle
        qu'une fois réunies. La boucle se refuse à la création, là où un humain
        peut la comprendre.
        """
        a, b = self._pair(tmp_path)
        projet = b.create_project({"id": "p1", "name": "N", "structure": "network"})
        t1 = b.create_task({"id": "t1", "title": "un", "projectId": projet["id"]})
        t2 = b.create_task({"id": "t2", "title": "deux", "projectId": projet["id"]})
        b.create_task_edge(projet["id"], t1["id"], t2["id"])

        recue = [
            {
                "opId": "op-boucle",
                "deviceId": "autre-appareil",
                "entity": "task_edges",
                "entityId": "t2->t1",
                "kind": "upsert",
                "timestampMs": 9_999_999_999_999,
                "payload": {
                    "projectId": "p1",
                    "fromTaskId": "t2",
                    "toTaskId": "t1",
                },
                "request": {},
            }
        ]
        b.apply_inbound_operations(recue)
        assert len(b.list_task_edges("p1")) == 2


class TestCocherRespecteLaForme:
    """L'invariant du pipeline n'était tenu que dans un sens.

    « Entrer dans la dernière étape coche » passait par _resolve_stage. Mais
    cocher passe par set_task_done, le plus vieux chemin, qui ne consultait
    jamais la forme : on obtenait une carte cochée en première colonne, ou une
    carte « Fait » décochée. Deux vérités séparées finissent par se contredire.
    """

    def _pipeline(self, store: SuccesSyncStore) -> dict:
        return store.create_project(
            {
                "name": "V",
                "structure": "pipeline",
                "structureConfig": {"stages": ["Idée", "Monté", "Publié"]},
            }
        )

    def test_cocher_deplace_vers_la_derniere_etape(
        self, store: SuccesSyncStore
    ) -> None:
        projet = self._pipeline(store)
        tache = store.create_task({"title": "v", "projectId": projet["id"]})
        coche = store.set_task_done(tache["id"], True)
        assert coche["done"] is True
        assert coche["stage"] == "Publié"

    def test_decocher_fait_reculer_d_un_cran(self, store: SuccesSyncStore) -> None:
        """Reculer, pas revenir au début : le travail fait n'est pas annulé."""
        projet = self._pipeline(store)
        tache = store.create_task(
            {"title": "v", "projectId": projet["id"], "stage": "Publié"}
        )
        recule = store.set_task_done(tache["id"], False)
        assert recule["done"] is False
        assert recule["stage"] == "Monté"

    def test_hors_pipeline_cocher_ne_touche_a_aucune_etape(
        self, store: SuccesSyncStore
    ) -> None:
        liste = store.create_project({"name": "L", "structure": "flat"})
        tache = store.create_task({"title": "t", "projectId": liste["id"]})
        coche = store.set_task_done(tache["id"], True)
        assert coche["done"] is True
        assert coche["stage"] == ""


class TestLesTachesSuiventLaForme:
    def test_changer_les_etapes_range_les_taches_egarees(
        self, store: SuccesSyncStore
    ) -> None:
        """Le serveur fabriquait lui-même les étapes fantômes qu'il interdit."""
        projet = store.create_project(
            {
                "name": "V",
                "structure": "pipeline",
                "structureConfig": {"stages": ["Un", "Deux", "Trois"]},
            }
        )
        tache = store.create_task(
            {"title": "x", "projectId": projet["id"], "stage": "Deux"}
        )
        store.update_project(
            projet["id"], {"structureConfig": {"stages": ["Brouillon", "Final"]}}
        )
        assert store.get_task(tache["id"])["stage"] == "Brouillon"

    def test_quitter_le_pipeline_efface_les_etapes(
        self, store: SuccesSyncStore
    ) -> None:
        projet = store.create_project(
            {
                "name": "V",
                "structure": "pipeline",
                "structureConfig": {"stages": ["Un", "Deux"]},
            }
        )
        tache = store.create_task(
            {"title": "x", "projectId": projet["id"], "stage": "Deux"}
        )
        store.update_project(projet["id"], {"structure": "flat"})
        assert store.get_task(tache["id"])["stage"] == ""


class TestLesAretesSuiventLeursTaches:
    def test_supprimer_une_tache_emporte_ses_aretes(
        self, store: SuccesSyncStore
    ) -> None:
        """Sinon : une contrainte invisible, et donc insupprimable."""
        projet = store.create_project({"name": "N", "structure": "network"})
        a = store.create_task({"title": "a", "projectId": projet["id"]})
        b = store.create_task({"title": "b", "projectId": projet["id"]})
        c = store.create_task({"title": "c", "projectId": projet["id"]})
        store.create_task_edge(projet["id"], a["id"], b["id"])
        store.create_task_edge(projet["id"], b["id"], c["id"])
        store.delete_task(b["id"])
        assert store.list_task_edges(projet["id"]) == []
        # Et le refus fantôme disparaît avec elles.
        store.create_task_edge(projet["id"], c["id"], a["id"])
        assert len(store.list_task_edges(projet["id"])) == 1

    def test_une_arete_en_double_ne_cree_pas_d_operation(
        self, store: SuccesSyncStore
    ) -> None:
        projet = store.create_project({"name": "N", "structure": "network"})
        a = store.create_task({"title": "a", "projectId": projet["id"]})
        b = store.create_task({"title": "b", "projectId": projet["id"]})
        store.create_task_edge(projet["id"], a["id"], b["id"])
        avant = len(store.list_operations(after=0, limit=500)["operations"])
        store.create_task_edge(projet["id"], a["id"], b["id"])
        apres = len(store.list_operations(after=0, limit=500)["operations"])
        assert apres == avant, "un double-clic ne doit rien ajouter au journal"
        assert len(store.list_task_edges(projet["id"])) == 1


class TestLeTourDeCycleEstComplet:
    def test_le_tour_decoche_aussi_les_sous_taches(
        self, store: SuccesSyncStore
    ) -> None:
        """Sinon le tour « recommencé » s'achevait tout seul.

        Les sous-tâches restées cochées faisaient re-marquer la tâche faite au
        premier geste sur l'une d'elles, par recalcul de l'arbre.
        """
        projet = store.create_project({"name": "C", "structure": "cycle"})
        tache = store.create_task({"title": "revue", "projectId": projet["id"]})
        ajoutee = store.add_subtask(tache["id"], "point 1")
        sous_id = ajoutee["subtasks"][0]["id"]
        store.set_subtask_done(tache["id"], sous_id, True)
        assert store.get_task(tache["id"])["done"] is True

        store.reset_cycle(projet["id"])
        relue = store.get_task(tache["id"])
        assert relue["done"] is False
        assert all(not s["done"] for s in relue["subtasks"])

    def test_rejouer_un_tour_ne_le_refait_pas(self, store: SuccesSyncStore) -> None:
        """Un client qui renvoie son op après une coupure annulerait un travail
        refait entre-temps."""
        projet = store.create_project({"name": "C", "structure": "cycle"})
        tache = store.create_task({"title": "revue", "projectId": projet["id"]})
        store.set_task_done(tache["id"], True)
        premier = store.reset_cycle(projet["id"], op_id="tour-1")
        assert premier["reopened"] == 1

        store.set_task_done(tache["id"], True)  # le travail est refait
        rejeu = store.reset_cycle(projet["id"], op_id="tour-1")
        assert rejeu["reopened"] == 0
        assert store.get_task(tache["id"])["done"] is True
