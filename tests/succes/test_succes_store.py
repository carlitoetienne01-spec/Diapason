from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from diapason.succes.dates import resolve_date_expression
from diapason.succes.store import SuccesError, SuccesStore
from diapason.tools.succes_tasks import SuccesDeleteTaskTool, SuccesTasksTool


@pytest.fixture()
def store(tmp_path):
    return SuccesStore(tmp_path / "succes.db")


def test_task_and_nested_subtasks_are_transactional(store: SuccesStore) -> None:
    task = store.create_task(
        {"title": "Préparer la présentation", "date": "2026-08-14", "priority": "high"}
    )
    assert task["done"] is False
    assert task["date"] == "2026-08-14"

    task = store.add_subtask(task["id"], "Écrire le plan")
    root_id = task["subtasks"][0]["id"]
    task = store.add_subtask(task["id"], "Ajouter les exemples", parent_id=root_id)
    child_id = task["subtasks"][0]["children"][0]["id"]

    task = store.set_subtask_done(task["id"], child_id, True)
    assert task["subtasks"][0]["done"] is True
    assert task["done"] is True
    assert task["completedDate"] == date.today().isoformat()


def test_parent_cannot_be_completed_before_subtasks(store: SuccesStore) -> None:
    task = store.create_task({"title": "Tâche avec contrôle"})
    task = store.add_subtask(task["id"], "Étape obligatoire")
    with pytest.raises(SuccesError, match="Validez d'abord"):
        store.set_task_done(task["id"], True)


def test_delete_is_a_tombstone_and_operation_cursor_advances(
    store: SuccesStore,
) -> None:
    task = store.create_task({"title": "À supprimer"})
    store.delete_task(task["id"])
    assert store.list_tasks() == []
    operations = store.list_operations()
    assert [op["kind"] for op in operations["operations"]] == ["upsert", "delete"]
    assert operations["operations"][-1]["payload"]["deletedAtMs"] > 0
    assert operations["cursor"] == 2


def test_legacy_import_is_idempotent_and_archives_full_snapshot(
    store: SuccesStore,
) -> None:
    snapshot = {
        "rev": 7,
        "state": {
            "todos": [
                {
                    "id": "legacy-1",
                    "title": "Tâche historique",
                    "date": "2026-04-12",
                    "priority": "high",
                    "updatedAtMs": 123,
                    "subtasks": [
                        {"id": "legacy-sub", "title": "Sous-tâche", "done": False}
                    ],
                }
            ],
            "projects": [
                {"id": "project-1", "name": "Projet historique", "updatedAtMs": 124}
            ],
            "habits": [{"id": "habit-preserved", "name": "Lecture"}],
        },
    }
    first = store.import_legacy_snapshot(snapshot)
    second = store.import_legacy_snapshot(snapshot)
    assert first["tasksImported"] == 1
    assert first["projectsImported"] == 1
    assert second["alreadyImported"] is True
    assert store.get_task("legacy-1")["subtasks"][0]["id"] == "legacy-sub"

    with sqlite3.connect(store.db_path) as conn:
        archived = json.loads(
            conn.execute("SELECT snapshot_json FROM succes_imports").fetchone()[0]
        )
    assert archived["state"]["habits"][0]["id"] == "habit-preserved"


def test_sync_status_never_claims_remote_success(store: SuccesStore) -> None:
    status = store.sync_status()
    assert status["mode"] == "local_only"
    assert status["configured"] is False
    assert "pas encore configurée" in status["message"]


def test_operation_id_is_exactly_once_and_bound_to_parameters(
    store: SuccesStore,
) -> None:
    first = store.create_task({"title": "Réserver la salle"}, op_id="request-42")
    replay = store.create_task({"title": "Réserver la salle"}, op_id="request-42")
    assert replay["id"] == first["id"]
    assert len(store.list_tasks()) == 1
    assert store.list_operations()["cursor"] == 1

    with pytest.raises(SuccesError, match="d'autres paramètres"):
        store.create_task({"title": "Changer la demande"}, op_id="request-42")


def test_date_resolver_refuses_ambiguous_next_weekday() -> None:
    result = resolve_date_expression("vendredi prochain", now=date(2026, 8, 13))
    assert result.status == "ambiguous"
    assert result.options == ("2026-08-14", "2026-08-21")


def test_dia_tool_has_no_delete_action_and_no_false_success(store: SuccesStore) -> None:
    tool = SuccesTasksTool(store)
    missing = tool.execute(action="complete", task_id="missing")
    forbidden = tool.execute(action="delete", task_id="anything")
    created = tool.execute(action="create", title="Appeler le client", date="demain")
    assert missing.success is False
    assert missing.metadata["persistence"] == "unchanged"
    assert forbidden.success is False
    assert created.success is True
    assert created.metadata["persistence"] == "local"


def test_dia_voice_registry_exposes_succes_tasks() -> None:
    from diapason.speech.realtime.tools import list_voice_tool_ids

    assert "succes_tasks" in list_voice_tool_ids()
    assert "succes_delete_task" not in list_voice_tool_ids()


def test_sensitive_dia_delete_requires_native_confirmation(store: SuccesStore) -> None:
    from diapason.core.types import ToolCall
    from diapason.tools._stubs import ToolExecutor

    task = store.create_task({"title": "Ne pas supprimer sans accord"})
    tool = SuccesDeleteTaskTool(store)
    call = ToolCall(
        id="delete-1",
        name="succes_delete_task",
        arguments=json.dumps({"task_id": task["id"]}),
    )
    denied = ToolExecutor(
        [tool], interactive=True, confirm_callback=lambda _prompt: False
    ).execute(call)
    assert denied.success is False
    assert store.get_task(task["id"])["title"] == task["title"]

    approved = ToolExecutor(
        [tool], interactive=True, confirm_callback=lambda _prompt: True
    ).execute(call)
    assert approved.success is True
    assert store.list_tasks() == []
