"""The signed command envelope and the eleven checks of spec §9.

Each test names the attack it refuses. A command bus that passes only the
happy path is not a bus, it is a demo.
"""

from __future__ import annotations

import base64

import pytest

from diapason.mesh.commands import (
    MAX_CLOCK_SKEW_MS,
    CommandRejected,
    NonceStore,
    RemoteCommand,
    build_command,
    now_ms,
    verify_command,
)
from diapason.mesh.registry import DeviceRegistry
from diapason.mesh.tools import (
    FORBIDDEN_PARAMETER_NAMES,
    REMOTE_TOOLS,
    list_remote_tools,
)
from diapason.security.signing import generate_keypair, sign_b64

LOCAL_DEVICE = "dev_this_mac"
LOCAL_OWNER = "owner_shared_fleet_identity"
REMOTE_DEVICE = "dev_the_phone"


@pytest.fixture
def world(tmp_path):
    """A registry holding one trusted peer, plus that peer's private key."""
    registry = DeviceRegistry(tmp_path / "mesh.db")
    nonces = NonceStore(tmp_path / "mesh.db")

    peer_keys = generate_keypair()
    invitation = registry.create_pairing("Téléphone")
    registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=REMOTE_DEVICE,
        public_key_b64=base64.b64encode(peer_keys.public_key).decode(),
        name="Téléphone",
        platform="IOS",
        device_type="PHONE",
        declared_capabilities=["app.navigate", "app.show_resource"],
    )
    # This device too, so capability checks have something to read.
    invitation2 = registry.create_pairing("Ce Mac")
    registry.redeem_pairing(
        invitation2["pairingToken"],
        device_id=LOCAL_DEVICE,
        public_key_b64=base64.b64encode(generate_keypair().public_key).decode(),
        name="Ce Mac",
        platform="MACOS",
        device_type="LAPTOP",
        declared_capabilities=["app.navigate", "app.show_resource", "app.open"],
    )
    return registry, nonces, peer_keys


def sign_as_peer(command: RemoteCommand, private_key: bytes) -> dict:
    """Sign exactly as the sending device would."""
    from diapason.mesh.identity import canonical_bytes

    payload = command.to_dict(with_signature=False)
    signature = sign_b64(canonical_bytes(payload), private_key)
    return {**payload, "signature": signature}


def a_command(**overrides) -> RemoteCommand:
    base = dict(
        owner_id=LOCAL_OWNER,
        origin_device_id=REMOTE_DEVICE,
        target_device_id=LOCAL_DEVICE,
        tool="app.navigate",
        arguments={"route": "success://projects/flashprime"},
    )
    base.update(overrides)
    return build_command(**base)


def check(raw, world, **kwargs):
    registry, nonces, _ = world
    return verify_command(
        raw,
        registry=registry,
        local_device_id=LOCAL_DEVICE,
        local_owner_id=LOCAL_OWNER,
        nonces=nonces,
        **kwargs,
    )


class TestHappyPath:
    def test_a_properly_signed_command_is_accepted(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        verified = check(raw, world)
        assert verified.tool == "app.navigate"
        assert verified.arguments["route"] == "success://projects/flashprime"


class TestSignature:
    def test_an_unsigned_command_is_refused(self, world):
        raw = a_command().to_dict(with_signature=False)
        with pytest.raises(CommandRejected, match="pas signée") as exc:
            check(raw, world)
        assert exc.value.code == "DENIED"

    def test_a_tampered_argument_breaks_the_signature(self, world):
        """The whole point: sign the envelope, not a summary of it."""
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        raw["arguments"] = {"route": "success://projects/QUELQUE_CHOSE_DAUTRE"}
        with pytest.raises(CommandRejected, match="signature"):
            check(raw, world)

    def test_a_command_signed_by_a_stranger_is_refused(self, world):
        stranger = generate_keypair()
        raw = sign_as_peer(a_command(), stranger.private_key)
        with pytest.raises(CommandRejected, match="signature"):
            check(raw, world)

    def test_a_revoked_device_can_no_longer_command(self, world):
        """Acceptance TEST H at the bus level."""
        registry, _, keys = world
        registry.revoke(REMOTE_DEVICE)
        raw = sign_as_peer(a_command(), keys.private_key)
        with pytest.raises(CommandRejected, match="pas autorisé"):
            check(raw, world)


class TestReplay:
    def test_a_nonce_may_be_spent_only_once(self, world):
        """Replaying a captured command is how 'open this' becomes 'open this
        forty times'. The signature stays perfect; the nonce does not."""
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        check(raw, world)
        with pytest.raises(CommandRejected, match="déjà été reçue"):
            check(raw, world)

    def test_a_rejected_command_does_not_burn_its_nonce(self, world):
        """The nonce is spent LAST, so a command refused for another reason
        leaves the legitimate sender able to retry."""
        _, _, keys = world
        command = a_command(tool="app.open")  # phone lacks app.open capability
        raw = sign_as_peer(command, keys.private_key)
        with pytest.raises(CommandRejected):
            check(raw, world)
        # Same nonce, now on a tool the device does have: still accepted.
        second = RemoteCommand(**{**a_command().__dict__, "nonce": command.nonce})
        raw2 = sign_as_peer(second, keys.private_key)
        assert check(raw2, world).nonce == command.nonce


class TestAddressing:
    def test_a_command_for_another_device_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(
            a_command(target_device_id="dev_someone_else"), keys.private_key
        )
        with pytest.raises(CommandRejected, match="ne s'adresse pas"):
            check(raw, world)

    def test_a_command_from_another_fleet_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(owner_id="owner_someone_else"), keys.private_key)
        with pytest.raises(CommandRejected, match="autre ensemble"):
            check(raw, world)

    def test_an_unknown_origin_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(origin_device_id="dev_ghost"), keys.private_key)
        with pytest.raises(CommandRejected, match="pas autorisé"):
            check(raw, world)


class TestExpiry:
    def test_an_expired_command_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(ttl_ms=1_000), keys.private_key)
        future = now_ms() + 1_000 + MAX_CLOCK_SKEW_MS + 1_000
        with pytest.raises(CommandRejected, match="expiré") as exc:
            check(raw, world, now=future)
        assert exc.value.code == "EXPIRED"

    def test_clock_skew_is_tolerated_within_bounds(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(ttl_ms=1_000), keys.private_key)
        # Slightly past expiry but inside the skew window: still honoured.
        assert check(raw, world, now=now_ms() + 1_000 + MAX_CLOCK_SKEW_MS - 500)

    def test_a_command_from_the_future_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(), keys.private_key)
        raw["createdAtMs"] = now_ms() + MAX_CLOCK_SKEW_MS + 60_000
        raw["expiresAtMs"] = raw["createdAtMs"] + 60_000
        # Re-sign so it fails on the date, not the signature.
        raw = sign_as_peer(RemoteCommand.from_dict(raw), keys.private_key)
        with pytest.raises(CommandRejected, match="futur"):
            check(raw, world)


class TestToolDiscipline:
    def test_an_unknown_tool_is_unsupported(self, world):
        """Acceptance TEST J: the assistant asking for a shell finds nothing."""
        _, _, keys = world
        raw = sign_as_peer(
            a_command(tool="system.execute_shell", arguments={}), keys.private_key
        )
        with pytest.raises(CommandRejected, match="n'existe pas") as exc:
            check(raw, world)
        assert exc.value.code == "UNSUPPORTED"

    def test_an_unknown_parameter_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(
            a_command(
                arguments={"route": "success://today", "extra": "rm -rf /"},
            ),
            keys.private_key,
        )
        with pytest.raises(CommandRejected, match="non reconnu"):
            check(raw, world)

    def test_a_missing_required_parameter_is_refused(self, world):
        _, _, keys = world
        raw = sign_as_peer(a_command(arguments={}), keys.private_key)
        with pytest.raises(CommandRejected, match="obligatoire"):
            check(raw, world)

    def test_an_enum_is_enforced(self, world):
        _, _, keys = world
        raw = sign_as_peer(
            a_command(
                tool="app.show_resource",
                arguments={"resourceType": "database", "resourceId": "x"},
            ),
            keys.private_key,
        )
        with pytest.raises(CommandRejected, match="non autorisée"):
            check(raw, world)

    def test_a_capability_this_platform_forbids_is_unsupported(
        self, world, monkeypatch
    ):
        """The receiver's ceiling comes from its PLATFORM, not from a
        registry row.

        The earlier version of this test read the ceiling from a registry
        entry for the local device — which the fixture helpfully created and
        the real world never does. A device is not listed in its own
        registry, so the lookup returned None and the check silently allowed
        everything. The test was constructing the only world in which the
        code worked.
        """
        _, _, keys = world
        import diapason.mesh.capabilities as caps

        monkeypatch.setattr(
            caps, "local_capabilities", lambda: frozenset({"app.navigate"})
        )
        raw = sign_as_peer(
            a_command(tool="notifications.show", arguments={"title": "Bonjour"}),
            keys.private_key,
        )
        with pytest.raises(CommandRejected, match="ne peut pas exécuter"):
            check(raw, world)

    def test_the_receiver_does_not_take_the_sender_s_word_for_its_own_limits(
        self, world
    ):
        """What the sender recorded about us is exactly what an attacker
        would have tampered with, so it cannot be what authorises us."""
        registry, _, keys = world
        # Wipe every capability the registry believes this Mac has.
        registry.declare_capabilities(LOCAL_DEVICE, [])
        raw = sign_as_peer(
            a_command(tool="app.navigate", arguments={"route": "success://today"}),
            keys.private_key,
        )
        # Still accepted: macOS genuinely allows it, and that is our call.
        assert check(raw, world).tool == "app.navigate"


class TestNoUniversalTool:
    """Spec §21, enforced on the whole registry rather than per review."""

    def test_no_tool_accepts_a_passthrough_parameter(self):
        for name, spec in REMOTE_TOOLS.items():
            offending = set(spec.parameters) & FORBIDDEN_PARAMETER_NAMES
            assert not offending, (
                f"L'outil « {name} » expose un paramètre fourre-tout : {offending}. "
                "Un outil distant doit nommer explicitement ce qu'il accepte."
            )

    def test_every_parameter_declares_a_concrete_type(self):
        for name, spec in REMOTE_TOOLS.items():
            for key, rule in spec.parameters.items():
                assert rule.get("type") in {"string", "integer", "boolean"}, (
                    f"« {name}.{key} » n'a pas de type borné."
                )

    def test_every_tool_maps_to_a_known_capability(self):
        from diapason.mesh.capabilities import ALL_CAPABILITIES

        for name, spec in REMOTE_TOOLS.items():
            assert spec.capability in ALL_CAPABILITIES, (
                f"« {name} » réclame une capacité inconnue : {spec.capability}."
            )

    def test_every_tool_declares_an_offline_policy(self):
        allowed = {"DROP_IF_OFFLINE", "QUEUE_UNTIL_EXPIRATION", "REQUIRE_ONLINE"}
        for name, spec in REMOTE_TOOLS.items():
            assert spec.offline_policy in allowed, f"« {name} » : politique inconnue."

    def test_the_catalogue_is_advertisable(self):
        catalogue = list_remote_tools()
        assert catalogue
        assert all("name" in entry and "parameters" in entry for entry in catalogue)
