"""Un projet supprimé doit emporter ses tâches.

Constaté le 22 août 2026 sur l'installation de Carlito : soixante-quinze
tâches survivaient à seize projets supprimés et s'entassaient dans la liste
« sans date ». Elles n'étaient plus rattachées à rien de visible, donc
introuvables par leur projet — et impossibles à supprimer autrement qu'une
par une.

``delete_project`` ne faisait qu'un ``UPDATE succes_projects``. Il ne touchait
ni les tâches, ni leurs sous-tâches, ni leurs arêtes.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from diapason.succes.workspace import SuccesWorkspaceStore


def _vivantes(chemin, project_id: str) -> list[str]:
    """Les tâches NON supprimées du projet, lues directement en base."""
    with closing(sqlite3.connect(chemin)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            r["title"]
            for r in conn.execute(
                "SELECT title FROM succes_tasks "
                "WHERE project_id=? AND deleted_at_ms IS NULL ORDER BY title",
                (project_id,),
            )
        ]


def _ops(chemin, entity: str) -> list[str]:
    with closing(sqlite3.connect(chemin)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            r["entity_id"]
            for r in conn.execute(
                "SELECT entity_id FROM succes_operations "
                "WHERE entity=? AND kind='delete'",
                (entity,),
            )
        ]


def test_supprimer_un_projet_emporte_ses_taches(tmp_path) -> None:
    chemin = tmp_path / "cascade.db"
    store = SuccesWorkspaceStore(chemin)
    projet = store.create_project({"name": "Déménage"})
    for titre in ("Louer le camion", "Cartons et emballage", "Jour J"):
        store.create_task({"title": titre, "projectId": projet["id"]})

    assert len(_vivantes(chemin, projet["id"])) == 3
    store.delete_project(projet["id"])
    assert _vivantes(chemin, projet["id"]) == [], (
        "les tâches survivaient au projet et polluaient « sans date »"
    )


def test_les_taches_des_autres_projets_ne_bougent_pas(tmp_path) -> None:
    chemin = tmp_path / "voisins.db"
    store = SuccesWorkspaceStore(chemin)
    condamne = store.create_project({"name": "À supprimer"})
    epargne = store.create_project({"name": "À garder"})
    store.create_task({"title": "Part avec", "projectId": condamne["id"]})
    store.create_task({"title": "Reste", "projectId": epargne["id"]})

    store.delete_project(condamne["id"])
    assert _vivantes(chemin, epargne["id"]) == ["Reste"]


def test_une_tache_sans_projet_est_intacte(tmp_path) -> None:
    """La liste libre n'appartient à personne : rien ne doit l'emporter."""
    chemin = tmp_path / "libre.db"
    store = SuccesWorkspaceStore(chemin)
    projet = store.create_project({"name": "Éphémère"})
    store.create_task({"title": "Liée", "projectId": projet["id"]})
    libre = store.create_task({"title": "Libre"})

    store.delete_project(projet["id"])
    restantes = [t["title"] for t in store.list_tasks() if t["id"] == libre["id"]]
    assert restantes == ["Libre"]


def test_les_sous_taches_partent_avec(tmp_path) -> None:
    chemin = tmp_path / "sous.db"
    store = SuccesWorkspaceStore(chemin)
    projet = store.create_project({"name": "Avec sous-tâches"})
    tache = store.create_task({"title": "Mère", "projectId": projet["id"]})
    store.add_subtask(tache["id"], "Fille")

    store.delete_project(projet["id"])
    with closing(sqlite3.connect(chemin)) as conn:
        restantes = conn.execute(
            "SELECT COUNT(*) FROM succes_subtasks WHERE deleted_at_ms IS NULL"
        ).fetchone()[0]
    assert restantes == 0


def test_les_aretes_partent_avec(tmp_path) -> None:
    """Sinon le graphe d'un pair garde des liens vers des disparus."""
    chemin = tmp_path / "aretes.db"
    store = SuccesWorkspaceStore(chemin)
    projet = store.create_project({"name": "Réseau", "structure": "network"})
    a = store.create_task({"title": "A", "projectId": projet["id"]})
    b = store.create_task({"title": "B", "projectId": projet["id"]})
    store.create_task_edge(projet["id"], a["id"], b["id"])

    store.delete_project(projet["id"])
    with closing(sqlite3.connect(chemin)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM succes_task_edges").fetchone()[0] == 0


def test_le_telephone_apprend_chaque_tache_separement(tmp_path) -> None:
    """Une op pour le projet ne suffit pas : le pair garderait les tâches."""
    chemin = tmp_path / "sync.db"
    store = SuccesWorkspaceStore(chemin)
    projet = store.create_project({"name": "Répliqué"})
    ids = [
        store.create_task({"title": t, "projectId": projet["id"]})["id"]
        for t in ("Un", "Deux")
    ]

    store.delete_project(projet["id"])
    assert _ops(chemin, "projects") == [projet["id"]]
    assert sorted(_ops(chemin, "tasks")) == sorted(ids)


def test_rejouer_la_meme_op_ne_supprime_pas_deux_fois(tmp_path) -> None:
    """Une coupure réseau fait renvoyer l'op ; elle ne doit pas doubler."""
    chemin = tmp_path / "rejeu.db"
    store = SuccesWorkspaceStore(chemin)
    projet = store.create_project({"name": "Rejeu"})
    store.create_task({"title": "Unique", "projectId": projet["id"]})

    store.delete_project(projet["id"], op_id="op-1")
    avant = len(_ops(chemin, "tasks"))
    store.delete_project(projet["id"], op_id="op-1")
    assert len(_ops(chemin, "tasks")) == avant


def test_un_projet_sans_tache_se_supprime_sans_bruit(tmp_path) -> None:
    chemin = tmp_path / "vide.db"
    store = SuccesWorkspaceStore(chemin)
    projet = store.create_project({"name": "Vide"})
    store.delete_project(projet["id"])
    assert _ops(chemin, "tasks") == []


class TestOrdreDeCreation:
    """L'ordre de création est l'ordre d'affichage — sans qu'on le demande.

    ``order_index`` restait à 0 pour toute tâche créée sans rang explicite, et
    le tri de la vue arbre (``ORDER BY order_index, id``) retombait sur l'id :
    des UUID, c'est-à-dire l'ordre du hasard. Constaté le 22 août 2026 : un
    parcours de cent quarante-huit cours créés dans l'ordre chronologique
    s'affichait battu comme un jeu de cartes. Les sous-tâches faisaient déjà
    MAX+1 ; les tâches, non.
    """

    def test_les_taches_prennent_la_suite_de_leurs_soeurs(self, tmp_path):
        store = SuccesWorkspaceStore(tmp_path / "ordre.db")
        projet = store.create_project({"name": "Parcours", "structure": "tree"})
        rangs = [
            store.create_task({"title": t, "projectId": projet["id"]})["order"]
            for t in ("Étape 1", "Étape 2", "Étape 3")
        ]
        assert rangs == [0, 1, 2], "l'ordre de création doit survivre au tri"

    def test_chaque_parent_compte_ses_propres_enfants(self, tmp_path):
        """Les rangs sont PAR fratrie : deux sous-arbres n'interfèrent pas."""
        store = SuccesWorkspaceStore(tmp_path / "fratries.db")
        projet = store.create_project({"name": "P", "structure": "tree"})
        a = store.create_task({"title": "A", "projectId": projet["id"]})
        b = store.create_task({"title": "B", "projectId": projet["id"]})
        a1 = store.create_task(
            {"title": "A1", "projectId": projet["id"], "parentTaskId": a["id"]}
        )
        b1 = store.create_task(
            {"title": "B1", "projectId": projet["id"], "parentTaskId": b["id"]}
        )
        assert (a1["order"], b1["order"]) == (0, 0)

    def test_un_rang_explicite_est_respecte(self, tmp_path):
        """Un client qui ordonne lui-même (import, synchro) garde la main."""
        store = SuccesWorkspaceStore(tmp_path / "explicite.db")
        projet = store.create_project({"name": "P"})
        t = store.create_task(
            {"title": "Rang imposé", "projectId": projet["id"], "order": 41}
        )
        assert t["order"] == 41

    def test_une_soeur_supprimee_ne_bloque_pas_la_suite(self, tmp_path):
        store = SuccesWorkspaceStore(tmp_path / "trou.db")
        projet = store.create_project({"name": "P"})
        premiere = store.create_task({"title": "Un", "projectId": projet["id"]})
        store.delete_task(premiere["id"])
        seconde = store.create_task({"title": "Deux", "projectId": projet["id"]})
        assert seconde["order"] >= 1, "le rang ne se réutilise pas, il avance"
