"""Regression tests for the authenticated realtime voice handshake."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from diapason.server.voice_live_routes import voice_live_router
from diapason.speech.realtime.base import SessionEvent


class _ReadySession:
    provider_id = "local"
    input_sample_rate = 16000
    output_sample_rate = 24000

    async def connect(self) -> None:
        return None

    async def events(self):
        yield SessionEvent(kind="ready")
        yield SessionEvent(kind="closed")

    async def send_audio(self, _pcm16: bytes) -> None:
        return None

    async def send_text(self, _text: str) -> None:
        return None

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _client(api_key: str = "diapason_sk_test") -> TestClient:
    app = FastAPI()
    app.state.api_key = api_key
    app.include_router(voice_live_router)
    return TestClient(app)


def test_voice_websocket_rejects_missing_local_token():
    client = _client()

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/v1/voice/live?provider=local"):
            pass

    assert exc_info.value.code == 1008


def test_voice_websocket_accepts_secret_subprotocol_and_reaches_ready(monkeypatch):
    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session",
        lambda *_args, **_kwargs: _ReadySession(),
    )
    client = _client()

    with client.websocket_connect(
        "/v1/voice/live?provider=local",
        subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
    ) as websocket:
        assert websocket.accepted_subprotocol == "diapason"
        websocket.send_json(
            {
                "type": "start",
                "provider": "local",
                "include_memory": False,
            }
        )
        assert websocket.receive_json() == {"type": "ready"}


def test_voice_health_reports_local_runtime_reason(monkeypatch):
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.local_voice_readiness",
        lambda: (False, "missing-dependencies"),
    )
    monkeypatch.setattr("diapason.core.cloud_keys.get_cloud_key", lambda *_names: None)

    response = _client().get("/v1/voice/live/health")

    assert response.status_code == 200
    assert response.json()["providers"]["local"] == {
        "configured": False,
        "reason": "missing-dependencies",
    }
