"""The mesh HTTP surface: enrolment is open, everything else is not.

The security property under test is the asymmetry: a joining device has no
API key and must still be able to redeem its invitation, while listing,
revoking and heartbeats stay behind the wall. Getting that boundary wrong in
either direction is how a control plane becomes a liability.
"""

from __future__ import annotations

import base64

import pytest

from diapason.security.signing import generate_keypair

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.mesh.presence import (  # noqa: E402
    BACKGROUND_WINDOW_MS,
    IDLE_WINDOW_MS,
    ONLINE_WINDOW_MS,
    is_reachable,
    presence_of,
)
from diapason.mesh.registry import DeviceRegistry, now_ms  # noqa: E402
from diapason.mesh.routes import router, set_registry_for_tests  # noqa: E402
from diapason.server.auth_middleware import AuthMiddleware  # noqa: E402

KEY = "diapason_sk_test_key_for_the_mesh_routes_0000"


@pytest.fixture
def client(tmp_path):
    registry = DeviceRegistry(tmp_path / "mesh.db")
    set_registry_for_tests(registry)
    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=KEY)
    app.include_router(router)
    with TestClient(app) as test_client:
        test_client.registry = registry  # type: ignore[attr-defined]
        yield test_client
    set_registry_for_tests(None)


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {KEY}"}


def a_key() -> str:
    return base64.b64encode(generate_keypair().public_key).decode("ascii")


def enrol(
    client, device_id="dev_pc", platform="WINDOWS", capabilities=None, address=""
):
    invitation = client.post(
        "/v1/mesh/pairings", json={"deviceName": "PC du bureau"}, headers=auth()
    ).json()
    payload = {
        "pairingToken": invitation["pairingToken"],
        "deviceId": device_id,
        "publicKey": a_key(),
        "name": "PC du bureau",
        "platform": platform,
        "deviceType": "DESKTOP",
        "capabilities": capabilities or ["app.navigate", "tasks.write"],
    }
    if address:
        payload["address"] = address
    return client.post("/v1/mesh/pairings/redeem", json=payload)


class TestAuthenticationBoundary:
    def test_enrolment_works_without_the_api_key(self, client):
        """The joining device has no key — the invitation is its credential."""
        response = enrol(client)
        assert response.status_code == 200, response.text
        assert response.json()["device"]["trustLevel"] == "TRUSTED"

    def test_enrolment_still_answers_our_identity(self, client):
        """Pairing is mutual: the new device needs our key to verify us."""
        body = enrol(client).json()
        assert len(base64.b64decode(body["host"]["publicKey"])) == 32

    def test_enrolment_tells_the_joining_device_where_we_live(self, client):
        """Addresses are exchanged here or not at all: until each side knows
        where the other is, neither can send nor even announce itself."""
        body = enrol(client).json()
        assert body["host"]["address"].startswith("http://")

    def test_an_address_offered_at_pairing_is_recorded_and_echoed(self, client):
        """Echoed from the row AFTER the write — reading back a null address
        would tell the joining device its address had been refused."""
        body = enrol(client, address="http://192.168.1.40:8000").json()
        assert body["device"]["address"] == "http://192.168.1.40:8000"
        listed = client.get("/v1/mesh/devices", headers=auth()).json()["devices"][0]
        assert listed["address"] == "http://192.168.1.40:8000"

    def test_pairing_without_an_address_still_succeeds(self, client):
        """A phone behind NAT has no address worth giving; it simply becomes
        command-able once it has announced itself."""
        body = enrol(client).json()
        assert body["device"]["trustLevel"] == "TRUSTED"
        assert not body["device"].get("address")

    def test_listing_devices_requires_the_api_key(self, client):
        enrol(client)
        assert client.get("/v1/mesh/devices").status_code == 401
        assert client.get("/v1/mesh/devices", headers=auth()).status_code == 200

    def test_revoking_requires_the_api_key(self, client):
        enrol(client)
        assert client.post("/v1/mesh/devices/dev_pc/revoke").status_code == 401

    def test_creating_an_invitation_requires_the_api_key(self, client):
        """Otherwise anyone reaching the port could mint their own way in."""
        response = client.post("/v1/mesh/pairings", json={"deviceName": "Intrus"})
        assert response.status_code == 401

    def test_a_forged_invitation_is_refused(self, client):
        response = client.post(
            "/v1/mesh/pairings/redeem",
            json={
                "pairingToken": "diapason_mesh_totally_made_up_token_value",
                "deviceId": "dev_intrus",
                "publicKey": a_key(),
                "name": "Intrus",
                "platform": "WINDOWS",
            },
        )
        assert response.status_code == 400
        assert "inconnu" in response.json()["detail"]


class TestFleetSurface:
    def test_devices_are_listed_with_their_presence(self, client):
        enrol(client)
        body = client.get("/v1/mesh/devices", headers=auth()).json()
        assert body["count"] == 1
        device = body["devices"][0]
        assert device["presence"]["state"] == "ONLINE"
        assert device["capabilities"] == ["app.navigate", "tasks.write"]

    def test_a_heartbeat_refreshes_presence(self, client):
        enrol(client)
        response = client.post(
            "/v1/mesh/devices/dev_pc/heartbeat",
            json={"appState": "planning", "transport": "lan"},
            headers=auth(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "ONLINE"
        assert body["appState"] == "planning"
        assert body["transport"] == "lan"

    def test_a_revoked_device_cannot_heartbeat_itself_back(self, client):
        enrol(client)
        client.post("/v1/mesh/devices/dev_pc/revoke", headers=auth())
        response = client.post(
            "/v1/mesh/devices/dev_pc/heartbeat", json={}, headers=auth()
        )
        assert response.status_code == 400

    def test_renaming_and_forgetting(self, client):
        enrol(client)
        renamed = client.patch(
            "/v1/mesh/devices/dev_pc", json={"name": "PC du salon"}, headers=auth()
        ).json()
        assert renamed["name"] == "PC du salon"
        client.delete("/v1/mesh/devices/dev_pc", headers=auth())
        assert client.get("/v1/mesh/devices/dev_pc", headers=auth()).status_code == 404

    def test_this_device_can_describe_itself(self, client):
        body = client.get("/v1/mesh/me", headers=auth()).json()
        assert body["deviceId"]
        assert "privateKey" not in body

    def test_a_declared_capability_is_still_only_a_claim(self, client):
        enrol(client, platform="IOS", capabilities=["tasks.read"])
        response = client.post(
            "/v1/mesh/devices/dev_pc/capabilities",
            json={"capabilities": ["tasks.read", "automation.approved.run"]},
            headers=auth(),
        )
        body = response.json()
        assert "automation.approved.run" in body["declaredCapabilities"]
        assert "automation.approved.run" not in body["capabilities"]


class TestPresenceLadder:
    """Spec §57: an absent device is never presented as present."""

    def _device(self, age_ms: int, trust: str = "TRUSTED") -> dict:
        return {
            "deviceId": "dev_x",
            "trustLevel": trust,
            "lastSeenAtMs": now_ms() - age_ms,
        }

    def test_a_fresh_heartbeat_is_online(self):
        assert presence_of(self._device(1_000))["state"] == "ONLINE"

    def test_two_missed_beats_are_tolerated(self):
        assert presence_of(self._device(ONLINE_WINDOW_MS - 500))["state"] == "ONLINE"

    def test_quiet_minutes_are_idle_not_offline(self):
        assert presence_of(self._device(IDLE_WINDOW_MS - 1_000))["state"] == "IDLE"

    def test_a_suspended_app_is_background(self):
        state = presence_of(self._device(BACKGROUND_WINDOW_MS - 1_000))["state"]
        assert state == "BACKGROUND"

    def test_a_long_silence_is_offline(self):
        assert presence_of(self._device(BACKGROUND_WINDOW_MS + 1))["state"] == "OFFLINE"

    def test_a_device_never_seen_is_offline(self):
        assert (
            presence_of({"deviceId": "d", "lastSeenAtMs": None})["state"] == "OFFLINE"
        )

    def test_a_revoked_device_is_offline_however_recent(self):
        # It beat one second ago, but we are not willing to reach it.
        assert presence_of(self._device(1_000, trust="REVOKED"))["state"] == "OFFLINE"

    def test_reachable_excludes_background(self):
        """A suspended phone may queue a notification; promising to OPEN a
        screen on it would be exactly the lie §57 forbids."""
        assert is_reachable(self._device(1_000))
        assert is_reachable(self._device(IDLE_WINDOW_MS - 1_000))
        assert not is_reachable(self._device(BACKGROUND_WINDOW_MS - 1_000))
        assert not is_reachable(self._device(BACKGROUND_WINDOW_MS + 1))
