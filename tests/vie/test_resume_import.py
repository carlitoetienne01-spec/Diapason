"""Le résumé d'import compte ce qui n'entre pas, sans qu'une couche efface l'autre.

26/09/2026, étape 2 de la phase 3 (docs/development/diapason-mobile.md).
Le cas réel — l'instantané écrit par le Dart — est éprouvé dans
tests/contract/test_import_life_os.py ; ici, les cas qu'aucune sauvegarde
du téléphone ne porte.
"""

from __future__ import annotations

from diapason.vie.resume_import import Sauts, cles_ignorees, fusionner, libelle, phrase
from diapason.vie.store import VieStore


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
