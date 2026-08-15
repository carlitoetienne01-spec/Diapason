from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.server.auth_middleware import AuthMiddleware
from diapason.succes.routes import router, set_store_for_tests
from diapason.succes.store import SuccesError
from diapason.succes.sync import SuccesSyncStore


def store(tmp_path, name: str) -> SuccesSyncStore:
    return SuccesSyncStore(tmp_path / f"{name}.db")


def authorize_peer(db: SuccesSyncStore, name: str = "iPhone") -> dict:
    invitation = db.create_pairing(name)
    return db.redeem_pairing(invitation["pairingToken"])


def test_pairing_is_one_time_hashed_and_revocable(tmp_path) -> None:
    db = store(tmp_path, "pairing")
    invitation = db.create_pairing("iPhone personnel")

    with sqlite3.connect(db.db_path) as conn:
        stored = conn.execute(
            "SELECT token_hash FROM succes_sync_pairings"
        ).fetchone()[0]
    assert invitation["pairingToken"] not in stored
    assert len(stored) == 64

    peer = db.redeem_pairing(invitation["pairingToken"])
    assert peer["syncToken"].startswith("diapason_sync_")
    assert db.verify_sync_token(peer["syncToken"]) is True
    with pytest.raises(SuccesError, match="déjà utilisé"):
        db.redeem_pairing(invitation["pairingToken"])

    assert db.revoke_peer(peer["peerId"]) is True
    assert db.verify_sync_token(peer["syncToken"]) is False


def test_exchange_replicates_offline_task_and_is_idempotent(tmp_path) -> None:
    source = store(tmp_path, "source")
    target = store(tmp_path, "target")
    peer = authorize_peer(target, "Mac secondaire")
    task = source.create_task(
        {
            "id": "lesson",
            "title": "Préparer la séance",
            "date": "2026-08-18",
            "updatedAtMs": 1,
        }
    )
    source.add_subtask(task["id"], "Créer les exercices")
    operations = source.list_operations()["operations"]

    first = target.exchange(peer["peerId"], after=0, operations=operations)
    replicated = target.get_task("lesson")
    assert replicated["title"] == "Préparer la séance"
    assert replicated["subtasks"][0]["title"] == "Créer les exercices"
    assert first["received"] == {"applied": 2, "stale": 0, "duplicate": 0}

    second = target.exchange(peer["peerId"], after=0, operations=operations)
    assert second["received"] == {"applied": 0, "stale": 0, "duplicate": 2}
    assert target.sync_status()["peerCount"] == 1


def test_lww_tombstone_prevents_older_update_from_resurrecting_task(tmp_path) -> None:
    source = store(tmp_path, "delete-source")
    target = store(tmp_path, "delete-target")
    peer = authorize_peer(target)
    source.create_task(
        {"id": "gone", "title": "À supprimer", "updatedAtMs": 2_000}
    )
    source.delete_task("gone")
    operations = source.list_operations()["operations"]

    # Receiving out of order must still converge on the newest delete.
    result = target.exchange(
        peer["peerId"], after=0, operations=list(reversed(operations))
    )
    assert result["received"]["applied"] == 1
    assert result["received"]["stale"] == 1
    assert target.list_tasks() == []


def test_sync_routes_expose_diagnostics_and_local_exchange(tmp_path) -> None:
    db = store(tmp_path, "routes")
    set_store_for_tests(db)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        status = client.get("/v1/succes/sync/status")
        assert status.status_code == 200
        assert status.json()["transport"] == "loopback_only"

        invitation = client.post(
            "/v1/succes/sync/pairings", json={"deviceName": "Android test"}
        )
        assert invitation.status_code == 200
        paired = client.post(
            "/v1/succes/sync/pair",
            json={"pairingToken": invitation.json()["pairingToken"]},
        )
        assert paired.status_code == 200

        exchange = client.post(
            "/v1/succes/sync/exchange",
            json={
                "peerToken": paired.json()["syncToken"],
                "cursor": 0,
                "operations": [],
            },
        )
        assert exchange.status_code == 200
        assert exchange.json()["received"]["applied"] == 0
    finally:
        set_store_for_tests(None)


def test_peer_token_cannot_bypass_the_local_api_boundary(tmp_path) -> None:
    db = store(tmp_path, "auth-boundary")
    peer = authorize_peer(db)
    set_store_for_tests(db)
    app = FastAPI()
    app.include_router(router)
    local_key = "local-key-that-is-long-enough-for-this-test"
    app.add_middleware(AuthMiddleware, api_key=local_key)
    client = TestClient(app)
    try:
        rejected = client.post(
            "/v1/succes/sync/exchange",
            headers={"Authorization": f"Bearer {peer['syncToken']}"},
            json={"peerToken": peer["syncToken"], "cursor": 0, "operations": []},
        )
        assert rejected.status_code == 401

        accepted = client.post(
            "/v1/succes/sync/exchange",
            headers={"Authorization": f"Bearer {local_key}"},
            json={"peerToken": peer["syncToken"], "cursor": 0, "operations": []},
        )
        assert accepted.status_code == 200
    finally:
        set_store_for_tests(None)
