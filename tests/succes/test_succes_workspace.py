from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.succes.routes import router, set_store_for_tests
from diapason.succes.store import SuccesStore
from diapason.succes.workspace import SuccesWorkspaceStore
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
            json={"date": "2026-08-14", "done": True},
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

        dashboard = client.get("/v1/succes/dashboard?date=2026-08-14")
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
