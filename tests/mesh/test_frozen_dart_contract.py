"""The three rules the Dart client cannot survive us breaking.

Succès reimplements the canonical encoding by hand and enforces one check out
of eleven. Three things it therefore reads on blind faith: the protocol
version (it writes ``1`` literally), the exact list of fields a signature
covers (a field it does not know arrives as ``null`` and invalidates every
poll), and the absence of floats in a signed envelope (Python writes
``1e-07`` where Dart writes ``1e-7``, so the two sides sign different bytes
and nothing says why).

CLAUDE.md §4 states all three. Until this file, **nothing enforced any of
them**: no test named ``COMMAND_VERSION``, ``PULL_VERSION`` or
``PRESENCE_VERSION``, and the tests that use the signed-field tuples *import*
them — so adding a field made the test sign with the new list and stay green
while the phone kept sending the old one.

A rule written in a document is a wish. This file is the ratchet.
"""

from __future__ import annotations

from diapason.mesh.beacon import _SIGNED_FIELDS, PRESENCE_VERSION, build_beacon
from diapason.mesh.commands import COMMAND_VERSION
from diapason.mesh.pull import (
    _ACK_FIELDS,
    _POLL_FIELDS,
    PULL_VERSION,
    build_ack,
    build_poll,
)

OWNER = "owner_" + "a" * 32
DEVICE = "dev_le_pc"

# Why literals and not imports: importing the constant makes the test agree
# with whatever the code says, which is the opposite of a contract. These are
# the values the deployed Dart client knows.
POLL_FIELDS_DEPLOYED = (
    "version",
    "ownerId",
    "deviceId",
    "appState",
    "capabilities",
    "appVersion",
    "sentAtMs",
)
ACK_FIELDS_DEPLOYED = (
    "version",
    "ownerId",
    "deviceId",
    "results",
    "sentAtMs",
)
BEACON_FIELDS_DEPLOYED = (
    "version",
    "ownerId",
    "deviceId",
    "appState",
    "transport",
    "address",
    "capabilities",
    "appVersion",
    "sentAtMs",
)

_POURQUOI_UN = (
    "The Dart client writes this version as a literal 1. Bumping it before a "
    "client accepting two versions is deployed silences every phone in the "
    "fleet, with no error anyone can read."
)


class TestTheVersionsTheDartClientHardCodes:
    """CLAUDE.md §4 rule 2 — do not bump before a two-version client ships."""

    def test_the_command_version_is_still_one(self):
        assert COMMAND_VERSION == 1, _POURQUOI_UN

    def test_the_pull_version_is_still_one(self):
        assert PULL_VERSION == 1, _POURQUOI_UN

    def test_the_presence_version_is_still_one(self):
        assert PRESENCE_VERSION == 1, _POURQUOI_UN


class TestTheSignedFieldListsAreFrozen:
    """CLAUDE.md §4 rule 3 — a field the phone does not know arrives as null.

    The signature covers an explicit list. Add one field here and every poll
    the fleet sends stops verifying, because Dart omits it and the server
    signs a key whose value is ``None``.
    """

    def test_the_poll_signs_exactly_the_seven_fields_dart_knows(self):
        assert _POLL_FIELDS == POLL_FIELDS_DEPLOYED, (
            "the poll's signed field list changed; the deployed Dart client "
            "sends exactly " + repr(POLL_FIELDS_DEPLOYED)
        )

    def test_the_ack_signs_exactly_the_five_fields_dart_knows(self):
        assert _ACK_FIELDS == ACK_FIELDS_DEPLOYED, (
            "the ack's signed field list changed; the deployed Dart client "
            "sends exactly " + repr(ACK_FIELDS_DEPLOYED)
        )

    def test_the_beacon_signs_exactly_the_nine_fields_dart_knows(self):
        assert _SIGNED_FIELDS == BEACON_FIELDS_DEPLOYED, (
            "the beacon's signed field list changed; the deployed Dart client "
            "sends exactly " + repr(BEACON_FIELDS_DEPLOYED)
        )


class TestNoFloatEverReachesASignedEnvelope:
    """CLAUDE.md §4 rule 1 — Python writes 1e-07, Dart writes 1e-7.

    ``canonical_bytes`` does not refuse floats: it serialises them, so the
    guarantee lives entirely in the builders coercing their values. That is
    exactly the kind of guarantee that decays without a test, and its failure
    mode is an invalid signature with no message attached to it.
    """

    @staticmethod
    def _floats_in(envelope, fields):
        # bool is an int and is fine; float is not, at any depth.
        def walk(value, path):
            if isinstance(value, float):
                return [path]
            if isinstance(value, dict):
                return [p for k, v in value.items() for p in walk(v, f"{path}.{k}")]
            if isinstance(value, (list, tuple)):
                return [p for i, v in enumerate(value) for p in walk(v, f"{path}[{i}]")]
            return []

        return [p for f in fields for p in walk(envelope.get(f), f)]

    def test_a_poll_carries_no_float(self):
        envelope = build_poll(
            owner_id=OWNER,
            device_id=DEVICE,
            app_state="foreground",
            capabilities=["mesh_send"],
            app_version="1.0.0",
        )
        assert self._floats_in(envelope, _POLL_FIELDS) == [], (
            "a float in a signed poll makes Dart and Python sign different "
            "bytes; every collection from every phone fails silently"
        )

    def test_an_ack_carries_no_float(self):
        envelope = build_ack(
            owner_id=OWNER,
            device_id=DEVICE,
            results=[{"commandId": "cmd_1", "status": "SUCCESS"}],
        )
        assert self._floats_in(envelope, _ACK_FIELDS) == [], (
            "a float in a signed ack makes the report unverifiable, and the "
            "command stays pending forever on the sender's side"
        )

    def test_a_beacon_carries_no_float(self):
        envelope = build_beacon(
            owner_id=OWNER,
            device_id=DEVICE,
            app_state="foreground",
            transport="lan",
            address="192.168.1.20:8001",
            capabilities=["mesh_send"],
            app_version="1.0.0",
        )
        assert self._floats_in(envelope, _SIGNED_FIELDS) == [], (
            "a float in a signed beacon makes the device look permanently "
            "unreachable, which the interface reports as an honest absence"
        )

    def test_the_timestamp_is_an_int_and_not_a_float(self):
        # The likeliest way a float gets in: time.time() * 1000 instead of the
        # integer millisecond clock. Named on its own so the failure says so.
        for name, envelope in (
            ("poll", build_poll(owner_id=OWNER, device_id=DEVICE)),
            ("ack", build_ack(owner_id=OWNER, device_id=DEVICE, results=[])),
            ("beacon", build_beacon(owner_id=OWNER, device_id=DEVICE)),
        ):
            assert isinstance(envelope["sentAtMs"], int), (
                f"{name}.sentAtMs is a float — time.time() * 1000 rather than "
                "the integer millisecond clock"
            )
            assert not isinstance(envelope["sentAtMs"], bool), (
                f"{name}.sentAtMs is a bool"
            )
