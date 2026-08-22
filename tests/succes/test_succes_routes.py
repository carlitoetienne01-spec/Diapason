from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.succes.routes import router, set_store_for_tests
from diapason.succes.store import SuccesStore


def test_local_api_create_plan_complete_and_confirm_delete(tmp_path) -> None:
    store = SuccesStore(tmp_path / "api-succes.db")
    set_store_for_tests(store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        created = client.post(
            "/v1/succes/tasks",
            json={
                "title": "Préparer le cours",
                "date": "2026-08-14",
                "priority": "high",
            },
        )
        assert created.status_code == 201
        task = created.json()["task"]
        assert created.json()["persistence"] == "local"

        planner = client.get("/v1/succes/planner?date=2026-08-14")
        assert planner.status_code == 200
        assert planner.json()["summary"] == {
            "total": 1,
            "completed": 0,
            "open": 1,
        }

        completed = client.post(
            f"/v1/succes/tasks/{task['id']}/done", json={"done": True}
        )
        assert completed.status_code == 200
        assert completed.json()["task"]["done"] is True

        refused = client.request(
            "DELETE",
            f"/v1/succes/tasks/{task['id']}",
            json={"confirmed": False},
        )
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "confirmation_required"

        deleted = client.request(
            "DELETE",
            f"/v1/succes/tasks/{task['id']}",
            json={"confirmed": True},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
    finally:
        set_store_for_tests(None)


def test_api_refuses_ambiguous_date_without_writing(tmp_path) -> None:
    store = SuccesStore(tmp_path / "ambiguous-succes.db")
    set_store_for_tests(store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        response = client.post(
            "/v1/succes/tasks",
            json={"title": "Tâche ambiguë", "date": "vendredi prochain"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "ambiguous_date"
        assert store.list_tasks() == []
    finally:
        set_store_for_tests(None)


def test_finance_transaction_create_accepts_json_body(tmp_path) -> None:
    from diapason.succes.sync import SuccesSyncStore

    store = SuccesSyncStore(tmp_path / "finance-api.db")
    set_store_for_tests(store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        accounts = client.get("/v1/succes/finances/accounts").json()["accounts"]
        categories = client.get("/v1/succes/finances/categories").json()["categories"]
        rent = next(cat for cat in categories if "Loyer" in cat["name"])
        created = client.post(
            "/v1/succes/finances/transactions",
            json={
                "accountId": accounts[0]["id"],
                "type": "expense",
                "amount": 1590,
                "date": "2026-09-01",
                "categoryId": rent["id"],
                "payee": "Nobel Appartement",
                "notes": "Loyer = 1570$ / Internet = 20$",
            },
        )
        assert created.status_code == 201, created.text
        txn = created.json()["transaction"]
        assert txn["amount"] == 1590
        assert txn["payee"] == "Nobel Appartement"
        assert txn["date"] == "2026-09-01"
    finally:
        set_store_for_tests(None)
