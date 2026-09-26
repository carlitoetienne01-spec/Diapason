"""L'import de la sauvegarde Life OS, éprouvé sur ce que le téléphone écrit VRAIMENT.

26/09/2026, étape 2 de la phase 3 (docs/development/diapason-mobile.md).
L'import ne lisait les coches d'habitude que dans ``habitLogsAt`` : les
coches antérieures à l'horodatage des bascules, qui n'existent que dans
``habitLogs``, ne franchissaient pas l'import — 2 sur 3 sur la copie de dev.
Une note sans titre était sautée sans être comptée, et le résumé disait
« importé ».

L'instantané n'est PAS écrit ici : il sort du vrai ``LifeOsState.toJson()``
du dépôt mobile (``test/import/instantane_life_os_test.dart``), qui le
vérifie de son côté. Un instantané écrit à la main par Python aurait porté
l'idée que Python se fait du format — celle qui avait laissé passer le
défaut. Même chemin, même règle que les vecteurs canoniques : hors CI, un
dépôt mobile absent est un ÉCHEC, pas un saut.
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.vie.routes import monter, set_store_for_tests
from diapason.vie.sync import VieSyncStore

MOBILE = pathlib.Path.home() / "Projets/diapason_mobile"
INSTANTANE = MOBILE / "test/import/instantane_life_os.json"

_HABITUDE = "habitude-lecture"
_CINQ_REGLAGES = {
    "settings.theme",
    "settings.colorTheme",
    "settings.todosViewMode",
    "settings.bilanFutureExtraYears",
    "settings.bilanHorizonLastYear",
}


def _en_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _instantane() -> dict:
    """L'instantané du dépôt mobile — ou un échec qui le dit."""
    try:
        return json.loads(INSTANTANE.read_text(encoding="utf-8"))
    except OSError:
        if _en_ci():
            pytest.skip(f"{INSTANTANE} absent du runner de CI")
        pytest.fail(
            f"{INSTANTANE} introuvable ou illisible. Le dépôt mobile doit vivre "
            f"dans {MOBILE} ; hors CI, son absence n'est pas un saut : c'est "
            "l'import qui n'est plus éprouvé sur le format réel."
        )


def _coches(chemin: pathlib.Path) -> dict[str, tuple[int, int]]:
    with sqlite3.connect(chemin) as conn:
        lignes = conn.execute(
            "SELECT log_date, done, updated_at_ms FROM vie_habit_logs "
            "WHERE habit_id=? ORDER BY log_date",
            (_HABITUDE,),
        ).fetchall()
    return {jour: (fait, ts) for jour, fait, ts in lignes}


@pytest.fixture
def magasin(tmp_path: pathlib.Path) -> VieSyncStore:
    return VieSyncStore(tmp_path / "vie.db")


class TestLImportNePerdPlusDeCochesNiDeNotesSansLeDire:
    """§5 et §100 : ce qui n'entre pas est compté, par motif, et nommé."""

    def test_trois_coches_dont_une_horodatee_donnent_trois_lignes(self, magasin):
        """Le défaut exact : seules les coches de ``habitLogsAt`` entraient."""
        resume = magasin.import_legacy_snapshot(_instantane())

        coches = _coches(magasin.db_path)
        assert sorted(coches) == ["2026-09-20", "2026-09-21", "2026-09-22"], (
            f"les trois coches doivent devenir trois lignes, pas {sorted(coches)}"
        )
        assert all(fait == 1 for fait, _ in coches.values()), "les trois sont faites"
        assert resume["habitLogsImported"] == 3
        assert resume["habitLogsWithoutTimestamp"] == 2, (
            "deux coches n'avaient pas d'horodatage : le résumé doit le dire"
        )
        assert coches["2026-09-22"][1] == 1790062200000, (
            "la coche horodatée garde SON horodatage, pas celui de repli"
        )

    def test_un_second_import_rend_already_imported_avec_le_resume_entier(
        self, magasin
    ):
        """La ligne archivée gardait tâches et projets seulement : le second
        import répondait « déjà importé » avec un résumé amputé."""
        premier = magasin.import_legacy_snapshot(_instantane())
        second = magasin.import_legacy_snapshot(_instantane())

        assert premier["alreadyImported"] is False
        assert second["alreadyImported"] is True
        assert {k: v for k, v in second.items() if k != "alreadyImported"} == {
            k: v for k, v in premier.items() if k != "alreadyImported"
        }, "le second import doit rendre le résumé du premier, en entier"
        assert len(_coches(magasin.db_path)) == 3, "aucune ligne en double"

    def test_la_note_sans_titre_figure_au_resume_avec_son_motif(self, magasin):
        resume = magasin.import_legacy_snapshot(_instantane())

        assert resume["notesImported"] == 1
        assert resume["skipped"]["notes"] == {"titreVide": 1}
        (note,) = [e for e in resume["skippedItems"] if e["kind"] == "notes"]
        assert note["id"] == "note-sans-titre"
        assert note["reason"] == "titreVide"
        assert note["label"].startswith("Une pensée notée dans le bus"), (
            "une note sans titre se reconnaît à son début, sans balises"
        )

    def test_chaque_saut_porte_son_motif(self, magasin):
        """Un titre trop long n'est pas « invalide », et une habitude refusée
        n'est pas absente : l'utilisateur ne les corrige pas pareil."""
        resume = magasin.import_legacy_snapshot(_instantane())

        assert resume["tasksImported"] == 1
        assert resume["skipped"]["tasks"] == {"tropLong": 1}
        assert resume["habitsImported"] == 1
        assert resume["skipped"]["habits"] == {"invalide": 1}
        assert resume["projectsImported"] == 1
        assert resume["templatesImported"] == 1
        assert resume["quotesImported"] == 1
        assert set(resume["skipped"]) == {"tasks", "habits", "notes"}, (
            f"aucun autre saut attendu : {resume['skipped']}"
        )

    def test_les_cles_ignorees_sont_nommees_avec_leur_raison(self, magasin):
        resume = magasin.import_legacy_snapshot(_instantane())
        ignorees = {c["key"]: c for c in resume["ignoredKeys"]}

        assert _CINQ_REGLAGES <= set(ignorees), (
            "les cinq réglages du site sont ignorés, mais NOMMÉS"
        )
        assert all(
            ignorees[k]["reason"] == "reglageSansEquivalent" for k in _CINQ_REGLAGES
        )
        for cle in ("activeNoteId", "notesView", "notesEditorId", "selectedDate"):
            assert ignorees[cle]["reason"] == "etatInterface", cle
        assert ignorees["sync.deletes"]["reason"] == "suppressionsNonRejouees"
        assert ignorees["sync.deletes"]["count"] == 1, (
            "une suppression faite sur le téléphone n'efface rien ici : le "
            "résumé doit dire combien"
        )
        importees = {"todos", "projects", "habits", "habitLogs", "habitLogsAt"}
        assert not importees & set(ignorees), "une clé importée n'est pas ignorée"

    def test_le_rejeu_au_demarrage_ne_rajeunit_pas_une_coche_sans_horodatage(
        self, magasin
    ):
        """Le constructeur rejoue chaque import archivé. Un repli sur
        ``now_ms()`` aurait rajeuni la coche à chaque démarrage, et écrasé
        une décoche faite depuis sur le Mac."""
        magasin.import_legacy_snapshot(_instantane())
        magasin.set_habit_done(_HABITUDE, "2026-09-20", False)

        rouvert = VieSyncStore(magasin.db_path)

        assert _coches(rouvert.db_path)["2026-09-20"][0] == 0, (
            "la décoche faite sur le Mac après l'import doit survivre au rejeu"
        )

    def test_une_version_plus_recente_sur_le_mac_gagne_et_se_compte(self, magasin):
        instantane = _instantane()
        with sqlite3.connect(magasin.db_path) as conn:
            conn.execute(
                "INSERT INTO vie_notes (id,title,content,created_at,updated_at,"
                "updated_at_ms) VALUES (?,?,?,?,?,?)",
                ("note-semis", "Semis revus", "<p>Revu</p>", "", "", 1790999999000),
            )

        resume = magasin.import_legacy_snapshot(instantane)

        assert resume["skipped"]["notes"] == {
            "titreVide": 1,
            "plusRecentSurLeMac": 1,
        }
        assert magasin.get_note("note-semis")["title"] == "Semis revus"

    def test_la_route_rend_une_phrase_tiree_du_resume(self, magasin):
        """La phrase était fixe (« importées sans écraser … ») même quand des
        éléments avaient été sautés. Elle vient désormais du résumé (§100)."""
        app = FastAPI()
        monter(app)
        set_store_for_tests(magasin)
        try:
            reponse = TestClient(app).post(
                "/v1/vie/import/legacy", json={"snapshot": _instantane()}
            )
        finally:
            set_store_for_tests(None)

        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["summary"]["habitLogsImported"] == 3
        message = corps["message"]
        assert "3 coches d'habitude" in message, message
        assert "1 note (sans titre)" in message, message
        assert "1 tâche (trop long)" in message, message
        assert "1 suppression faite ailleurs n'efface rien" in message, message
