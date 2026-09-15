"""Les catégories de notes et le rattachement d'une note à un projet.

Demandés le 15 septembre 2026 : « classer les notes par catégorie, le nom en
haut, un trait qui sépare » et « rattacher une ou des notes à un projet ».
§5 — une catégorie n'est pas un état à entretenir : elle existe tant qu'une
note vivante la porte, et l'ordre seul est mémorisé.
"""

from __future__ import annotations

import pytest

from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.store import SuccesError


@pytest.fixture()
def db(tmp_path) -> SuccesContinuityStore:
    return SuccesContinuityStore(tmp_path / "succes.db")


def _note(db, titre: str, **extra) -> dict:
    return db.create_note({"title": titre, **extra})


class TestCategoriesDeNotes:
    def test_une_categorie_existe_tant_qu_une_note_la_porte(self, db) -> None:
        note = _note(db, "Recette", category="Cuisine")
        assert note["category"] == "Cuisine"
        assert db.list_note_categories() == ["Cuisine"]
        db.delete_note(note["id"])
        assert db.list_note_categories() == [], (
            "la dernière note partie, la catégorie disparaît d'elle-même"
        )

    def test_l_ordre_choisi_est_memorise_et_les_nouvelles_vont_a_la_fin(
        self, db
    ) -> None:
        _note(db, "A", category="Alpha")
        _note(db, "B", category="Bravo")
        _note(db, "C", category="Charlie")
        db.order_note_categories(["Charlie", "Alpha", "Bravo"])
        assert db.list_note_categories() == ["Charlie", "Alpha", "Bravo"]
        # Une catégorie apparue APRÈS le classement (import, synchronisation)
        # se range à la fin, sans casser l'ordre voulu.
        _note(db, "D", category="Delta")
        _note(db, "E", category="Aaa")
        attendu = ["Charlie", "Alpha", "Bravo", "Aaa", "Delta"]
        assert db.list_note_categories() == attendu

    def test_renommer_deplace_toutes_les_notes_et_l_ordre(self, db) -> None:
        _note(db, "Un", category="Ecole")
        _note(db, "Deux", category="Ecole")
        db.order_note_categories(["Ecole"])
        assert db.rename_note_category("Ecole", "La Cité") == 2
        assert db.list_note_categories() == ["La Cité"]
        assert all(n["category"] == "La Cité" for n in db.list_notes())

    def test_dissoudre_rend_les_notes_sans_categorie_sans_les_supprimer(
        self, db
    ) -> None:
        _note(db, "Un", category="Brouillon")
        assert db.rename_note_category("Brouillon", "") == 1
        assert db.list_note_categories() == []
        notes = db.list_notes()
        assert len(notes) == 1 and notes[0]["category"] == "", (
            "dissoudre ne supprime rien"
        )

    def test_le_patch_sans_champ_categorie_n_y_touche_pas(self, db) -> None:
        note = _note(db, "Stable", category="Garde")
        db.update_note(note["id"], {"title": "Stable 2"})
        assert db.get_note(note["id"])["category"] == "Garde", (
            "un patch muet sur la catégorie doit la laisser telle quelle"
        )
        db.update_note(note["id"], {"category": ""})
        assert db.get_note(note["id"])["category"] == "", (
            "la chaîne vide, elle, veut dire « retirer »"
        )


class TestNoteRattacheeAUnProjet:
    def test_le_lien_se_pose_et_le_projet_inexistant_est_refuse(self, db) -> None:
        projet = db.create_project({"name": "La Cité"})
        note = _note(db, "Immigration", projectId=projet["id"])
        assert note["projectId"] == projet["id"]
        with pytest.raises(SuccesError):
            _note(db, "Perdue", projectId="proj_fantome")

    def test_supprimer_le_projet_libere_la_note_sans_la_supprimer(self, db) -> None:
        projet = db.create_project({"name": "Éphémère"})
        note = _note(db, "Survit", projectId=projet["id"])
        db.delete_project(projet["id"])
        apres = db.get_note(note["id"])
        assert apres["projectId"] == "", "la note redevient « sans projet »"
        assert apres["title"] == "Survit", "et n'est jamais supprimée"
