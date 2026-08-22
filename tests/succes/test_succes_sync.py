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
        stored = conn.execute("SELECT token_hash FROM succes_sync_pairings").fetchone()[
            0
        ]
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
    source.create_task({"id": "gone", "title": "À supprimer", "updatedAtMs": 2_000})
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
        assert status.json()["role"] == "ready"

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


def test_peer_token_cannot_access_general_api_but_exchange_is_token_auth(
    tmp_path,
) -> None:
    db = store(tmp_path, "auth-boundary")
    peer = authorize_peer(db)
    set_store_for_tests(db)
    app = FastAPI()
    app.include_router(router)
    local_key = "local-key-that-is-long-enough-for-this-test"
    app.add_middleware(AuthMiddleware, api_key=local_key)
    client = TestClient(app)
    try:
        rejected = client.get(
            "/v1/succes/sync/status",
            headers={"Authorization": f"Bearer {peer['syncToken']}"},
        )
        assert rejected.status_code == 401

        accepted = client.post(
            "/v1/succes/sync/exchange",
            json={"peerToken": peer["syncToken"], "cursor": 0, "operations": []},
        )
        assert accepted.status_code == 200

        with_key = client.get(
            "/v1/succes/sync/status",
            headers={"Authorization": f"Bearer {local_key}"},
        )
        assert with_key.status_code == 200
    finally:
        set_store_for_tests(None)


def test_guest_join_and_exchange_through_http_relay(tmp_path) -> None:
    host = store(tmp_path, "host")
    guest = store(tmp_path, "guest")
    set_store_for_tests(host)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        invitation = host.create_pairing("Mac secondaire")
        host.create_task(
            {
                "id": "shared",
                "title": "Depuis l'hôte",
                "date": "2026-08-18",
                "updatedAtMs": 10,
            }
        )
        guest.create_task(
            {
                "id": "guest-only",
                "title": "Depuis l'invité",
                "date": "2026-08-19",
                "updatedAtMs": 20,
            }
        )

        # Point guest at the in-process host via ASGI transport.
        guest.set_relay_url("http://testserver")
        from diapason.succes import sync as sync_mod

        original_post = sync_mod.relay_post

        def _asgi_post(base_url: str, path: str, payload: dict):
            assert base_url.rstrip("/") == "http://testserver"
            response = client.post(path, json=payload)
            if response.status_code >= 400:
                detail = response.json().get("detail") if response.content else ""
                raise SuccesError(str(detail) or f"HTTP {response.status_code}")
            return response.json()

        sync_mod.relay_post = _asgi_post  # type: ignore[assignment]
        try:
            joined = guest.join_remote(invitation["pairingToken"], device_name="Invité")
            assert joined["role"] == "guest"
            assert joined["transport"] == "https_relay"
            assert joined["guest"]["peerId"]

            result = guest.run_exchange()
            assert result["pulled"] >= 1
            assert result["pushed"] >= 1
            assert guest.get_task("shared")["title"] == "Depuis l'hôte"
            assert host.get_task("guest-only")["title"] == "Depuis l'invité"
        finally:
            sync_mod.relay_post = original_post  # type: ignore[assignment]
    finally:
        set_store_for_tests(None)


def test_normalize_relay_url_rejects_credentials_and_metadata() -> None:
    from diapason.succes.relay import normalize_relay_url

    assert normalize_relay_url("https://sync.example.com/diapason/") == (
        "https://sync.example.com/diapason"
    )
    with pytest.raises(SuccesError, match="identifiants"):
        normalize_relay_url("https://user:pass@example.com")
    with pytest.raises(SuccesError, match="autorisée"):
        normalize_relay_url("http://169.254.169.254/")


# ---------------------------------------------------------------------------
# Device attribution — the mesh's first invariant
# ---------------------------------------------------------------------------


def _operation(op_id: str, device_id: str, title: str) -> dict:
    """A minimal authored upsert, shaped like the wire format."""
    return {
        "opId": op_id,
        "deviceId": device_id,
        "entity": "tasks",
        "entityId": f"task_{op_id}",
        "kind": "upsert",
        "timestampMs": 1_700_000_000_000,
        "payload": {"id": f"task_{op_id}", "title": title, "done": False},
    }


def test_peer_is_bound_to_the_device_it_first_authors(tmp_path) -> None:
    db = store(tmp_path, "bind")
    peer = authorize_peer(db, "iPhone")

    db.apply_remote_operations(peer["peerId"], [_operation("op-1", "phone-a", "Un")])

    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        bound = conn.execute(
            "SELECT device_id FROM succes_sync_peers WHERE id=?", (peer["peerId"],)
        ).fetchone()["device_id"]
    assert bound == "phone-a"


def test_a_peer_cannot_author_in_another_devices_name(tmp_path) -> None:
    """The forgery the old code allowed: authenticated ≠ authorized to be anyone.

    Every later guarantee — audit, revocation, conflict arbitration — keys on
    the device id, so a peer that can forge it can rewrite whose history it is.
    """
    db = store(tmp_path, "forge")
    peer = authorize_peer(db, "iPhone")
    db.apply_remote_operations(peer["peerId"], [_operation("op-1", "phone-a", "Un")])

    with pytest.raises(SuccesError, match="autre appareil"):
        db.apply_remote_operations(
            peer["peerId"], [_operation("op-2", "mac-victime", "Forgé")]
        )


def test_relayed_history_from_other_devices_still_flows(tmp_path) -> None:
    """The counterweight: a peer may RELAY what it received, star-topology.

    A guest echoes back operations it pulled from the host; those carry other
    devices' ids and must not be mistaken for forgeries — they arrive as
    duplicates, which is precisely why the check sits after that branch.
    """
    db = store(tmp_path, "relay")
    peer = authorize_peer(db, "iPhone")
    # The host already holds an operation authored by the Mac…
    db.apply_inbound_operations([_operation("op-mac", "mac-hote", "Depuis le Mac")])
    # …and the guest echoes it back alongside its own new one.
    stats = db.apply_remote_operations(
        peer["peerId"],
        [
            _operation("op-mac", "mac-hote", "Depuis le Mac"),
            _operation("op-phone", "phone-a", "Depuis le téléphone"),
        ],
    )
    assert stats["duplicate"] == 1
    assert stats["applied"] == 1
