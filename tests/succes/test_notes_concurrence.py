"""§100 : ajouter un dessin ne doit pas écraser une écriture concurrente."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.store import SuccesError, SuccesNoteConflict


def test_les_ajouts_sont_atomiques_et_le_rejeu_n_ajoute_pas_deux_fois(tmp_path):
    a = SuccesContinuityStore(tmp_path / "notes.db")
    b = SuccesContinuityStore(tmp_path / "notes.db")
    note = a.create_note({"title": "Travail", "content": "Début"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = [
            pool.submit(
                store.update_note, note["id"], {"appendContent": texte}, op_id=cle
            )
            for store, texte, cle in [
                (a, "<p>A</p>", "ajout-a"),
                (b, "<p>B</p>", "ajout-b"),
            ]
        ]
        for resultat in resultats:
            resultat.result()
    a.update_note(note["id"], {"appendContent": "<p>A</p>"}, op_id="ajout-a")
    texte = a.get_note(note["id"])["content"]
    assert texte.count("<p>A</p>") == texte.count("<p>B</p>") == 1, (
        "chaque ajout survit exactement une fois"
    )
    assert texte.startswith("Début"), "le texte initial reste intact"


def test_un_editeur_ouvert_avant_le_dessin_ne_peut_pas_l_effacer(tmp_path):
    db = SuccesContinuityStore(tmp_path / "notes.db")
    lu = db.create_note({"title": "Cours", "content": "Ancien texte"})
    nouveau = db.update_note(lu["id"], {"appendContent": "<p>Dessin</p>"})
    with pytest.raises(SuccesNoteConflict):
        db.update_note(
            lu["id"],
            {"content": "Brouillon périmé", "expectedContentHash": lu["contentHash"]},
        )
    assert db.get_note(lu["id"])["content"] == nouveau["content"], (
        "aucune perte sur conflit"
    )
    db.update_note(lu["id"], {"category": "Étude"})
    sauvee = db.update_note(
        lu["id"],
        {"content": "Texte et dessin", "expectedContentHash": nouveau["contentHash"]},
    )
    assert sauvee["category"] == "Étude", (
        "un changement de métadonnée ne périme pas le texte"
    )


def test_on_ne_peut_pas_ajouter_et_remplacer_dans_le_meme_patch(tmp_path):
    db = SuccesContinuityStore(tmp_path / "notes.db")
    note = db.create_note({"title": "Cours", "content": "Initial"})
    with pytest.raises(SuccesError):
        db.update_note(note["id"], {"content": "A", "appendContent": "B"})
    assert db.get_note(note["id"])["content"] == "Initial", (
        "l'écriture entière doit être annulée"
    )


def test_le_conflit_http_est_explicite_et_le_rejeu_reste_idempotent(
    monkeypatch, tmp_path
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diapason.succes import routes

    db = SuccesContinuityStore(tmp_path / "http.db")
    monkeypatch.setattr(routes, "_store", db)
    app = FastAPI()
    app.include_router(routes.router)
    c = TestClient(app)
    note = c.post(
        "/v1/succes/notes", json={"title": "Cours", "content": "Initial"}
    ).json()["note"]
    url = f"/v1/succes/notes/{note['id']}"
    ajout = {"appendContent": "<p>Dessin</p>", "opId": "dessin-unique"}
    assert c.patch(url, json=ajout).status_code == 200
    assert c.patch(url, json=ajout).status_code == 200
    conflit = c.patch(
        url, json={"content": "Périmé", "expectedContentHash": note["contentHash"]}
    )
    assert conflit.status_code == 409
    assert conflit.json()["detail"]["code"] == "note_conflict", (
        "le client doit reconnaître le conflit"
    )
    assert c.get(url).json()["note"]["content"] == "Initial<p>Dessin</p>"
