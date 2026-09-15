"""L'ordre manuel des notes et des projets — glisser pour ranger.

Demandé le 15 septembre 2026. Le patron des tâches/photos : une colonne
order_index, un nouvel élément à la FIN (MAX+1), un endpoint qui réécrit le
rang, et un tri qui le respecte. §100 — l'ordre affiché doit venir de la base,
pas d'un envoi optimiste.
"""

from __future__ import annotations

import pytest

from diapason.succes.continuity import SuccesContinuityStore


@pytest.fixture()
def db(tmp_path) -> SuccesContinuityStore:
    return SuccesContinuityStore(tmp_path / "succes.db")


class TestOrdreDesNotes:
    def test_une_note_neuve_va_a_la_fin(self, db) -> None:
        a = db.create_note({"title": "A"})
        b = db.create_note({"title": "B"})
        c = db.create_note({"title": "C"})
        assert [a["order"], b["order"], c["order"]] == [0, 1, 2]
        # list_notes rend l'ordre manuel, pas la récence.
        assert [n["title"] for n in db.list_notes()] == ["A", "B", "C"]

    def test_reordonner_reecrit_les_rangs_et_le_tri_suit(self, db) -> None:
        a = db.create_note({"title": "A"})
        b = db.create_note({"title": "B"})
        c = db.create_note({"title": "C"})
        db.reorder_notes([c["id"], a["id"], b["id"]])
        assert [n["title"] for n in db.list_notes()] == ["C", "A", "B"]
        assert db.get_note(c["id"])["order"] == 0
        assert db.get_note(b["id"])["order"] == 2

    def test_seules_les_notes_qui_bougent_sont_reecrites(self, db) -> None:
        a = db.create_note({"title": "A"})  # order 0
        b = db.create_note({"title": "B"})  # order 1
        avant = db.get_note(a["id"])["updatedAtMs"]
        # Même ordre : rien ne change, donc aucune écriture.
        assert db.reorder_notes([a["id"], b["id"]]) == []
        assert db.get_note(a["id"])["updatedAtMs"] == avant

    def test_un_id_inconnu_est_ignore_sans_lever(self, db) -> None:
        a = db.create_note({"title": "A"})
        assert db.reorder_notes(["fantome", a["id"]]) == []  # A reste à 0

    def test_l_ordre_survit_a_une_mise_a_jour_de_note(self, db) -> None:
        a = db.create_note({"title": "A"})
        b = db.create_note({"title": "B"})
        db.reorder_notes([b["id"], a["id"]])
        db.update_note(a["id"], {"title": "A modifiée"})
        # Le tri primaire est order_index : renommer ne remonte pas la note.
        assert [n["title"] for n in db.list_notes()] == ["B", "A modifiée"]


class TestOrdreDesProjets:
    def test_un_projet_neuf_va_a_la_fin_et_le_tri_suit(self, db) -> None:
        a = db.create_project({"name": "Alpha"})
        b = db.create_project({"name": "Bravo"})
        assert [a["order"], b["order"]] == [0, 1]
        assert [p["name"] for p in db.list_projects()] == ["Alpha", "Bravo"]

    def test_reordonner_les_projets(self, db) -> None:
        a = db.create_project({"name": "Alpha"})
        b = db.create_project({"name": "Bravo"})
        c = db.create_project({"name": "Charlie"})
        db.reorder_projects([c["id"], a["id"], b["id"]])
        assert [p["name"] for p in db.list_projects()] == ["Charlie", "Alpha", "Bravo"]

    def test_renommer_un_projet_ne_le_deplace_pas(self, db) -> None:
        a = db.create_project({"name": "Alpha"})
        db.create_project({"name": "Bravo"})
        db.update_project(a["id"], {"name": "Alpha 2"})
        # order_index prime sur updated_at_ms : l'ordre ne bouge pas.
        assert [p["name"] for p in db.list_projects()] == ["Alpha 2", "Bravo"]


def test_le_seed_de_migration_garde_l_ordre_visible(tmp_path) -> None:
    """Une base d'AVANT order_index : à l'ouverture, l'ordre récence est semé,
    pas remis à zéro — sinon l'ordre visible sauterait au premier lancement."""
    import sqlite3

    chemin = tmp_path / "vieux.db"
    # On fabrique la table sans order_index, deux projets, B plus récent que A.
    conn = sqlite3.connect(chemin)
    conn.executescript(
        """
        CREATE TABLE succes_projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            color TEXT DEFAULT '#000', icon TEXT DEFAULT '', start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '', created_date TEXT DEFAULT '',
            updated_at_ms INTEGER NOT NULL, deleted_at_ms INTEGER
        );
        INSERT INTO succes_projects(id,name,updated_at_ms) VALUES ('a','Ancien',100);
        INSERT INTO succes_projects(id,name,updated_at_ms) VALUES ('b','Recent',200);
        """
    )
    conn.commit()
    conn.close()
    db = SuccesContinuityStore(chemin)  # ouverture → migration + seed
    # Récent (updated_at_ms 200) d'abord, comme avant la migration.
    assert [p["name"] for p in db.list_projects()] == ["Recent", "Ancien"]
