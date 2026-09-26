"""Tests for WebSocket event bridge."""

from __future__ import annotations

import time

import pytest

from diapason.core.events import EventBus, EventType

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def app(event_bus):
    from diapason.server.ws_bridge import create_ws_router

    app = FastAPI()
    router = create_ws_router(event_bus)
    app.include_router(router)
    return app


class TestWSBridge:
    def test_websocket_receives_events(self, app, event_bus):
        client = TestClient(app)
        with client.websocket_connect("/v1/agents/events") as ws:
            event_bus.publish(
                EventType.AGENT_TICK_START,
                {
                    "agent_id": "test-123",
                    "agent_name": "test",
                },
            )
            time.sleep(0.05)  # Let call_soon_threadsafe deliver to queue
            data = ws.receive_json()
            assert data["type"] == "agent_tick_start"
            assert data["data"]["agent_id"] == "test-123"

    def test_websocket_filters_by_agent_id(self, app, event_bus):
        client = TestClient(app)
        with client.websocket_connect("/v1/agents/events?agent_id=agent-A") as ws:
            # This event should NOT be received (different agent)
            event_bus.publish(EventType.AGENT_TICK_START, {"agent_id": "agent-B"})
            # This event SHOULD be received
            event_bus.publish(EventType.AGENT_TICK_START, {"agent_id": "agent-A"})
            time.sleep(0.05)  # Let call_soon_threadsafe deliver to queue
            data = ws.receive_json()
            assert data["data"]["agent_id"] == "agent-A"


class TestLeFluxSortALaDeconnexion:
    """26/09/2026 (contre-épreuve) : un WebSocket /v1/agents/events ouvert
    bloquait l'arrêt du serveur. Le handler n'attendait que sa file
    d'événements, jamais le client : sans événement, il ne voyait ni la
    déconnexion ni le 1012 d'uvicorn, et « Waiting for background tasks to
    complete » durait jusqu'au SIGKILL de launchd. La route est ouverte au
    téléphone par la passerelle du tailnet, dont le socket s'arrête en
    premier dans la chaîne des signaux : elle faisait attendre l'API locale.
    """

    def test_le_handler_rend_la_main_quand_le_client_part(self, app):
        import asyncio

        async def scenario() -> list[dict]:
            envoyes: list[dict] = []
            accepte = asyncio.Event()
            etapes = iter([{"type": "websocket.connect"}])

            async def recevoir() -> dict:
                prochain = next(etapes, None)
                if prochain is not None:
                    return prochain
                await accepte.wait()
                return {"type": "websocket.disconnect", "code": 1001}

            async def envoyer(message: dict) -> None:
                envoyes.append(message)
                if message["type"] == "websocket.accept":
                    accepte.set()

            portee = {
                "type": "websocket",
                "asgi": {"version": "3.0"},
                "path": "/v1/agents/events",
                "raw_path": b"/v1/agents/events",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"host", b"testserver")],
                "client": ("127.0.0.1", 50000),
                "server": ("127.0.0.1", 8000),
                "scheme": "ws",
                "subprotocols": [],
            }
            await asyncio.wait_for(app(portee, recevoir, envoyer), 3)
            return envoyes

        envoyes = asyncio.run(scenario())
        assert envoyes and envoyes[0]["type"] == "websocket.accept", envoyes
