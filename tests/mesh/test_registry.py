"""The device registry: enrolment, trust, and who decides what a device can do.

The headline property here is acceptance TEST I — a device that CLAIMS a
capability its platform cannot honour does not receive it. Declaration is
information; the grant is the server's.
"""

from __future__ import annotations

import base64
import sqlite3

import pytest

from diapason.mesh.capabilities import effective_capabilities, platform_allows
from diapason.mesh.registry import (
    PAIRING_TTL_MS,
    DeviceRegistry,
    MeshError,
)
from diapason.security.signing import generate_keypair


@pytest.fixture
def registry(tmp_path) -> DeviceRegistry:
    return DeviceRegistry(tmp_path / "mesh.db")


def a_key() -> str:
    return base64.b64encode(generate_keypair().public_key).decode("ascii")


def enrol(
    registry: DeviceRegistry,
    *,
    device_id: str = "dev_phone",
    platform: str = "IOS",
    device_type: str = "PHONE",
    capabilities=(),
    key: str | None = None,
) -> dict:
    invitation = registry.create_pairing("iPhone de Carlito")
    return registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=device_id,
        public_key_b64=key or a_key(),
        name="iPhone de Carlito",
        platform=platform,
        device_type=device_type,
        declared_capabilities=list(capabilities),
    )


class TestPairing:
    def test_a_device_can_be_enrolled(self, registry):
        device = enrol(registry)
        assert device["deviceId"] == "dev_phone"
        assert device["trustLevel"] == "TRUSTED"
        assert registry.list_devices()[0]["name"] == "iPhone de Carlito"

    def test_the_invitation_is_stored_hashed_and_spent_once(self, registry, tmp_path):
        invitation = registry.create_pairing("iPad")
        token = invitation["pairingToken"]

        with sqlite3.connect(tmp_path / "mesh.db") as conn:
            stored = conn.execute("SELECT token_hash FROM mesh_pairings").fetchone()[0]
        assert token not in stored  # never at rest in the clear

        registry.redeem_pairing(
            token,
            device_id="dev_ipad",
            public_key_b64=a_key(),
            name="iPad",
            platform="IPADOS",
            device_type="TABLET",
        )
        with pytest.raises(MeshError, match="déjà été utilisé"):
            registry.redeem_pairing(
                token,
                device_id="dev_autre",
                public_key_b64=a_key(),
                name="Intrus",
                platform="IPADOS",
                device_type="TABLET",
            )

    def test_two_devices_racing_on_one_invitation_cannot_both_get_in(
        self, registry, tmp_path
    ):
        """« Spent once » has to hold under a race, not just in sequence.

        Reading redeemed_at_ms and then writing it left a gap — sqlite3 opens
        its transaction at the first write — so two redemptions could both
        read "unused" and both succeed. The extra device was not the worst of
        it: the legitimate one succeeded too, so the « déjà utilisé » message
        that would have told the user their code was stolen never appeared.
        """
        import threading

        token = registry.create_pairing("MacBook de Carlito")["pairingToken"]
        gate = threading.Barrier(2)
        outcomes: dict[str, str] = {}

        def redeem(tag: str, device_id: str) -> None:
            # Its own connection, as two HTTP requests would have.
            peer = DeviceRegistry(db_path=tmp_path / "mesh.db")
            gate.wait()
            try:
                peer.redeem_pairing(
                    token,
                    device_id=device_id,
                    public_key_b64=a_key(),
                    name="MacBook de Carlito",
                    platform="MACOS",
                    device_type="LAPTOP",
                )
                outcomes[tag] = "admitted"
            except MeshError:
                outcomes[tag] = "refused"

        threads = [
            threading.Thread(target=redeem, args=("first", "dev_" + "a" * 20)),
            threading.Thread(target=redeem, args=("second", "dev_" + "b" * 20)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outcomes.values()) == ["admitted", "refused"]
        assert len(registry.list_devices()) == 1

    def test_a_refusal_after_the_claim_leaves_the_invitation_usable(self, registry):
        """The claim is rolled back with the rest of the transaction.

        Otherwise presenting a revoked device — which is refused several
        checks later — would silently burn a perfectly good invitation and
        the user would have to mint another for no reason they could see.
        """
        enrol(registry, device_id="dev_pc", platform="WINDOWS", device_type="DESKTOP")
        registry.revoke("dev_pc")

        token = registry.create_pairing("PC")["pairingToken"]
        with pytest.raises(MeshError, match="révoqué"):
            registry.redeem_pairing(
                token,
                device_id="dev_pc",
                public_key_b64=a_key(),
                name="PC",
                platform="WINDOWS",
                device_type="DESKTOP",
            )
        # Same invitation, a device that may join: still good.
        device = registry.redeem_pairing(
            token,
            device_id="dev_portable",
            public_key_b64=a_key(),
            name="Portable",
            platform="MACOS",
            device_type="LAPTOP",
        )
        assert device["trustLevel"] == "TRUSTED"

    def test_an_expired_invitation_is_refused(self, registry, tmp_path):
        invitation = registry.create_pairing("Vieux PC")
        with sqlite3.connect(tmp_path / "mesh.db") as conn:
            conn.execute(
                "UPDATE mesh_pairings SET expires_at_ms = ?",
                (invitation["expiresAtMs"] - PAIRING_TTL_MS * 2,),
            )
            conn.commit()
        with pytest.raises(MeshError, match="expiré"):
            registry.redeem_pairing(
                invitation["pairingToken"],
                device_id="dev_pc",
                public_key_b64=a_key(),
                name="PC",
                platform="WINDOWS",
                device_type="DESKTOP",
            )

    def test_a_malformed_public_key_is_refused(self, registry):
        invitation = registry.create_pairing("Suspect")
        for bad in ("", "pas-du-base64!", base64.b64encode(b"trop court").decode()):
            with pytest.raises(MeshError):
                registry.redeem_pairing(
                    invitation["pairingToken"],
                    device_id="dev_bad",
                    public_key_b64=bad,
                    name="Suspect",
                    platform="MACOS",
                    device_type="LAPTOP",
                )


class TestCapabilityGrants:
    """Acceptance TEST I — a claim is not a grant."""

    def test_a_phone_claiming_host_automation_does_not_get_it(self, registry):
        device = enrol(
            registry,
            platform="IOS",
            capabilities=[
                "tasks.read",
                "app.navigate",
                "automation.approved.run",  # the lie
                "filesystem.workspace.write",  # also impossible on iOS
            ],
        )
        # What it claimed is recorded honestly…
        assert "automation.approved.run" in device["declaredCapabilities"]
        # …and what it GETS excludes what iOS cannot honour.
        assert "automation.approved.run" not in device["capabilities"]
        assert "filesystem.workspace.write" not in device["capabilities"]
        assert device["capabilities"] == ["app.navigate", "tasks.read"]

    def test_a_mac_gets_what_it_declares(self, registry):
        device = enrol(
            registry,
            device_id="dev_mac",
            platform="MACOS",
            device_type="LAPTOP",
            capabilities=["automation.approved.run", "tasks.write"],
        )
        assert set(device["capabilities"]) == {
            "automation.approved.run",
            "tasks.write",
        }

    def test_a_capability_the_device_never_claimed_is_never_granted(self, registry):
        device = enrol(registry, platform="MACOS", capabilities=["tasks.read"])
        # The ceiling is not the grant: macOS allows everything, this build
        # only implements one thing, so one thing is what it gets.
        assert device["capabilities"] == ["tasks.read"]

    def test_unknown_platforms_fall_back_to_read_only(self):
        granted = effective_capabilities(
            "TOASTER", ["tasks.write", "tasks.read", "automation.approved.run"]
        )
        assert granted == ("tasks.read",)

    def test_an_unknown_verb_is_dropped_not_fatal(self):
        granted = effective_capabilities("MACOS", ["tasks.read", "teleport.user"])
        assert granted == ("tasks.read",)

    def test_the_web_is_a_client_not_a_system_agent(self):
        assert not platform_allows("WEB", "automation.approved.run")
        assert not platform_allows("WEB", "filesystem.workspace.read")
        assert platform_allows("WEB", "app.navigate")


class TestRevocation:
    def test_a_revoked_device_disappears_from_the_active_list(self, registry):
        enrol(registry)
        registry.revoke("dev_phone")
        assert registry.list_devices() == []
        assert len(registry.list_devices(include_revoked=True)) == 1

    def test_a_revoked_device_cannot_verify_commands(self, registry):
        enrol(registry)
        assert registry.public_key_of("dev_phone") is not None
        registry.revoke("dev_phone")
        # Returning None rather than the key makes it impossible to accept a
        # signature from a device the user deliberately cut off.
        assert registry.public_key_of("dev_phone") is None

    def test_revocation_cannot_be_laundered_by_re_pairing(self, registry):
        """Acceptance TEST H, hardened: a fresh invitation is not amnesty."""
        key = a_key()
        enrol(registry, key=key)
        registry.revoke("dev_phone")
        invitation = registry.create_pairing("iPhone de Carlito")
        with pytest.raises(MeshError, match="révoqué"):
            registry.redeem_pairing(
                invitation["pairingToken"],
                device_id="dev_phone",
                public_key_b64=key,
                name="iPhone de Carlito",
                platform="IOS",
                device_type="PHONE",
            )

    def test_forgetting_a_device_allows_a_clean_re_pairing(self, registry):
        enrol(registry)
        registry.revoke("dev_phone")
        registry.forget("dev_phone")
        again = enrol(registry)
        assert again["trustLevel"] == "TRUSTED"

    def test_a_known_id_with_a_different_key_is_refused(self, registry):
        """Impostor or reinstall — either way the human decides, not the code."""
        enrol(registry)
        invitation = registry.create_pairing("iPhone de Carlito")
        with pytest.raises(MeshError, match="autre clé"):
            registry.redeem_pairing(
                invitation["pairingToken"],
                device_id="dev_phone",
                public_key_b64=a_key(),  # different key, same id
                name="iPhone de Carlito",
                platform="IOS",
                device_type="PHONE",
            )

    def test_a_revoked_device_cannot_redeclare_capabilities(self, registry):
        enrol(registry, platform="MACOS", capabilities=["tasks.read"])
        registry.revoke("dev_phone")
        with pytest.raises(MeshError, match="autorisé"):
            registry.declare_capabilities("dev_phone", ["automation.approved.run"])
