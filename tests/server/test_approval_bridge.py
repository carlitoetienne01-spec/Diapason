"""Chat tool confirmations answered through the approval bell.

The bridge is what makes the composer's Auto/Ask chip TRUE: "auto" keeps
the historical run-without-asking behavior, "ask" parks the tool call in
the same queue the bell already displays and waits for the decision.
"""

from __future__ import annotations

import threading
import time

import pytest

from diapason.server import approval_bridge
from diapason.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    ApprovalStore,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A temp-backed store that the bridge's late imports resolve to."""
    db = str(tmp_path / "approvals.db")
    created = ApprovalStore(db_path=db)

    import diapason.tools.approval_store as mod

    class _TempStore(ApprovalStore):
        def __init__(self, db_path: str = "") -> None:
            super().__init__(db_path=db)

    monkeypatch.setattr(mod, "ApprovalStore", _TempStore)
    # Poll fast: the production 1 s cadence is user-facing, not test-facing.
    monkeypatch.setattr(approval_bridge, "_POLL_INTERVAL_S", 0.02)
    yield created
    created.close()


def _set_mode(monkeypatch, mode: str) -> None:
    class _Agent:
        tool_approval = mode

    class _Cfg:
        agent = _Agent()

    import diapason.core.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda: _Cfg())


class TestAutoMode:
    def test_auto_confirms_instantly_without_touching_the_queue(
        self, store, monkeypatch
    ):
        _set_mode(monkeypatch, "auto")
        confirm = approval_bridge.tool_confirm_callback()
        assert confirm("Run shell command?") is True
        assert store.list_pending() == []

    def test_unknown_mode_degrades_to_auto(self, store, monkeypatch):
        _set_mode(monkeypatch, "yolo")
        assert approval_bridge.current_mode() == "auto"

    def test_config_trouble_degrades_to_auto(self, monkeypatch):
        import diapason.core.config as config_mod

        def boom():
            raise RuntimeError("no config")

        monkeypatch.setattr(config_mod, "load_config", boom)
        assert approval_bridge.current_mode() == "auto"


class TestAskMode:
    def _decide_later(self, store, status, delay=0.05):
        def worker():
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                pending = store.list_pending()
                if pending:
                    store.update_status(pending[0].id, status)
                    return
                time.sleep(0.01)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return t

    def test_approval_from_the_bell_releases_the_tool(self, store, monkeypatch):
        _set_mode(monkeypatch, "ask")
        self._decide_later(store, STATUS_APPROVED)
        confirm = approval_bridge.tool_confirm_callback(wait_s=2)
        assert confirm("Send the email?") is True

    def test_denial_refuses_the_tool(self, store, monkeypatch):
        _set_mode(monkeypatch, "ask")
        self._decide_later(store, STATUS_DENIED)
        confirm = approval_bridge.tool_confirm_callback(wait_s=2)
        assert confirm("Delete the branch?") is False

    def test_timeout_fails_closed_and_expires_the_action(self, store, monkeypatch):
        _set_mode(monkeypatch, "ask")
        confirm = approval_bridge.tool_confirm_callback(wait_s=0.1)
        assert confirm("rm -rf ./build ?") is False
        actions = [
            a
            for a in [store.get_action(p.id) for p in store.list_pending()]
            if a is not None
        ]
        # Nothing left pending: the unanswered action was expired, not lost.
        assert actions == []

    def test_the_queued_action_is_what_the_bell_shows(self, store, monkeypatch):
        _set_mode(monkeypatch, "ask")
        confirm = approval_bridge.tool_confirm_callback(wait_s=0.05)
        confirm("Execute shell command: git push?")
        # After the timeout the action exists with the prompt as description.
        row = store._conn.execute(
            "SELECT action_type, description, status FROM pending_actions"
        ).fetchone()
        assert row[0] == approval_bridge.TOOL_CONFIRMATION_ACTION
        assert "git push" in row[1]
        assert row[2] in (STATUS_EXPIRED, STATUS_PENDING, STATUS_DENIED)


class TestConfigRoute:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import diapason.core.config as config_mod

        monkeypatch.setenv("DIAPASON_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(
            config_mod, "get_config_path", lambda: tmp_path / "config.toml",
            raising=False,
        )
        from diapason.server.config_routes import create_config_router

        app = FastAPI()
        app.include_router(create_config_router())
        return TestClient(app)

    def test_tool_approval_is_readable(self, client):
        body = client.get("/v1/config").json()
        assert body["agent"]["tool_approval"] in ("auto", "ask")

    def test_bad_value_is_rejected(self, client):
        r = client.post(
            "/v1/config/set",
            json={"key": "agent.tool_approval", "value": "maybe"},
        )
        assert r.status_code == 400

    def test_other_agent_keys_stay_locked(self, client):
        r = client.post(
            "/v1/config/set", json={"key": "agent.max_turns", "value": 99}
        )
        assert r.status_code == 400
