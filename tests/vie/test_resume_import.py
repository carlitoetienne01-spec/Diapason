"""Le résumé d'import compte ce qui n'entre pas, sans qu'une couche efface l'autre.

26/09/2026, étape 2 de la phase 3 (docs/development/diapason-mobile.md).
Le cas réel — l'instantané écrit par le Dart — est éprouvé dans
tests/contract/test_import_life_os.py ; ici, les cas qu'aucune sauvegarde
du téléphone ne porte.
"""

from __future__ import annotations

import sqlite3

from diapason.vie.resume_import import Sauts, cles_ignorees, fusionner, libelle, phrase
from diapason.vie.store import VieStore
from diapason.vie.sync import VieSyncStore


class TestLeResumeNEffacePasUneCoucheParLAutre:
    """§5 : un saut qui n'apparaît pas au résumé est un saut caché."""

    def test_les_sauts_de_deux_couches_s_additionnent(self):
        """Un ``{**a, **b}`` remplaçait les tâches sautées par les notes sautées."""
        a, b = Sauts(), Sauts()
        a.noter("tasks", "titreVide", "t1")
        b.noter("notes", "titreVide", "n1")
        b.noter("notes", "titreVide", "n2")

        total = fusionner({"tasksImported": 1}, a.resume(), b.resume())

        assert total["skipped"] == {
            "tasks": {"titreVide": 1},
            "notes": {"titreVide": 2},
        }, "les deux couches doivent survivre à la fusion"
        assert [e["id"] for e in total["skippedItems"]] == ["t1", "n1", "n2"]
        assert total["tasksImported"] == 1

    def test_une_note_sans_titre_se_reconnait_a_son_debut_sans_balises(self):
        assert libelle("", "<p>Une <b>idée</b></p>") == "Une idée"
        assert len(libelle("x" * 500)) == 60, "le libellé ne recopie pas la note"

    def test_une_sauvegarde_enveloppee_nomme_aussi_son_enveloppe(self):
        ignorees = cles_ignorees({"rev": 7, "state": {"todos": [], "zzz": 1}})
        assert {"key": "rev", "reason": "enveloppe"} in ignorees
        assert {"key": "zzz", "reason": "cleInconnue"} in ignorees
        assert all(c["key"] != "todos" for c in ignorees), "todos est importée"


class TestLaPhraseDitCeQuiAEuLieu:
    """§100 : la phrase vient du résumé du récepteur, pas de l'envoi."""

    def test_rien_d_importe_ne_se_dit_pas_importe(self):
        assert phrase({"tasksImported": 0}).startswith("Rien n'a été importé")

    def test_un_second_import_dit_que_rien_n_a_change(self):
        assert "rien n'a changé" in phrase({"alreadyImported": True})

    def test_les_champs_raccourcis_sont_annonces(self):
        texte = phrase({"tasksImported": 1, "truncated": {"tasks": {"notes": 2}}})
        assert "2 champs raccourcis" in texte, texte


class TestUnProjetTropLongNeFaitPlusTomberLImport:
    """Un nom de projet de 201 caractères levait hors de tout ``try`` : tout
    l'import tombait en 400 pour un seul projet."""

    def test_le_projet_est_saute_et_le_reste_importe(self, tmp_path):
        magasin = VieStore(tmp_path / "vie.db")

        resume = magasin.import_legacy_snapshot(
            {
                "projects": [
                    {"id": "p-long", "name": "p" * 201},
                    {"id": "p-bon", "name": "Jardin"},
                ],
                "todos": [
                    {"id": "t1", "title": "Semer", "notes": "n" * 2500},
                ],
            }
        )

        assert resume["projectsImported"] == 1
        assert resume["skipped"]["projects"] == {"tropLong": 1}
        assert resume["tasksImported"] == 1
        assert resume["truncated"] == {"tasks": {"notes": 1}}, (
            "des notes de tâche raccourcies à 2 000 caractères doivent se compter"
        )
        assert len(magasin.get_task("t1")["notes"]) == 2000


def _fait(magasin, habitude: str, jour: str) -> int | None:
    with sqlite3.connect(magasin.db_path) as conn:
        ligne = conn.execute(
            "SELECT done FROM vie_habit_logs WHERE habit_id=? AND log_date=?",
            (habitude, jour),
        ).fetchone()
    return None if ligne is None else int(ligne[0])


def _operations_de_taches(magasin) -> int:
    with sqlite3.connect(magasin.db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM vie_operations WHERE entity='tasks'"
        ).fetchone()[0]


def _habitude(ident: str, **champs) -> dict:
    return {
        "id": ident,
        "name": "Lire",
        "frequency": "daily",
        "startDate": "2026-09-01",
        "updatedAtMs": 1789891200000,
        **champs,
    }


class TestChaqueMotifDeSautEstEprouve:
    """§5 : les motifs ajoutés au plan le 26/09/2026 (``habitudeAbsente``,
    ``dejaSurLeMac``) et ceux du plan (``plusRecentSurLeMac`` pour une
    coche, ``titreVide`` pour une habitude) n'avaient aucun rouge qui les
    garde : chacun pouvait devenir faux sans qu'un test le voie."""

    def test_la_coche_d_une_habitude_refusee_se_dit_habitude_absente(self, tmp_path):
        magasin = VieSyncStore(tmp_path / "vie.db")

        resume = magasin.import_legacy_snapshot(
            {
                "habits": [_habitude("h-hebdo", frequency="weekly")],
                "habitLogs": {"h-hebdo_2026-09-20": True},
            }
        )

        assert resume["skipped"]["habits"] == {"invalide": 1}
        assert resume["skipped"]["habitLogs"] == {"habitudeAbsente": 1}, (
            "la coche d'une habitude que le Mac a refusée doit le dire"
        )

    def test_une_coche_plus_recente_sur_le_mac_gagne_et_se_compte(self, tmp_path):
        magasin = VieSyncStore(tmp_path / "vie.db")
        magasin.import_legacy_snapshot({"habits": [_habitude("h1")]})
        magasin.set_habit_done("h1", "2026-09-20", False)

        resume = magasin.import_legacy_snapshot(
            {
                "habits": [_habitude("h1")],
                "habitLogs": {"h1_2026-09-20": True},
                "habitLogsAt": {"h1_2026-09-20": 1789900000000},
            }
        )

        assert resume["skipped"]["habitLogs"] == {"plusRecentSurLeMac": 1}
        assert _fait(magasin, "h1", "2026-09-20") == 0, (
            "la décoche faite sur le Mac, plus récente, doit rester"
        )

    def test_un_modele_et_une_citation_deja_presents_meme_supprimes(self, tmp_path):
        magasin = VieSyncStore(tmp_path / "vie.db")
        modele = {
            "id": "m1",
            "title": "Compost",
            "frequency": "daily",
            "startDate": "2026-09-01",
            "endDate": "2026-12-31",
        }
        citation = {"id": "c1", "text": "Un peu chaque jour."}
        magasin.import_legacy_snapshot(
            {"todoTemplates": [modele], "quotes": [citation]}
        )
        magasin.delete_template("m1")
        magasin.delete_quote("c1")

        resume = magasin.import_legacy_snapshot(
            {"todoTemplates": [modele], "quotes": [citation], "rev": 2}
        )

        assert resume["skipped"]["templates"] == {"dejaSurLeMac": 1}
        assert resume["skipped"]["quotes"] == {"dejaSurLeMac": 1}, (
            "supprimé sur le Mac veut dire présent : ni recréé, ni « invalide »"
        )

    def test_une_habitude_sans_nom_se_dit_sans_titre(self, tmp_path):
        magasin = VieSyncStore(tmp_path / "vie.db")

        resume = magasin.import_legacy_snapshot({"habits": [_habitude("h1", name="")]})

        assert resume["skipped"]["habits"] == {"titreVide": 1}


class TestLesDoublonsEtLesIdentiquesNeSeComptentPasFaux:
    """§100 : le compte d'importés égale le nombre de lignes, et un motif
    dit vrai."""

    def test_deux_notes_de_meme_identifiant_font_une_ligne_et_un_doublon(
        self, tmp_path
    ):
        magasin = VieSyncStore(tmp_path / "vie.db")
        note = {"title": "Semis", "content": "<p>x</p>"}

        resume = magasin.import_legacy_snapshot(
            {
                "notes": [
                    {**note, "id": "n1", "updatedAtMs": 1},
                    {**note, "id": "n1", "title": "Semis revus", "updatedAtMs": 2},
                    {**note, "id": "n2", "updatedAtMs": 5},
                    {**note, "id": "n2", "updatedAtMs": 5},
                ],
                "todos": [{"id": "t1", "title": "A"}, {"id": "t1", "title": "A"}],
            }
        )

        assert resume["notesImported"] == 2, "deux lignes, pas trois"
        assert resume["tasksImported"] == 1, "une ligne, pas deux"
        assert resume["skipped"]["notes"] == {"enDouble": 2}
        assert resume["skipped"]["tasks"] == {"enDouble": 1}
        assert magasin.get_note("n1")["title"] == "Semis revus", (
            "le doublon le plus récent gagne"
        )

    def test_un_second_import_a_peine_change_dit_deja_sur_le_mac(self, tmp_path):
        magasin = VieSyncStore(tmp_path / "vie.db")
        sauvegarde = {
            "todos": [{"id": "t1", "title": "Semer", "updatedAtMs": 1789891200000}],
            "habits": [_habitude("h1")],
            "habitLogs": {"h1_2026-09-20": True},
        }
        magasin.import_legacy_snapshot(sauvegarde)
        operations = _operations_de_taches(magasin)

        resume = magasin.import_legacy_snapshot({**sauvegarde, "selectedDate": "x"})

        assert resume["tasksImported"] == 0, "une tâche inchangée n'est pas réimportée"
        assert resume["skipped"]["tasks"] == {"dejaSurLeMac": 1}
        assert resume["skipped"]["habits"] == {"dejaSurLeMac": 1}
        assert resume["skipped"]["habitLogs"] == {"dejaSurLeMac": 1}, (
            "à horodatage égal, rien n'est « plus récent sur le Mac »"
        )
        assert _operations_de_taches(magasin) == operations, (
            "un réimport inchangé n'émet aucune opération de synchronisation"
        )


class TestLaPhraseSAccorde:
    def test_deux_suppressions_n_effacent_rien(self):
        texte = phrase(
            {
                "ignoredKeys": [
                    {
                        "key": "sync.deletes",
                        "reason": "suppressionsNonRejouees",
                        "count": 2,
                    }
                ]
            }
        )
        assert "2 suppressions faites ailleurs n'effacent rien" in texte, texte

    def test_une_suppression_n_efface_rien(self):
        texte = phrase(
            {
                "ignoredKeys": [
                    {
                        "key": "sync.deletes",
                        "reason": "suppressionsNonRejouees",
                        "count": 1,
                    }
                ]
            }
        )
        assert "1 suppression faite ailleurs n'efface rien" in texte, texte

    def test_les_decoches_sont_nommees_a_part(self):
        texte = phrase({"habitLogsImported": 1, "habitLogUnchecksImported": 3})
        assert "1 coche d'habitude, 3 décoches d'habitude" in texte, texte
