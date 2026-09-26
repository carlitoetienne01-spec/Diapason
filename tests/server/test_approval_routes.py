"""Tests for the proactive-agent approval queue API routes."""

from __future__ import annotations

import pytest

from diapason.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_PENDING,
    TIER_HIGH,
    TIER_LOW,
    TIER_MEDIUM,
    ApprovalStore,
)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approval_store(tmp_path):
    """A fresh ApprovalStore backed by a temp DB, injected into the routes module."""
    import diapason.server.approval_routes as ar

    store = ApprovalStore(db_path=str(tmp_path / "approvals.db"))
    original = ar._store
    ar._store = store
    yield store
    ar._store = original
    store.close()


@pytest.fixture
def client(approval_store):  # noqa: ARG001 — triggers store injection as a side-effect
    """TestClient with the approval router mounted on a minimal FastAPI app."""
    from diapason.server.approval_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _queue(store: ApprovalStore, **kwargs) -> str:
    """Helper — queue an action and return its id."""
    defaults = dict(
        action_type="file_write",
        description="Write a report to ~/Desktop/report.txt",
        payload={"path": "~/Desktop/report.txt", "size_kb": 12},
        permission_key="file_write:path:~/Desktop",
        tier=TIER_MEDIUM,
    )
    defaults.update(kwargs)
    action = store.queue_action(**defaults)
    return action.id


def _expire(store: ApprovalStore, action_id: str) -> None:
    """Force an action's expires_at into the past so list_pending skips it."""
    store._conn.execute(
        "UPDATE pending_actions SET expires_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", action_id),
    )
    store._conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestListPendingApprovals:
    def test_empty_queue(self, client):
        resp = client.get("/v1/approvals/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["actions"] == []
        assert body["count"] == 0

    def test_returns_queued_items(self, client, approval_store):
        _queue(approval_store)
        resp = client.get("/v1/approvals/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert len(body["actions"]) == 1

    def test_returns_multiple_items(self, client, approval_store):
        _queue(approval_store, action_type="email_send", description="Send digest")
        _queue(approval_store, action_type="file_delete", description="Delete temps")
        resp = client.get("/v1/approvals/pending")
        assert resp.json()["count"] == 2

    def test_response_shape(self, client, approval_store):
        _queue(
            approval_store,
            action_type="sms_send",
            description="Reply to Alice",
            payload={"to": "+15550001234", "body": "On my way"},
            tier=TIER_HIGH,
        )
        resp = client.get("/v1/approvals/pending")
        action = resp.json()["actions"][0]

        required_fields = {
            "id",
            "action_type",
            "description",
            "payload",
            "permission_key",
            "tier",
            "status",
            "created_at",
            "expires_at",
        }
        assert required_fields.issubset(action.keys()), (
            f"Missing fields: {required_fields - action.keys()}"
        )

    def test_payload_is_dict_not_string(self, client, approval_store):
        """The route must deserialize payload — not return the raw JSON string."""
        _queue(approval_store, payload={"key": "value", "nested": {"x": 1}})
        action = client.get("/v1/approvals/pending").json()["actions"][0]
        assert isinstance(action["payload"], dict), (
            f"Expected dict, got {type(action['payload'])}"
        )
        assert action["payload"]["key"] == "value"

    def test_correct_field_values(self, client, approval_store):
        _queue(
            approval_store,
            action_type="calendar_create",
            description="Create meeting event",
            tier=TIER_LOW,
        )
        action = client.get("/v1/approvals/pending").json()["actions"][0]
        assert action["action_type"] == "calendar_create"
        assert action["description"] == "Create meeting event"
        assert action["tier"] == TIER_LOW
        assert action["status"] == STATUS_PENDING

    def test_does_not_return_approved_actions(self, client, approval_store):
        action_id = _queue(approval_store)
        approval_store.update_status(action_id, STATUS_APPROVED)
        resp = client.get("/v1/approvals/pending")
        assert resp.json()["count"] == 0

    def test_does_not_return_denied_actions(self, client, approval_store):
        action_id = _queue(approval_store)
        approval_store.update_status(action_id, STATUS_DENIED)
        resp = client.get("/v1/approvals/pending")
        assert resp.json()["count"] == 0

    def test_auto_expires_stale_actions(self, client, approval_store):
        """GET /pending must expire past-TTL items and exclude them."""
        action_id = _queue(approval_store)
        _expire(approval_store, action_id)
        resp = client.get("/v1/approvals/pending")
        assert resp.json()["count"] == 0

    def test_stale_expired_mixes_with_live(self, client, approval_store):
        """Only expired items are excluded; live items still appear."""
        stale_id = _queue(approval_store, description="Stale action")
        _queue(approval_store, description="Live action")
        _expire(approval_store, stale_id)
        resp = client.get("/v1/approvals/pending")
        body = resp.json()
        assert body["count"] == 1
        assert body["actions"][0]["description"] == "Live action"

    def test_timestamps_are_strings(self, client, approval_store):
        _queue(approval_store)
        action = client.get("/v1/approvals/pending").json()["actions"][0]
        assert isinstance(action["created_at"], str)
        assert isinstance(action["expires_at"], str)


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestApproveAction:
    def test_approve_returns_200(self, client, approval_store):
        action_id = _queue(approval_store)
        resp = client.post(f"/v1/approvals/{action_id}/approve")
        assert resp.status_code == 200

    def test_approve_response_body(self, client, approval_store):
        action_id = _queue(approval_store)
        body = client.post(f"/v1/approvals/{action_id}/approve").json()
        assert body["status"] == "approved"
        assert body["id"] == action_id

    def test_approve_updates_db_status(self, client, approval_store):
        action_id = _queue(approval_store)
        client.post(f"/v1/approvals/{action_id}/approve")
        action = approval_store.get_action(action_id)
        assert action is not None
        assert action.status == STATUS_APPROVED

    def test_approve_removes_from_pending_list(self, client, approval_store):
        action_id = _queue(approval_store)
        client.post(f"/v1/approvals/{action_id}/approve")
        resp = client.get("/v1/approvals/pending")
        ids = [a["id"] for a in resp.json()["actions"]]
        assert action_id not in ids

    def test_approve_nonexistent_returns_404(self, client):
        resp = client.post("/v1/approvals/doesnotexist/approve")
        assert resp.status_code == 404

    def test_approve_only_removes_target(self, client, approval_store):
        """Approving one action must leave others untouched."""
        id_a = _queue(approval_store, description="Action A")
        id_b = _queue(approval_store, description="Action B")
        client.post(f"/v1/approvals/{id_a}/approve")
        resp = client.get("/v1/approvals/pending")
        body = resp.json()
        assert body["count"] == 1
        assert body["actions"][0]["id"] == id_b


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestDenyAction:
    def test_deny_returns_200(self, client, approval_store):
        action_id = _queue(approval_store)
        resp = client.post(f"/v1/approvals/{action_id}/deny")
        assert resp.status_code == 200

    def test_deny_response_body(self, client, approval_store):
        action_id = _queue(approval_store)
        body = client.post(f"/v1/approvals/{action_id}/deny").json()
        assert body["status"] == "denied"
        assert body["id"] == action_id

    def test_deny_updates_db_status(self, client, approval_store):
        action_id = _queue(approval_store)
        client.post(f"/v1/approvals/{action_id}/deny")
        action = approval_store.get_action(action_id)
        assert action is not None
        assert action.status == STATUS_DENIED

    def test_deny_removes_from_pending_list(self, client, approval_store):
        action_id = _queue(approval_store)
        client.post(f"/v1/approvals/{action_id}/deny")
        resp = client.get("/v1/approvals/pending")
        ids = [a["id"] for a in resp.json()["actions"]]
        assert action_id not in ids

    def test_deny_nonexistent_returns_404(self, client):
        resp = client.post("/v1/approvals/doesnotexist/deny")
        assert resp.status_code == 404

    def test_deny_only_removes_target(self, client, approval_store):
        id_a = _queue(approval_store, description="Action A")
        id_b = _queue(approval_store, description="Action B")
        client.post(f"/v1/approvals/{id_a}/deny")
        resp = client.get("/v1/approvals/pending")
        body = resp.json()
        assert body["count"] == 1
        assert body["actions"][0]["id"] == id_b


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestApprovalStoreIntegration:
    """End-to-end scenarios: queue → inspect → decide."""

    def test_full_approve_flow(self, client, approval_store):
        """Queue an action, verify it appears, approve it, verify it's gone."""
        action_id = _queue(
            approval_store,
            action_type="email_delete",
            description="Delete promotional email from newsletters@company.com",
            payload={"message_id": "abc123", "subject": "Weekly promo"},
            tier=TIER_HIGH,
        )

        # Should appear in pending
        pending = client.get("/v1/approvals/pending").json()
        assert pending["count"] == 1
        assert pending["actions"][0]["id"] == action_id

        # Approve it
        resp = client.post(f"/v1/approvals/{action_id}/approve")
        assert resp.status_code == 200

        # Should be gone from pending
        assert client.get("/v1/approvals/pending").json()["count"] == 0

        # Status in DB should be approved
        assert approval_store.get_action(action_id).status == STATUS_APPROVED

    def test_full_deny_flow(self, client, approval_store):
        action_id = _queue(
            approval_store,
            action_type="file_delete",
            description="Delete ~/Documents/report.pdf",
            tier=TIER_HIGH,
        )

        assert client.get("/v1/approvals/pending").json()["count"] == 1

        resp = client.post(f"/v1/approvals/{action_id}/deny")
        assert resp.status_code == 200

        assert client.get("/v1/approvals/pending").json()["count"] == 0
        assert approval_store.get_action(action_id).status == STATUS_DENIED

    def test_mixed_queue_approve_one_deny_one(self, client, approval_store):
        id_a = _queue(approval_store, description="Send email")
        id_b = _queue(approval_store, description="Delete file")
        id_c = _queue(approval_store, description="Create calendar event")

        assert client.get("/v1/approvals/pending").json()["count"] == 3

        client.post(f"/v1/approvals/{id_a}/approve")
        client.post(f"/v1/approvals/{id_b}/deny")

        pending = client.get("/v1/approvals/pending").json()
        assert pending["count"] == 1
        assert pending["actions"][0]["id"] == id_c

        assert approval_store.get_action(id_a).status == STATUS_APPROVED
        assert approval_store.get_action(id_b).status == STATUS_DENIED
        assert approval_store.get_action(id_c).status == STATUS_PENDING

    def test_empty_payload_handled(self, client, approval_store):
        """Actions with empty payloads should serialize cleanly."""
        _queue(approval_store, payload={})
        action = client.get("/v1/approvals/pending").json()["actions"][0]
        assert isinstance(action["payload"], dict)
        assert action["payload"] == {}

    def test_nested_payload_preserved(self, client, approval_store):
        payload = {
            "email": {"to": "user@example.com", "subject": "Hello"},
            "metadata": {"priority": 1, "tags": ["newsletter", "promo"]},
        }
        _queue(approval_store, payload=payload)
        action = client.get("/v1/approvals/pending").json()["actions"][0]
        assert action["payload"]["email"]["to"] == "user@example.com"
        assert action["payload"]["metadata"]["tags"] == ["newsletter", "promo"]

    def test_all_tiers_accepted(self, client, approval_store):
        for tier in ["trivial", "low", "medium", "high"]:
            _queue(approval_store, tier=tier, description=f"{tier} action")
        resp = client.get("/v1/approvals/pending")
        tiers = {a["tier"] for a in resp.json()["actions"]}
        assert tiers == {"trivial", "low", "medium", "high"}


# ── la boucle reste libre (CLAUDE.md §5) ─────────────────────────────────
#
# 26/09/2026, phase 5 du plan mobile : le téléphone sonde ces routes en plus
# de la cloche du Mac. Un cœur bat toutes les 10 ms pendant l'appel ; le
# magasin est ralenti de 0,5 s — ce qu'un verrou SQLite tenu par un autre
# écrivain coûte au moins. Un trou de plus de 0,3 s entre deux battements
# dit que la route a gelé la boucle.

_LENT_S = 0.5
_TROU_TOLERE_S = 0.3


def _plus_long_trou(scenario) -> float:
    import asyncio
    import time

    async def mener():
        instants: list[float] = []
        arret = asyncio.Event()

        async def coeur():
            while True:
                instants.append(time.monotonic())
                if arret.is_set():
                    return
                await asyncio.sleep(0.01)

        battre = asyncio.ensure_future(coeur())
        await asyncio.sleep(0.05)
        await scenario()
        arret.set()
        await battre
        return max(b - a for a, b in zip(instants, instants[1:]))

    return asyncio.run(mener())


def _ralentir(store: ApprovalStore, monkeypatch, *noms: str) -> None:
    import time

    for nom in noms:
        original = getattr(store, nom)

        def lent(*args, _original=original, **kwargs):
            time.sleep(_LENT_S)
            return _original(*args, **kwargs)

        monkeypatch.setattr(store, nom, lent)


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestLaClocheNeGelePasLaBoucle:
    """Phase 5 du plan mobile : la cloche est sondée par le Mac ET le
    téléphone ; une lecture de la base ne doit jamais figer le flux du chat
    ni la voix."""

    def _app(self):
        from diapason.server.approval_routes import router

        app = FastAPI()
        app.include_router(router)
        return app

    def test_la_liste_des_demandes_se_lit_dans_un_fil(
        self, approval_store, monkeypatch
    ):
        from httpx import ASGITransport, AsyncClient

        _queue(approval_store)
        _ralentir(approval_store, monkeypatch, "expire_stale")
        app = self._app()

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                reponse = await c.get("/v1/approvals/pending")
                assert reponse.json()["count"] == 1, "la demande doit rester listée"

        trou = _plus_long_trou(scenario)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s en listant"

    def test_approuver_et_refuser_s_ecrivent_dans_un_fil(
        self, approval_store, monkeypatch
    ):
        from httpx import ASGITransport, AsyncClient

        a = _queue(approval_store)
        b = _queue(approval_store)
        _ralentir(approval_store, monkeypatch, "get_action")
        app = self._app()

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                assert (await c.post(f"/v1/approvals/{a}/approve")).status_code == 200
                assert (await c.post(f"/v1/approvals/{b}/deny")).status_code == 200

        trou = _plus_long_trou(scenario)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s en décidant"

    def test_deux_appareils_qui_decident_ensemble_n_ecrivent_qu_une_decision(
        self, approval_store, monkeypatch
    ):
        """Le Mac approuve pendant que le téléphone refuse : dans des fils,
        sans verrou, les deux passaient le contrôle « pending » et le second
        écrasait le premier. Un seul 200, l'autre 409, et la base garde la
        décision qui a répondu 200."""
        import asyncio
        import threading

        from httpx import ASGITransport, AsyncClient

        action_id = _queue(approval_store)
        # Un rendez-vous plutôt qu'un simple retard : chaque lecture attend
        # (1 s au plus) que l'autre décision lise aussi. Sans verrou, les
        # deux lisent « pending » ensemble ; avec, la seconde ne peut pas
        # lire tant que la première n'a pas écrit, et le rendez-vous expire.
        arrivees = threading.Barrier(2, timeout=1.0)
        original = approval_store.get_action

        def lecture_au_rendez_vous(*args, **kwargs):
            try:
                arrivees.wait()
            except threading.BrokenBarrierError:
                pass
            return original(*args, **kwargs)

        monkeypatch.setattr(approval_store, "get_action", lecture_au_rendez_vous)
        app = self._app()

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                return await asyncio.gather(
                    c.post(f"/v1/approvals/{action_id}/approve"),
                    c.post(f"/v1/approvals/{action_id}/deny"),
                )

        oui, non = asyncio.run(scenario())
        statuts = sorted([oui.status_code, non.status_code])
        assert statuts == [200, 409], f"une seule décision doit passer, pas {statuts}"
        gagnante = oui if oui.status_code == 200 else non
        attendu = STATUS_APPROVED if gagnante is oui else STATUS_DENIED
        assert approval_store.get_action(action_id).status == attendu, (
            "la base doit garder la décision qui a répondu 200"
        )
