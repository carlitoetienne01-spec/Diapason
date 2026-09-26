from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.vie.project_kits import list_project_kits
from diapason.vie.routes import monter, set_store_for_tests
from diapason.vie.store import VieError
from diapason.vie.workspace import VieWorkspaceStore


def test_list_project_kits_includes_builtins() -> None:
    kits = list_project_kits()
    ids = {kit["id"] for kit in kits}
    assert {"moving", "exams", "podcast-launch"} <= ids
    assert all(kit["nodeCount"] > 0 for kit in kits)


def test_task_tree_parent_and_description(tmp_path) -> None:
    store = VieWorkspaceStore(tmp_path / "tree.db")
    project = store.create_project({"name": "Arbre", "structure": "tree"})
    assert project["structure"] == "tree"
    root = store.create_task(
        {
            "title": "Phase 1",
            "notes": "Préparer le terrain",
            "projectId": project["id"],
        }
    )
    assert root["parentTaskId"] == ""
    assert root["notes"] == "Préparer le terrain"
    child = store.create_task(
        {
            "title": "Étape A",
            "notes": "Détail de A",
            "projectId": project["id"],
            "parentTaskId": root["id"],
        }
    )
    assert child["parentTaskId"] == root["id"]

    with pytest.raises(VieError, match="boucle|propre parent"):
        store.update_task(root["id"], {"parentTaskId": child["id"]})

    other = store.create_project({"name": "Autre"})
    with pytest.raises(VieError, match="même projet"):
        store.create_task(
            {
                "title": "Hors projet",
                "projectId": other["id"],
                "parentTaskId": root["id"],
            }
        )


def test_kit_materializes_task_tree(tmp_path) -> None:
    store = VieWorkspaceStore(tmp_path / "kit.db")
    project = store.create_project(
        {"name": "Mon déménagement", "kitId": "moving", "structure": "flat"}
    )
    assert project["structure"] == "tree"
    assert project["taskTotal"] > 5
    tasks = [task for task in store.list_tasks() if task["projectId"] == project["id"]]
    assert len(tasks) == project["taskTotal"]
    roots = [task for task in tasks if not task["parentTaskId"]]
    assert len(roots) == 3
    assert any(task["notes"] for task in tasks)


def test_project_kits_and_tree_api(tmp_path) -> None:
    store = VieWorkspaceStore(tmp_path / "api-tree.db")
    set_store_for_tests(store)
    app = FastAPI()
    monter(app)
    client = TestClient(app)

    kits = client.get("/v1/vie/project-kits")
    assert kits.status_code == 200
    assert kits.json()["count"] >= 3

    created = client.post(
        "/v1/vie/projects",
        json={"name": "Podcast perso", "kitId": "podcast-launch"},
    )
    assert created.status_code == 201
    project = created.json()["project"]
    assert project["structure"] == "tree"
    assert project["taskTotal"] > 0

    root = client.post(
        "/v1/vie/tasks",
        json={
            "title": "Idée bonus",
            "notes": "À creuser",
            "projectId": project["id"],
        },
    )
    assert root.status_code == 201
    root_task = root.json()["task"]
    child = client.post(
        "/v1/vie/tasks",
        json={
            "title": "Sous-idée",
            "projectId": project["id"],
            "parentTaskId": root_task["id"],
            "notes": "Description courte",
        },
    )
    assert child.status_code == 201
    assert child.json()["task"]["parentTaskId"] == root_task["id"]
    assert child.json()["task"]["notes"] == "Description courte"

    set_store_for_tests(None)
