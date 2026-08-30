from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.succes.routes import router, set_store_for_tests
from diapason.succes.store import SuccesError, SuccesStore
from diapason.succes.workspace import NOTE_CONTENT_MAX, SuccesWorkspaceStore
from diapason.tools.succes_workspace import (
    SuccesDeleteItemTool,
    SuccesWorkspaceTool,
)


def test_projects_derive_progress_from_linked_tasks(tmp_path) -> None:
    store = SuccesWorkspaceStore(tmp_path / "workspace.db")
    project = store.create_project(
        {
            "name": "Lancer Succès",
            "description": "Transplantation dans Diapason",
            "startDate": "2026-08-14",
            "endDate": "2026-09-01",
        }
    )
    task = store.create_task({"title": "Valider le plan", "projectId": project["id"]})

    assert store.get_project(project["id"])["taskTotal"] == 1
    store.set_task_done(task["id"], True)
    assert store.get_project(project["id"])["taskCompleted"] == 1


def test_habit_logs_keep_false_values_and_compute_streak(tmp_path) -> None:
    store = SuccesWorkspaceStore(tmp_path / "habits.db")
    habit = store.create_habit(
        {
            "name": "Lire vingt minutes",
            "frequency": "daily",
            "startDate": "2026-08-12",
        }
    )
    store.set_habit_done(habit["id"], "2026-08-13", True)
    today = store.set_habit_done(habit["id"], "2026-08-14", True)
    assert today["done"] is True
    assert today["streak"] == 2

    reopened = store.set_habit_done(habit["id"], "2026-08-14", False)
    assert reopened["done"] is False
    with sqlite3.connect(store.db_path) as conn:
        value = conn.execute(
            "SELECT done FROM succes_habit_logs WHERE habit_id=? AND log_date=?",
            (habit["id"], "2026-08-14"),
        ).fetchone()[0]
    assert value == 0


def test_habit_logs_can_be_listed_for_a_date_span(tmp_path) -> None:
    store = SuccesWorkspaceStore(tmp_path / "habit-logs.db")
    habit = store.create_habit(
        {"name": "Eau", "frequency": "daily", "startDate": "2026-01-01"}
    )
    other = store.create_habit(
        {"name": "Marche", "frequency": "daily", "startDate": "2026-01-01"}
    )
    store.set_habit_done(habit["id"], "2026-03-01", True)
    store.set_habit_done(habit["id"], "2026-03-02", True)
    store.set_habit_done(habit["id"], "2026-03-02", False)
    store.set_habit_done(other["id"], "2026-03-01", True)
    store.set_habit_done(habit["id"], "2026-04-01", True)

    logs = store.list_habit_logs(from_date="2026-03-01", to_date="2026-03-31")
    assert logs == {
        f"{habit['id']}_2026-03-01": True,
        f"{other['id']}_2026-03-01": True,
    }
    scoped = store.list_habit_logs(
        from_date="2026-03-01", to_date="2026-03-31", habit_id=habit["id"]
    )
    assert scoped == {f"{habit['id']}_2026-03-01": True}


def test_weekly_habit_due_days_are_deterministic(tmp_path) -> None:
    store = SuccesWorkspaceStore(tmp_path / "weekly.db")
    habit = store.create_habit(
        {
            "name": "Cours du vendredi",
            "frequency": "weekly",
            "weeklyDays": [5],
            "startDate": "2026-08-01",
        }
    )
    assert store.get_habit(habit["id"], on_date="2026-08-14")["due"] is True
    assert store.get_habit(habit["id"], on_date="2026-08-15")["due"] is False


def test_notes_support_page_formats_and_fonts(tmp_path) -> None:
    store = SuccesWorkspaceStore(tmp_path / "rich-notes.db")
    note = store.create_note(
        {
            "title": "Carnet",
            "content": "<p><strong>Bonjour</strong></p>",
            "pageFormat": "letter",
            "pageBackground": "lined",
            "fontFamily": "Merriweather",
            "docLang": "ht",
        }
    )
    assert note["pageFormat"] == "letter"
    assert note["pageBackground"] == "lined"
    assert note["fontFamily"] == "Merriweather"
    assert note["docLang"] == "ht"
    updated = store.update_note(
        note["id"], {"pageFormat": "reading", "fontFamily": "Inter"}
    )
    assert updated["pageFormat"] == "reading"
    assert updated["fontFamily"] == "Inter"


def test_une_note_riche_passe_le_plafond_de_cent_mille(tmp_path) -> None:
    """§5 — 29 août 2026 : un guide HTML se faisait refuser à 100 000."""
    store = SuccesWorkspaceStore(tmp_path / "long-note.db")
    content = "<p>" + ("mot " * 40_000) + "</p>"
    assert len(content) > 100_000
    assert len(content) < NOTE_CONTENT_MAX
    note = store.create_note({"title": "Guide", "content": content})
    assert note["content"] == content
    try:
        store.create_note({"title": "Trop", "content": "x" * (NOTE_CONTENT_MAX + 1)})
    except SuccesError as error:
        assert "1 000 000" in str(error), "le plafond doit rester lisible en français"
    else:
        raise AssertionError("une note au-delà du plafond doit être refusée")


def test_notes_are_versioned_and_deleted_with_tombstones(tmp_path) -> None:
    store = SuccesWorkspaceStore(tmp_path / "notes.db")
    note = store.create_note({"title": "Idée", "content": "Première version"})
    changed = store.update_note(note["id"], {"content": "Deuxième version"})
    assert changed["content"] == "Deuxième version"

    store.delete_note(note["id"])
    assert store.list_notes() == []
    operations = store.list_operations()["operations"]
    assert [item["kind"] for item in operations] == ["upsert", "upsert", "delete"]


def test_phase_two_materializes_snapshots_archived_by_phase_one(tmp_path) -> None:
    path = tmp_path / "migration.db"
    phase_one = SuccesStore(path)
    phase_one.import_legacy_snapshot(
        {
            "state": {
                "todos": [],
                "projects": [],
                "habits": [
                    {
                        "id": "habit-old",
                        "name": "Méditer",
                        "frequency": "daily",
                        "startDate": "2026-08-10",
                        "updatedAtMs": 100,
                    }
                ],
                "habitLogs": {"habit-old_2026-08-13": True},
                "habitLogsAt": {"habit-old_2026-08-13": 101},
                "notes": [
                    {
                        "id": "note-old",
                        "title": "Note historique",
                        "content": "Conservée par la phase 1",
                        "updatedAtMs": 102,
                    }
                ],
            }
        }
    )

    phase_two = SuccesWorkspaceStore(path)
    assert phase_two.get_habit("habit-old", on_date="2026-08-13")["done"] is True
    assert phase_two.get_note("note-old")["content"] == "Conservée par la phase 1"


def test_workspace_api_project_habit_note_lifecycle(tmp_path) -> None:
    store = SuccesWorkspaceStore(tmp_path / "workspace-api.db")
    set_store_for_tests(store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    today = date.today().isoformat()
    try:
        project = client.post(
            "/v1/succes/projects", json={"name": "Application Diapason"}
        )
        assert project.status_code == 201

        habit = client.post(
            "/v1/succes/habits",
            json={"name": "Planifier la journée", "frequency": "daily"},
        )
        assert habit.status_code == 201
        habit_id = habit.json()["habit"]["id"]
        logged = client.post(
            f"/v1/succes/habits/{habit_id}/log",
            json={"date": today, "done": True},
        )
        assert logged.json()["habit"]["done"] is True

        note = client.post(
            "/v1/succes/notes", json={"title": "Décision", "content": "Local"}
        )
        assert note.status_code == 201
        note_id = note.json()["note"]["id"]
        refused = client.request(
            "DELETE", f"/v1/succes/notes/{note_id}", json={"confirmed": False}
        )
        assert refused.status_code == 409

        dashboard = client.get(f"/v1/succes/dashboard?date={today}")
        assert dashboard.status_code == 200
        assert dashboard.json()["projects"] == 1
        assert dashboard.json()["habits"] == {"due": 1, "completed": 1}
        assert dashboard.json()["notes"] == 1
    finally:
        set_store_for_tests(None)


def test_dia_workspace_tool_separates_routine_and_sensitive_actions(tmp_path) -> None:
    from diapason.core.types import ToolCall
    from diapason.tools._stubs import ToolExecutor

    store = SuccesWorkspaceStore(tmp_path / "dia-workspace.db")
    routine = SuccesWorkspaceTool(store)
    created = routine.execute(
        action="create_note", title="À retenir", content="Donnée locale"
    )
    forbidden = routine.execute(action="delete", item_id="unknown")
    assert created.success is True
    assert forbidden.success is False
    note_id = created.metadata["note"]["id"]

    sensitive = SuccesDeleteItemTool(store)
    call = ToolCall(
        id="delete-note",
        name="succes_delete_item",
        arguments=f'{{"entity":"note","item_id":"{note_id}"}}',
    )
    denied = ToolExecutor(
        [sensitive], interactive=True, confirm_callback=lambda _prompt: False
    ).execute(call)
    assert denied.success is False
    assert store.get_note(note_id)["title"] == "À retenir"

    approved = ToolExecutor(
        [sensitive], interactive=True, confirm_callback=lambda _prompt: True
    ).execute(call)
    assert approved.success is True
    assert store.list_notes() == []


def test_voice_exposes_routine_workspace_but_not_sensitive_delete() -> None:
    from diapason.speech.realtime.tools import list_voice_tool_ids

    tool_ids = list_voice_tool_ids()
    assert "succes_workspace" in tool_ids
    assert "succes_delete_item" not in tool_ids


class TestLesTroisAxesDeMiseEnPage:
    """« Mise en page » de Word a trois menus ; nous en avions un seul.

    30 août 2026. « A4 » est un papier, « Marges minimales » un réglage de
    marges, « A4 paysage » une orientation — tout cela dans une même liste.
    On ne pouvait donc ni mettre une A5 en paysage, ni savoir sur quel papier
    « marges minimales » s'appliquait. Ces tests tiennent la séparation, et
    surtout la compatibilité : une note écrite avant ne doit pas changer
    d'allure en silence.
    """

    def test_une_note_heritee_se_relit_dans_les_trois_axes(self, tmp_path) -> None:
        store = SuccesWorkspaceStore(tmp_path / "notes.db")
        note = store.create_note({"title": "Ancienne", "pageFormat": "wide"})

        assert note["pageSize"] == "a4"
        assert note["pageOrientation"] == "paysage", (
            "« A4 paysage » était une ORIENTATION déguisée en format : la "
            "perdre remettrait la note en portrait sans prévenir"
        )
        assert note["pageMargins"] == "normales"

    def test_marges_minimales_rouvre_en_etroites_pas_en_normales(
        self, tmp_path
    ) -> None:
        store = SuccesWorkspaceStore(tmp_path / "notes.db")
        note = store.create_note({"title": "Dense", "pageFormat": "full"})
        assert note["pageMargins"] == "etroites"

    def test_page_etroite_etait_un_papier_executive(self, tmp_path) -> None:
        store = SuccesWorkspaceStore(tmp_path / "notes.db")
        note = store.create_note({"title": "Étroite", "pageFormat": "narrow"})
        assert note["pageSize"] == "executive"
        assert note["pageMargins"] == "moderees"

    def test_les_trois_axes_neufs_sont_acceptes_et_relus(self, tmp_path) -> None:
        store = SuccesWorkspaceStore(tmp_path / "notes.db")
        note = store.create_note(
            {
                "title": "Neuve",
                "pageSize": "legal",
                "pageOrientation": "paysage",
                "pageMargins": "larges",
            }
        )
        relue = store.get_note(note["id"])
        assert (relue["pageSize"], relue["pageOrientation"], relue["pageMargins"]) == (
            "legal",
            "paysage",
            "larges",
        )

    def test_une_a5_peut_enfin_etre_en_paysage(self, tmp_path) -> None:
        """Ce que l'ancienne liste rendait littéralement impossible."""
        store = SuccesWorkspaceStore(tmp_path / "notes.db")
        note = store.create_note(
            {"title": "A5 couchée", "pageSize": "a5", "pageOrientation": "paysage"}
        )
        assert (note["pageSize"], note["pageOrientation"]) == ("a5", "paysage")

    def test_un_papier_inconnu_est_refuse(self, tmp_path) -> None:
        store = SuccesWorkspaceStore(tmp_path / "notes.db")
        for champ, valeur in (
            ("pageSize", "papyrus"),
            ("pageOrientation", "diagonale"),
            ("pageMargins", "aucune"),
        ):
            try:
                store.create_note({"title": "x", champ: valeur})
            except SuccesError:
                continue
            raise AssertionError(f"{champ}={valeur} aurait dû être refusé")

    def test_la_mise_en_page_survit_a_une_modification(self, tmp_path) -> None:
        store = SuccesWorkspaceStore(tmp_path / "notes.db")
        note = store.create_note(
            {"title": "Suivi", "pageSize": "a5", "pageMargins": "larges"}
        )
        modifiee = store.update_note(note["id"], {"content": "<p>texte</p>"})
        assert (modifiee["pageSize"], modifiee["pageMargins"]) == ("a5", "larges"), (
            "une simple frappe ne doit pas ramener la note à A4 marges normales"
        )


def test_une_base_ancienne_est_remplie_a_l_ouverture(tmp_path) -> None:
    """La migration doit REMPLIR, pas laisser deviner.

    `ALTER TABLE` donne à chaque note existante le défaut des colonnes neuves.
    Sans remplissage, « jamais renseigné » devient indiscernable de « choisi
    exprès » : une note héritée « A4 paysage » qu'on remettrait ensuite en
    portrait serait éternellement rendue en paysage par une lecture qui
    préfère la valeur non-défaut. C'est le piège que ce test ferme.
    """
    chemin = tmp_path / "ancienne.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(
        """
        CREATE TABLE succes_notes (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            deleted_at_ms INTEGER,
            page_format TEXT NOT NULL DEFAULT 'a4',
            page_background TEXT NOT NULL DEFAULT 'default',
            font_family TEXT NOT NULL DEFAULT 'Special Elite',
            doc_lang TEXT NOT NULL DEFAULT 'fr',
            color TEXT NOT NULL DEFAULT '#6366f1'
        );
        """
    )
    for note_id, page_format in (
        ("n-wide", "wide"),
        ("n-full", "full"),
        ("n-narrow", "narrow"),
        ("n-reading", "reading"),
    ):
        conn.execute(
            """INSERT INTO succes_notes
               (id,title,content,created_at,updated_at,updated_at_ms,page_format)
               VALUES (?,?,'',?,?,?,?)""",
            (note_id, note_id, "2026-08-01", "2026-08-01", 1, page_format),
        )
    conn.commit()
    conn.close()

    store = SuccesWorkspaceStore(chemin)

    assert store.get_note("n-wide")["pageOrientation"] == "paysage"
    assert store.get_note("n-full")["pageMargins"] == "etroites"
    assert store.get_note("n-narrow")["pageSize"] == "executive"
    assert store.get_note("n-reading")["pageMargins"] == "larges"

    # Et les colonnes portent VRAIMENT ces valeurs — ce n'est pas la lecture
    # qui les recalcule à chaque fois.
    verif = sqlite3.connect(chemin)
    ligne = verif.execute(
        "SELECT page_size,page_orientation,page_margins"
        " FROM succes_notes WHERE id='n-narrow'"
    ).fetchone()
    verif.close()
    assert ligne == ("executive", "portrait", "moderees"), (
        "la migration doit écrire dans les colonnes, sinon un changement "
        "ultérieur ne pourra jamais contredire la valeur héritée"
    )
