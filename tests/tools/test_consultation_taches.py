"""§5/§100 — une semaine n'est pas un lundi, un total n'est pas une page."""

from datetime import date

import pytest

from diapason.tools.vie_tasks import VieTasksTool
from diapason.vie.periodes import plage_de_consultation
from diapason.vie.store import VieError, VieStore


class TestPeriodes:
    def test_une_annee_avec_ses_bornes_n_est_pas_contradictoire(self):
        """§100 : le modèle précisait year et ses deux dates exactes."""
        assert plage_de_consultation(
            periode="year", debut="2026-01-01", fin="2026-12-31"
        ) == ("2026-01-01", "2026-12-31"), "la précision redondante reste valide"
        with pytest.raises(VieError):
            plage_de_consultation(periode="year", debut="2026-02-01", fin="2026-12-31")

    @pytest.mark.parametrize(
        ("texte", "periode", "attendu"),
        [
            ("2026-09-30", "week", ("2026-09-28", "2026-10-04")),
            ("2024-02", "", ("2024-02-01", "2024-02-29")),
            ("2027", "", ("2027-01-01", "2027-12-31")),
            ("cette semaine", "", ("2026-09-21", "2026-09-27")),
            ("la semaine prochaine", "", ("2026-09-28", "2026-10-04")),
            ("aujourd'hui", "", ("2026-09-27", "2026-09-27")),
        ],
    )
    def test_les_bornes_sont_inclusives(self, texte, periode, attendu):
        """§100 : couvrir aussi le dimanche et le dernier jour du mois."""
        assert plage_de_consultation(texte, periode, now=date(2026, 9, 27)) == attendu

    def test_les_bornes_contradictoires_sont_refusees(self):
        """§34 : ne pas choisir silencieusement entre deux périodes."""
        with pytest.raises(VieError):
            plage_de_consultation(debut="2026-10-10", fin="2026-10-01")
        with pytest.raises(VieError):
            plage_de_consultation("demain", debut="2026-10-01", fin="2026-10-10")


class TestLectureTaches:
    def test_le_total_et_la_page_couvrent_toute_la_semaine(self, tmp_path):
        """§100 : les tâches hors période et supprimées ne gonflent pas le total."""
        magasin = VieStore(tmp_path / "vie.db")
        for i in range(14):
            magasin.create_task(
                {"title": f"Tâche {i}", "date": "2026-10-04", "done": i < 2}
            )
        for jour in ("2026-09-27", "2026-10-05", "", "2027-01-01"):
            magasin.create_task({"title": "Hors période", "date": jour})
        effacee = magasin.create_task({"title": "Effacée", "date": "2026-10-01"})
        magasin.delete_task(effacee["id"])
        outil = VieTasksTool(magasin)
        filtre = {"startDate": "2026-09-28", "endDate": "2026-10-04"}
        compte = outil.execute(action="count", **filtre)
        assert compte.success and compte.metadata["count"] == 14, (
            "total réel de la période"
        )
        assert compte.metadata["pendingCount"] == 12, "états calculés avant pagination"
        assert compte.metadata["tasks"] == [], (
            "compter ne recopie pas le contenu des tâches"
        )
        page = outil.execute(action="list", **filtre)
        suite = outil.execute(
            action="list", offset=page.metadata["nextOffset"], **filtre
        )
        ids = [t["id"] for r in (page, suite) for t in r.metadata["tasks"]]
        assert len(set(ids)) == len(ids) == 14, "pagination complète et sans doublon"
        assert suite.metadata["nextOffset"] is None, "la fin de liste est explicite"
        complet = outil.execute(action="read", task_id=ids[0])
        assert complet.success and "subtasks" in complet.metadata["task"], (
            "détails relisibles"
        )
        assert (
            outil.execute(action="count", status="completed", **filtre).metadata[
                "count"
            ]
            == 2
        )
