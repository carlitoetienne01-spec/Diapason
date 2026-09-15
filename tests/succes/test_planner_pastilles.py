"""Les pastilles du petit calendrier du Planificateur.

§5 et §100 — un point sans tâches, ou des tâches sans point, est un
mensonge. Constaté le 13 septembre 2026 : le calendrier peignait ses points
depuis les tâches déjà en base, si bien qu'une récurrence non matérialisée
n'avait pas de point puis en gagnait un après qu'on avait visité le jour, et
qu'une tâche en retard posait un point qu'aucune vue ne savait expliquer.
"""

from __future__ import annotations

import pytest

from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.store import SuccesError


@pytest.fixture()
def db(tmp_path) -> SuccesContinuityStore:
    return SuccesContinuityStore(tmp_path / "succes.db")


class TestPastillesPlanner:
    def test_les_taches_planifiees_comptent_sur_leur_jour(self, db) -> None:
        """Ouvertes et terminées se comptent sur la date PLANIFIÉE."""
        db.create_task({"title": "Ouverte", "date": "2026-09-10"})
        faite = db.create_task({"title": "Faite", "date": "2026-09-10"})
        db.set_task_done(faite["id"], True)
        db.create_task({"title": "Ailleurs", "date": "2026-09-20"})

        jours = db.pastilles_planner("2026-09-08", "2026-09-14")["days"]
        assert jours["2026-09-10"] == {"open": 1, "done": 1}, (
            "le 10 porte une ouverte et une terminée"
        )
        assert "2026-09-20" not in jours, "hors période : rien"

    def test_une_tache_sans_date_terminee_appartient_au_jour_de_fin(self, db) -> None:
        """Sans date planifiée, c'est le jour d'achèvement qui la porte."""
        t = db.create_task({"title": "Sans date"})
        db.set_task_done(t["id"], True)
        jour = db.get_task(t["id"])["completedDate"]
        assert jour, "set_task_done doit poser completedDate"
        jours = db.pastilles_planner(jour, jour)["days"]
        assert jours[jour]["done"] == 1, "terminée sans date : point du jour de fin"

    def test_une_recurrence_non_materialisee_compte_comme_ouverte(self, db) -> None:
        """Le point existe AVANT la visite du jour — c'était tout le défaut."""
        db.create_template(
            {
                "title": "Sport",
                "frequency": "daily",
                "startDate": "2026-09-01",
                "endDate": "2026-12-31",
                "templateKind": "task",
            }
        )
        jours = db.pastilles_planner("2026-10-05", "2026-10-07")["days"]
        assert jours["2026-10-05"]["open"] == 1, (
            "l'occurrence projetée doit poser un point ouvert"
        )
        assert jours["2026-10-06"]["open"] == 1
        # Et rien n'a été créé : la projection est en lecture seule.
        assert db.list_tasks(scheduled_date="2026-10-05") == [], (
            "les pastilles ne doivent pas matérialiser"
        )

    def test_une_occurrence_materialisee_ne_compte_pas_deux_fois(self, db) -> None:
        db.create_template(
            {
                "title": "Sport",
                "frequency": "daily",
                "startDate": "2026-09-01",
                "endDate": "2026-12-31",
                "templateKind": "task",
            }
        )
        db.materialize_templates("2026-10-05", "2026-10-05")
        jours = db.pastilles_planner("2026-10-05", "2026-10-05")["days"]
        assert jours["2026-10-05"]["open"] == 1, (
            "matérialisée + projetée = UNE tâche, pas deux"
        )

    def test_une_tache_supprimee_ne_pose_pas_de_point(self, db) -> None:
        t = db.create_task({"title": "Effacée", "date": "2026-09-10"})
        db.delete_task(t["id"])
        jours = db.pastilles_planner("2026-09-10", "2026-09-10")["days"]
        assert "2026-09-10" not in jours, "une tâche supprimée ne laisse rien"

    def test_la_periode_est_bornee_et_ordonnee(self, db) -> None:
        with pytest.raises(SuccesError):
            db.pastilles_planner("2026-09-10", "2026-09-01")
        with pytest.raises(SuccesError):
            db.pastilles_planner("2026-01-01", "2026-12-31")
