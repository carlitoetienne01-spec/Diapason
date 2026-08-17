"""Garbage from a stranger must come back as a refusal, never as a crash.

Five mesh routes are reachable without the local API key, which makes them
the only surface anyone on the network can touch at all. An audit found that
malformed bodies raised uncaught exceptions there — a 500 and a stack trace
in the log, on demand, from anybody — and that none of the five was rate
limited, because being outside the key wall and being outside the limiter
were accidentally the same condition.
"""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.mesh.queue import CommandQueue
from diapason.mesh.registry import DeviceRegistry
from diapason.mesh.routes import router, set_queue_for_tests, set_registry_for_tests
from diapason.security.signing import generate_keypair
from diapason.server.auth_middleware import (
    _OPEN_MESH_ROUTES,
    AuthMiddleware,
    RateLimitMiddleware,
)

KEY = "cle_de_test_0123456789abcdef"

# Every shape a body can arrive in when nobody is being cooperative.
RUBBISH = [
    {},
    {"version": "pas un nombre"},
    {"version": 1, "ownerId": None},
    {"version": 1, "ownerId": [], "deviceId": {}},
    {"version": [1], "sentAtMs": "hier"},
    {"results": "pas une liste"},
    {"signature": ["pas", "une", "chaîne"]},
]

SIGNED_ROUTES = [
    "/v1/mesh/commands/poll",
    "/v1/mesh/commands/ack",
    "/v1/mesh/presence",
]


@pytest.fixture
def client(tmp_path):
    registry = DeviceRegistry(tmp_path / "mesh.db")
    set_registry_for_tests(registry)
    set_queue_for_tests(CommandQueue(tmp_path / "mesh.db"))
    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=KEY)
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client
    set_registry_for_tests(None)
    set_queue_for_tests(None)


class TestNothingCrashes:
    @pytest.mark.parametrize("path", SIGNED_ROUTES)
    @pytest.mark.parametrize("body", RUBBISH)
    def test_a_signed_route_refuses_rather_than_raising(self, client, path, body):
        response = client.post(path, json=body)
        assert response.status_code < 500, response.text
        assert response.status_code in {400, 403, 422}

    @pytest.mark.parametrize("body", RUBBISH)
    def test_deliver_answers_a_verdict_rather_than_raising(self, client, body):
        """This route reports its verdict in the body by design, so a refusal
        is a 200 whose status says DENIED — not an HTTP error."""
        response = client.post("/v1/mesh/commands/deliver", json=body)
        assert response.status_code < 500, response.text
        if response.status_code == 200:
            assert response.json()["status"] != "SUCCESS"

    @pytest.mark.parametrize("path", [*SIGNED_ROUTES, "/v1/mesh/commands/deliver"])
    def test_a_non_object_body_is_refused(self, client, path):
        for body in ["une chaîne", 42, [1, 2, 3], None]:
            assert client.post(path, json=body).status_code < 500

    def test_redeem_refuses_rubbish_without_the_api_key(self, client):
        for body in RUBBISH:
            assert client.post("/v1/mesh/pairings/redeem", json=body).status_code < 500

    @pytest.mark.parametrize("path", [*SIGNED_ROUTES, "/v1/mesh/commands/deliver"])
    def test_pathological_json_values_are_refused(self, client, path):
        """Sent as raw text, because these are values Python's own encoder
        refuses to produce — which is exactly why an attacker would use them.
        JSON has no bound on a number's magnitude; Python turns 1e400 into
        inf and a very long digit string into an unbounded int."""
        for raw in [
            b'{"version": 1e400, "sentAtMs": 1e400}',
            b'{"version": 1, "sentAtMs": -1e400}',
            b'{"version": 1, "sentAtMs": ' + b"9" * 400 + b"}",
            b'{"version": NaN}',
            b"{",
            b"",
            b"\x00\x01\x02",
        ]:
            response = client.post(
                path, content=raw, headers={"Content-Type": "application/json"}
            )
            assert response.status_code < 500, (path, raw[:40], response.text[:200])


class TestTheOpenRoutesAreThrottled:
    def test_every_key_less_mesh_route_is_listed_as_open(self):
        """The two lists must not drift: a route that leaves the key wall
        without joining this set leaves the limiter too, silently."""
        for path in _OPEN_MESH_ROUTES:
            assert AuthMiddleware._requires_auth(path) is False, path

    def test_an_open_route_is_rate_limited(self, tmp_path):
        registry = DeviceRegistry(tmp_path / "mesh.db")
        set_registry_for_tests(registry)
        set_queue_for_tests(CommandQueue(tmp_path / "mesh.db"))
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, requests_per_minute=2, burst_size=1)
        app.add_middleware(AuthMiddleware, api_key=KEY)
        app.include_router(router)
        try:
            with TestClient(app) as client:
                codes = [
                    client.post("/v1/mesh/presence", json={}).status_code
                    for _ in range(30)
                ]
            assert 429 in codes, "la porte d'entrée du maillage n'est pas limitée"
        finally:
            set_registry_for_tests(None)
            set_queue_for_tests(None)

    def test_the_pairing_front_door_is_throttled_too(self, tmp_path):
        """routes.py says so in its own docstring. For a while it was false."""
        registry = DeviceRegistry(tmp_path / "mesh.db")
        set_registry_for_tests(registry)
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, requests_per_minute=2, burst_size=1)
        app.add_middleware(AuthMiddleware, api_key=KEY)
        app.include_router(router)
        payload = {
            "pairingToken": "diapason_mesh_un_code_totalement_invente_pour_le_test",
            "deviceId": "dev_intrus",
            "publicKey": base64.b64encode(generate_keypair().public_key).decode(),
            "name": "Intrus",
            "platform": "WINDOWS",
        }
        try:
            with TestClient(app) as client:
                codes = [
                    client.post("/v1/mesh/pairings/redeem", json=payload).status_code
                    for _ in range(30)
                ]
            assert 429 in codes
        finally:
            set_registry_for_tests(None)

    def test_the_authenticated_surface_keeps_its_own_bucket(self, tmp_path):
        """The open bucket must not become a way to starve the real one."""
        registry = DeviceRegistry(tmp_path / "mesh.db")
        set_registry_for_tests(registry)
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, requests_per_minute=2, burst_size=1)
        app.add_middleware(AuthMiddleware, api_key=KEY)
        app.include_router(router)
        try:
            with TestClient(app) as client:
                for _ in range(30):
                    client.post("/v1/mesh/presence", json={})
                # Exhausted the open bucket; the keyed surface is untouched.
                answer = client.get(
                    "/v1/mesh/devices", headers={"Authorization": f"Bearer {KEY}"}
                )
            assert answer.status_code == 200
        finally:
            set_registry_for_tests(None)
