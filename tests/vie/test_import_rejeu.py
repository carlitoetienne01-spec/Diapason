"""Import, vie du Mac, redémarrage : rien de ce que le Mac a fait ne se perd.

26/09/2026, contre-épreuve de l'étape 2 de la phase 3
(docs/development/diapason-mobile.md). Le constructeur rejoue chaque import
archivé à chaque démarrage (``materialize_archived_snapshots``,
``materialize_continuity_archives``) : tout ce qui n'est pas idempotent ou
qui n'est pas borné une fois pour toutes s'y révèle, au redémarrage launchd
qui suit — bien après un import réussi.
"""

from __future__ import annotations

import sqlite3

from diapason.vie.store import now_ms
from diapason.vie.sync import VieSyncStore


def _une(magasin, sql: str, *params):
    with sqlite3.connect(magasin.db_path) as conn:
        return conn.execute(sql, params).fetchall()


_HABITUDE = {
    "id": "h1",
    "name": "Lire",
    "frequency": "daily",
    "startDate": "2026-09-01",
    "updatedAtMs": 1789891200000,
}


class TestLImportNEffacePasCeQueLeMacAAjoute:
    """§100 : la phrase dit « n'efface rien sur le Mac » ; c'était faux."""

    def test_une_sous_tache_ajoutee_sur_le_mac_survit_au_second_import(self, tmp_path):
        magasin = VieSyncStore(tmp_path / "vie.db")
        tache = {
            "id": "t1",
            "title": "Arroser",
            "updatedAtMs": 1789891200000,
            "subtasks": [
                {"id": "s1", "title": "Remplir", "updatedAtMs": 1789891200000}
            ],
        }
        magasin.import_legacy_snapshot({"todos": [tache]})
        magasin.add_subtask("t1", "Acheter du terreau")

        resume = magasin.import_legacy_snapshot(
            {
                "todos": [
                    {**tache, "title": "Arroser le balcon", "updatedAtMs": now_ms()}
                ]
            }
        )

        assert resume["tasksImported"] == 1
        vivantes = _une(
            magasin,
            "SELECT title FROM vie_subtasks WHERE task_id='t1' "
            "AND deleted_at_ms IS NULL ORDER BY title",
        )
        assert vivantes == [("Acheter du terreau",), ("Remplir",)], (
            f"la sous-tâche du Mac a été effacée par l'import : {vivantes}"
        )

    def test_un_titre_de_sous_tache_raccourci_ou_trop_profond_se_compte(self, tmp_path):
        magasin = VieSyncStore(tmp_path / "vie.db")
        feuille: dict = {"id": "profonde", "title": "Au fond"}
        for niveau in range(24, 0, -1):
            feuille = {
                "id": f"n{niveau}",
                "title": f"Niveau {niveau}",
                "children": [feuille],
            }

        resume = magasin.import_legacy_snapshot(
            {
                "todos": [
                    {
                        "id": "t1",
                        "title": "Arroser",
                        "subtasks": [
                            {"id": "s1", "title": "x" * 300},
                            {"title": "Sans identifiant"},
                            feuille,
                        ],
                    }
                ]
            }
        )

        assert resume["truncated"] == {"subtasks": {"title": 1}}, (
            "un titre de sous-tâche coupé à 200 caractères doit se compter"
        )
        assert resume["skipped"]["subtasks"] == {"invalide": 1, "tropProfond": 1}, (
            "une sous-tâche sans identifiant et le 25e niveau ne disparaissent "
            "pas sans un mot"
        )


class TestLeRejeuAuDemarrageNEcrasePasLeMac:
    """Le rejeu tourne à CHAQUE démarrage : il doit rendre la même chose que
    l'import, pas mieux, pas plus."""

    def test_un_horodatage_en_avance_n_ecrase_pas_une_modification_du_mac(
        self, tmp_path
    ):
        """Borné à « maintenant + 5 min » recalculé à chaque rejeu, un
        horodatage de deux jours en avance gagnait contre le Mac au
        redémarrage suivant."""
        magasin = VieSyncStore(tmp_path / "vie.db")
        demain = now_ms() + 2 * 86_400_000
        magasin.import_legacy_snapshot(
            {
                "habits": [_HABITUDE],
                "notes": [
                    {"id": "n1", "title": "Semis", "content": "", "updatedAtMs": demain}
                ],
                "habitLogs": {"h1_2026-09-22": True},
                "habitLogsAt": {"h1_2026-09-22": demain},
            }
        )
        magasin.update_note("n1", {"title": "Revu sur le Mac"})
        magasin.set_habit_done("h1", "2026-09-22", False)

        VieSyncStore(magasin.db_path)

        assert _une(magasin, "SELECT title FROM vie_notes WHERE id='n1'") == [
            ("Revu sur le Mac",)
        ], "la note modifiée sur le Mac après l'import doit survivre au rejeu"
        assert _une(
            magasin, "SELECT done FROM vie_habit_logs WHERE log_date='2026-09-22'"
        ) == [(0,)], "la décoche faite sur le Mac doit survivre au rejeu"

    def test_un_modele_et_une_citation_sans_identifiant_ne_se_multiplient_pas(
        self, tmp_path
    ):
        magasin = VieSyncStore(tmp_path / "vie.db")
        resume = magasin.import_legacy_snapshot(
            {
                "todoTemplates": [
                    {
                        "title": "Compost",
                        "frequency": "daily",
                        "startDate": "2026-09-01",
                        "endDate": "2026-12-31",
                    }
                ],
                "quotes": [{"text": "Un peu chaque jour.", "author": "Anonyme"}],
            }
        )

        for _ in range(3):
            VieSyncStore(magasin.db_path)

        assert resume["templatesImported"] == 1 and resume["quotesImported"] == 1
        assert _une(magasin, "SELECT COUNT(*) FROM vie_task_templates") == [(1,)], (
            "un modèle sans identifiant était recréé à chaque démarrage"
        )
        assert _une(magasin, "SELECT COUNT(*) FROM vie_quotes") == [(1,)], (
            "une citation sans identifiant était recréée à chaque démarrage"
        )

    def test_une_coche_retiree_par_la_synchronisation_ne_revient_pas(self, tmp_path):
        """``_apply_delete`` EFFACE la ligne et pose une pierre tombale ;
        sans ligne, rien ne s'opposait au rejeu."""
        magasin = VieSyncStore(tmp_path / "vie.db")
        magasin.import_legacy_snapshot(
            {"habits": [_HABITUDE], "habitLogs": {"h1_2026-09-20": True}}
        )
        with magasin._transaction() as conn:
            magasin._apply_delete(conn, "habit_logs", "h1_2026-09-20", now_ms(), "op-1")

        VieSyncStore(magasin.db_path)

        assert _une(magasin, "SELECT * FROM vie_habit_logs") == [], (
            "la coche retirée par la synchronisation est revenue au démarrage"
        )

    def test_la_coche_d_une_habitude_de_modele_entre_des_le_premier_import(
        self, tmp_path
    ):
        """Les coches passaient avant la couche qui crée l'habitude d'un
        modèle : « habitude absente du Mac », puis présente au redémarrage."""
        magasin = VieSyncStore(tmp_path / "vie.db")

        resume = magasin.import_legacy_snapshot(
            {
                "todoTemplates": [
                    {
                        "id": "m1",
                        "title": "Méditer",
                        "frequency": "daily",
                        "startDate": "2026-09-01",
                        "endDate": "2026-12-31",
                        "templateKind": "habit",
                    }
                ],
                "habitLogs": {"template-habit-m1_2026-09-20": True},
            }
        )

        assert "habitLogs" not in resume.get("skipped", {}), resume.get("skipped")
        assert resume["habitLogsImported"] == 1
        assert _une(magasin, "SELECT habit_id, done FROM vie_habit_logs") == [
            ("template-habit-m1", 1)
        ]
