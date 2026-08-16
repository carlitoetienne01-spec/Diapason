"""What a device must prove before this machine believes it is awake.

Presence is not decoration. Every "elle n'a pas été effectuée" and every
"partira dès son retour" the user is told rests on it being true, so a
beacon that can be forged or replayed turns the whole honesty layer into
theatre. These tests are the proof that it cannot.
"""

from __future__ import annotations

import base64

import pytest

from diapason.mesh.beacon import (
    MAX_BEACON_SKEW_MS,
    PresenceRejected,
    announce_to,
    announce_to_fleet,
    build_beacon,
    local_address,
    verify_beacon,
)
from diapason.mesh.commands import now_ms
from diapason.mesh.identity import canonical_bytes
from diapason.mesh.registry import DeviceRegistry
from diapason.security.signing import generate_keypair, sign_b64

OWNER = "owner_" + "a" * 32
HOST = "dev_ce_mac"
PEER = "dev_le_pc"


@pytest.fixture
def registry(tmp_path):
    return DeviceRegistry(db_path=tmp_path / "mesh.db")


@pytest.fixture
def peer_key():
    return generate_keypair()


@pytest.fixture
def paired(registry, peer_key):
    invitation = registry.create_pairing("PC du bureau")
    return registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=PEER,
        public_key_b64=base64.b64encode(peer_key.public_key).decode("ascii"),
        name="PC du bureau",
        platform="WINDOWS",
        device_type="DESKTOP",
        declared_capabilities=["app.navigate"],
    )


def beacon(peer_key, **overrides):
    """A beacon signed by the peer, with fields overridable to attack it."""
    from diapason.mesh.beacon import _SIGNED_FIELDS

    body = build_beacon(
        owner_id=OWNER,
        device_id=PEER,
        app_state="foreground",
        address="http://192.168.1.20:8000",
    )
    body.update(overrides)
    signable = {field: body.get(field) for field in _SIGNED_FIELDS}
    body["signature"] = sign_b64(canonical_bytes(signable), peer_key.private_key)
    return body


def accept(registry, body, **kw):
    return verify_beacon(
        body,
        registry=registry,
        local_owner_id=OWNER,
        local_device_id=HOST,
        **kw,
    )


class TestABeaconIsBelievedOnlyWithProof:
    def test_a_signed_beacon_from_a_paired_device_is_accepted(
        self, registry, peer_key, paired
    ):
        device = accept(registry, beacon(peer_key))
        assert device["deviceId"] == PEER
        assert device["address"] == "http://192.168.1.20:8000"

    def test_an_unsigned_beacon_is_refused(self, registry, peer_key, paired):
        body = beacon(peer_key)
        body["signature"] = ""
        with pytest.raises(PresenceRejected, match="pas signée"):
            accept(registry, body)

    def test_a_stranger_cannot_announce_a_device_it_does_not_own(
        self, registry, paired
    ):
        with pytest.raises(PresenceRejected, match="signature"):
            accept(registry, beacon(generate_keypair()))

    def test_an_unpaired_device_is_refused(self, registry, peer_key):
        with pytest.raises(PresenceRejected, match="pas autorisé"):
            accept(registry, beacon(peer_key))

    def test_a_revoked_device_cannot_keep_itself_alive(
        self, registry, peer_key, paired
    ):
        accept(registry, beacon(peer_key))
        registry.revoke(PEER)
        with pytest.raises(PresenceRejected, match="pas autorisé"):
            accept(registry, beacon(peer_key, sentAtMs=now_ms() + 1))

    def test_a_beacon_from_another_fleet_is_refused(self, registry, peer_key, paired):
        with pytest.raises(PresenceRejected, match="autre ensemble"):
            accept(registry, beacon(peer_key, ownerId="owner_" + "b" * 32))

    def test_a_device_does_not_announce_itself(self, registry, peer_key, paired):
        with pytest.raises(PresenceRejected, match="lui-même"):
            verify_beacon(
                beacon(peer_key),
                registry=registry,
                local_owner_id=OWNER,
                local_device_id=PEER,
            )


class TestReplayCannotFakeBeingAwake:
    """The attack this design exists to stop: capture one beacon from a
    machine, keep sending it, and the fleet believes that machine is on."""

    def test_the_same_beacon_twice_is_refused_the_second_time(
        self, registry, peer_key, paired
    ):
        body = beacon(peer_key)
        accept(registry, body)
        with pytest.raises(PresenceRejected, match="déjà été vue|dépassée"):
            accept(registry, dict(body))

    def test_an_older_beacon_cannot_overwrite_a_newer_one(
        self, registry, peer_key, paired
    ):
        stamp = now_ms()
        accept(registry, beacon(peer_key, sentAtMs=stamp))
        with pytest.raises(PresenceRejected, match="déjà été vue|dépassée"):
            accept(registry, beacon(peer_key, sentAtMs=stamp - 5_000))

    def test_a_captured_beacon_replayed_later_is_too_old(
        self, registry, peer_key, paired
    ):
        old = beacon(peer_key, sentAtMs=now_ms() - MAX_BEACON_SKEW_MS - 1_000)
        with pytest.raises(PresenceRejected, match="trop ancienne"):
            accept(registry, old)

    def test_a_beacon_from_the_future_is_refused(self, registry, peer_key, paired):
        ahead = beacon(peer_key, sentAtMs=now_ms() + MAX_BEACON_SKEW_MS + 5_000)
        with pytest.raises(PresenceRejected, match="futur"):
            accept(registry, ahead)

    def test_a_rejected_beacon_does_not_burn_the_watermark(
        self, registry, peer_key, paired
    ):
        """A forged beacon must not lock out the real device that follows it."""
        stamp = now_ms()
        forged = beacon(generate_keypair(), sentAtMs=stamp + 1_000)
        with pytest.raises(PresenceRejected):
            accept(registry, forged)
        # The genuine device, with an EARLIER timestamp, must still be heard.
        assert accept(registry, beacon(peer_key, sentAtMs=stamp))["deviceId"] == PEER


class TestWhatABeaconMayAndMayNotChange:
    def test_the_address_is_learned_from_the_beacon(self, registry, peer_key, paired):
        device = accept(registry, beacon(peer_key, address="http://192.168.1.77:8000"))
        assert device["address"] == "http://192.168.1.77:8000"

    def test_a_device_cannot_grant_itself_a_capability_it_may_not_have(
        self, registry, peer_key, paired
    ):
        device = accept(
            registry,
            beacon(
                peer_key,
                capabilities=["app.navigate", "automation.approved.run", "sudo"],
            ),
        )
        assert "sudo" not in device["capabilities"]

    def test_a_tampered_field_invalidates_the_signature(
        self, registry, peer_key, paired
    ):
        body = beacon(peer_key)
        body["address"] = "http://10.0.0.99:8000"  # changed after signing
        with pytest.raises(PresenceRejected, match="signature"):
            accept(registry, body)

    def test_the_signature_covers_the_timestamp(self, registry, peer_key, paired):
        body = beacon(peer_key)
        body["sentAtMs"] = body["sentAtMs"] + 1
        with pytest.raises(PresenceRejected, match="signature"):
            accept(registry, body)


class TestAnnouncing:
    def test_a_peer_with_no_address_is_skipped_not_attempted(self, registry):
        calls = []
        assert (
            announce_to(
                {"deviceId": "x", "trustLevel": "TRUSTED"},
                post=lambda u, b: calls.append(u) or 200,
            )
            is False
        )
        assert not calls

    def test_a_reachable_peer_receives_a_signed_envelope(self, registry, paired):
        sent = {}

        def post(url, body):
            sent["url"] = url
            sent["body"] = body
            return 200

        device = registry.get(PEER)
        registry.heartbeat(PEER, address="http://127.0.0.1:8100")
        assert announce_to(registry.get(PEER), post=post) is True
        assert sent["url"].endswith("/v1/mesh/presence")
        assert sent["body"]["signature"]
        assert sent["body"]["deviceId"] != device["deviceId"]  # ours, not theirs

    def test_a_failing_peer_is_reported_false_never_raised(self, registry, paired):
        registry.heartbeat(PEER, address="http://127.0.0.1:8100")

        def broken(url, body):
            raise OSError("réseau coupé")

        assert announce_to(registry.get(PEER), post=broken) is False

    def test_a_revoked_peer_is_not_announced_to(self, registry, paired):
        registry.heartbeat(PEER, address="http://127.0.0.1:8100")
        registry.revoke(PEER)
        calls = []
        result = announce_to_fleet(
            registry=registry, post=lambda u, b: calls.append(u) or 200
        )
        assert calls == []
        assert result["reached"] == 0

    def test_the_fleet_count_distinguishes_reached_from_skipped(self, registry, paired):
        registry.heartbeat(PEER, address="http://127.0.0.1:8100")
        result = announce_to_fleet(registry=registry, post=lambda u, b: 200)
        assert result == {"reached": 1, "skipped": 0}


class TestOurOwnAddress:
    def test_it_is_an_http_url_on_a_private_host(self):
        from diapason.mesh.transport import address_is_private

        address = local_address()
        assert address.startswith("http://")
        assert address_is_private(address), address
