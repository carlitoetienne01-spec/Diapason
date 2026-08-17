"""The half of the mesh that reaches a phone.

A device that cannot be dialled comes and fetches instead. Two things have
to hold for that to be worth having: the fetch must prove who is fetching as
strictly as any command does, and what the user is told about a queued
command must stay true — « il le récupérera dans quelques secondes » is a
promise, and a promise that turns out false is worse than a refusal.
"""

from __future__ import annotations

import base64

import pytest

from diapason.mesh.commands import build_command, now_ms, sign_command
from diapason.mesh.dispatch import dispatch_command
from diapason.mesh.identity import canonical_bytes
from diapason.mesh.pull import (
    MAX_PER_POLL,
    PullRejected,
    build_ack,
    build_poll,
    collect_for_device,
    device_collects_its_own,
    record_ack,
)
from diapason.mesh.queue import CommandQueue
from diapason.mesh.registry import DeviceRegistry
from diapason.mesh.signed import MAX_SIGNED_SKEW_MS
from diapason.security.signing import generate_keypair, sign_b64

OWNER = "owner_" + "c" * 32
HOST = "mac_de_carlito"
PHONE = "dev_iphone"
OTHER = "dev_ipad"


@pytest.fixture
def phone_key():
    return generate_keypair()


@pytest.fixture
def mesh(tmp_path, phone_key):
    registry = DeviceRegistry(db_path=tmp_path / "mesh.db")
    queue = CommandQueue(db_path=tmp_path / "mesh.db")
    for device_id, name, key in [
        (PHONE, "iPhone de Carlito", phone_key),
        (OTHER, "iPad du salon", generate_keypair()),
    ]:
        invitation = registry.create_pairing(name)
        registry.redeem_pairing(
            invitation["pairingToken"],
            device_id=device_id,
            public_key_b64=base64.b64encode(key.public_key).decode("ascii"),
            name=name,
            platform="IOS",
            device_type="PHONE",
            declared_capabilities=[
                "app.navigate",
                "app.show_resource",
                "app.open",
                "notifications.show",
            ],
        )
    return registry, queue


def signed(payload: dict, fields, key) -> dict:
    body = dict(payload)
    body["signature"] = sign_b64(
        canonical_bytes({f: body.get(f) for f in fields}), key.private_key
    )
    return body


def poll(key, **overrides) -> dict:
    from diapason.mesh.pull import _POLL_FIELDS

    body = build_poll(owner_id=OWNER, device_id=PHONE, app_state="foreground")
    body.update(overrides)
    return signed(body, _POLL_FIELDS, key)


def ack(key, results, **overrides) -> dict:
    from diapason.mesh.pull import _ACK_FIELDS

    body = build_ack(owner_id=OWNER, device_id=PHONE, results=results)
    body.update(overrides)
    return signed(body, _ACK_FIELDS, key)


def collect(mesh, body):
    registry, queue = mesh
    return collect_for_device(
        body,
        registry=registry,
        queue=queue,
        local_owner_id=OWNER,
        local_device_id=HOST,
    )


def acknowledge(mesh, body):
    registry, queue = mesh
    return record_ack(
        body,
        registry=registry,
        queue=queue,
        local_owner_id=OWNER,
        local_device_id=HOST,
    )


def queue_one(mesh, *, target=PHONE, tool="app.navigate", args=None):
    registry, queue = mesh
    return dispatch_command(
        target_device_id=target,
        tool=tool,
        arguments=args or {"route": "success://today"},
        registry=registry,
        queue=queue,
        transport=lambda c, d: {"status": "SUCCESS"},
    )


class TestOnlyAProvenDeviceCollects:
    def test_a_signed_poll_returns_what_is_waiting(self, mesh, phone_key):
        collect(mesh, poll(phone_key))  # first poll marks it as a pull device
        queue_one(mesh)
        out = collect(mesh, poll(phone_key, sentAtMs=now_ms() + 1))
        assert out["count"] == 1
        assert out["commands"][0]["tool"] == "app.navigate"
        # The envelope must arrive intact: the phone verifies it itself.
        assert out["commands"][0]["signature"]

    def test_an_unsigned_poll_collects_nothing(self, mesh, phone_key):
        body = poll(phone_key)
        body["signature"] = ""
        with pytest.raises(PullRejected, match="pas signée"):
            collect(mesh, body)

    def test_a_stranger_cannot_collect_someone_else_s_commands(self, mesh):
        with pytest.raises(PullRejected, match="signature"):
            collect(mesh, poll(generate_keypair()))

    def test_a_revoked_device_collects_nothing(self, mesh, phone_key):
        registry, _ = mesh
        collect(mesh, poll(phone_key))
        registry.revoke(PHONE)
        with pytest.raises(PullRejected, match="pas autorisé"):
            collect(mesh, poll(phone_key, sentAtMs=now_ms() + 1))

    def test_a_poll_from_another_fleet_is_refused(self, mesh, phone_key):
        with pytest.raises(PullRejected, match="autre ensemble"):
            collect(mesh, poll(phone_key, ownerId="owner_" + "d" * 32))

    def test_a_replayed_poll_learns_nothing(self, mesh, phone_key):
        """A captured poll must not become a way to read the queue later."""
        body = poll(phone_key)
        collect(mesh, body)
        queue_one(mesh)
        with pytest.raises(PullRejected, match="déjà été vue|dépassée"):
            collect(mesh, dict(body))

    def test_a_stale_poll_is_refused(self, mesh, phone_key):
        old = poll(phone_key, sentAtMs=now_ms() - MAX_SIGNED_SKEW_MS - 5_000)
        with pytest.raises(PullRejected, match="trop ancienne"):
            collect(mesh, old)


class TestCollectingIsAlsoBeingSeen:
    def test_polling_records_presence(self, mesh, phone_key):
        out = collect(mesh, poll(phone_key))
        assert out["presence"]["deviceId"] == PHONE
        from diapason.mesh.presence import presence_of

        assert presence_of(out["presence"])["state"] == "ONLINE"

    def test_polling_marks_the_device_as_one_that_fetches(self, mesh, phone_key):
        registry, _ = mesh
        assert device_collects_its_own(registry.get(PHONE)) is False
        collect(mesh, poll(phone_key))
        assert device_collects_its_own(registry.get(PHONE)) is True

    def test_a_device_that_never_polled_is_not_assumed_to(self, mesh):
        """The trap this avoids: a desktop that has simply not announced yet
        has no address either, and would otherwise sit under a promise that
        it will collect — which it never will."""
        registry, _ = mesh
        silent = registry.get(OTHER)
        assert not silent.get("address")
        assert device_collects_its_own(silent) is False


class TestWhatTheUserIsToldStaysTrue:
    def test_an_awake_phone_is_promised_seconds_not_failure(self, mesh, phone_key):
        collect(mesh, poll(phone_key))
        out = queue_one(mesh)
        assert out["status"] == "QUEUED"
        assert "quelques secondes" in out["userSafeMessage"]
        assert "hors ligne" not in out["userSafeMessage"]
        assert "n'a pas été effectuée" not in out["userSafeMessage"]

    def test_a_sleeping_phone_is_promised_its_waking_not_never(
        self, mesh, phone_key, tmp_path
    ):
        import sqlite3

        collect(mesh, poll(phone_key))
        registry, _ = mesh
        with sqlite3.connect(registry.db_path) as conn:
            conn.execute(
                "UPDATE mesh_devices SET last_seen_at_ms=? WHERE device_id=?",
                (now_ms() - 86_400_000, PHONE),
            )
            conn.commit()
        out = queue_one(mesh)
        assert out["status"] == "QUEUED"
        assert "à son réveil" in out["userSafeMessage"]

    def test_a_command_for_a_phone_never_touches_the_wire(self, mesh, phone_key):
        collect(mesh, poll(phone_key))
        registry, queue = mesh
        dialled = []
        dispatch_command(
            target_device_id=PHONE,
            tool="app.navigate",
            arguments={"route": "success://today"},
            registry=registry,
            queue=queue,
            transport=lambda c, d: dialled.append(1),
        )
        assert not dialled


class TestReportingBack:
    def test_a_collected_command_is_settled_by_its_acknowledgement(
        self, mesh, phone_key
    ):
        registry, queue = mesh
        collect(mesh, poll(phone_key))
        sent = queue_one(mesh)
        collect(mesh, poll(phone_key, sentAtMs=now_ms() + 1))
        acknowledge(
            mesh,
            ack(
                phone_key,
                [
                    {
                        "commandId": sent["commandId"],
                        "status": "SUCCESS",
                        "userSafeMessage": "Écran ouvert.",
                    }
                ],
            ),
        )
        assert queue.get(sent["commandId"])["status"] == "SUCCESS"

    def test_a_device_cannot_settle_a_command_addressed_elsewhere(
        self, mesh, phone_key
    ):
        """Otherwise a paired phone could tell the user that something
        happened on a machine that never heard of it."""
        registry, queue = mesh
        collect(mesh, poll(phone_key))
        # Queued directly, so it is genuinely unsettled when the wrong device
        # tries to speak for it.
        for_other = queue.enqueue(
            sign_command(
                build_command(
                    owner_id=OWNER,
                    origin_device_id=HOST,
                    target_device_id=OTHER,
                    tool="app.navigate",
                    arguments={"route": "success://today"},
                    requires_confirmation=False,
                )
            ),
            status="QUEUED",
        )
        out = acknowledge(
            mesh,
            ack(
                phone_key, [{"commandId": for_other["commandId"], "status": "SUCCESS"}]
            ),
        )
        assert out["recorded"] == 0
        assert queue.get(for_other["commandId"])["status"] == "QUEUED"

    def test_an_invented_status_is_ignored(self, mesh, phone_key):
        registry, queue = mesh
        collect(mesh, poll(phone_key))
        sent = queue_one(mesh)
        out = acknowledge(
            mesh,
            ack(phone_key, [{"commandId": sent["commandId"], "status": "PARFAIT"}]),
        )
        assert out["recorded"] == 0
        assert queue.get(sent["commandId"])["status"] == "QUEUED"

    def test_a_settled_command_is_not_rewritten_by_a_late_report(self, mesh, phone_key):
        """Re-reporting is normal after a lost response, and must not change
        what the user was already told."""
        registry, queue = mesh
        collect(mesh, poll(phone_key))
        sent = queue_one(mesh)
        first = [
            {
                "commandId": sent["commandId"],
                "status": "SUCCESS",
                "userSafeMessage": "C'est fait.",
            }
        ]
        acknowledge(mesh, ack(phone_key, first))
        acknowledge(
            mesh,
            ack(
                phone_key,
                [{"commandId": sent["commandId"], "status": "FAILED"}],
                sentAtMs=now_ms() + 1,
            ),
        )
        settled = queue.get(sent["commandId"])
        assert settled["status"] == "SUCCESS"
        assert settled["userSafeMessage"] == "C'est fait."

    def test_an_unsigned_acknowledgement_changes_nothing(self, mesh, phone_key):
        registry, queue = mesh
        collect(mesh, poll(phone_key))
        sent = queue_one(mesh)
        body = ack(phone_key, [{"commandId": sent["commandId"], "status": "SUCCESS"}])
        body["signature"] = ""
        with pytest.raises(PullRejected):
            acknowledge(mesh, body)
        assert queue.get(sent["commandId"])["status"] == "QUEUED"

    def test_a_tampered_result_list_invalidates_the_signature(self, mesh, phone_key):
        registry, queue = mesh
        collect(mesh, poll(phone_key))
        sent = queue_one(mesh)
        body = ack(phone_key, [{"commandId": sent["commandId"], "status": "FAILED"}])
        body["results"][0]["status"] = "SUCCESS"  # changed after signing
        with pytest.raises(PullRejected, match="signature"):
            acknowledge(mesh, body)

    def test_an_unknown_command_id_is_ignored_not_created(self, mesh, phone_key):
        collect(mesh, poll(phone_key))
        out = acknowledge(
            mesh,
            ack(phone_key, [{"commandId": "cmd_inexistante", "status": "SUCCESS"}]),
        )
        assert out["recorded"] == 0


class TestBacklogIsBounded:
    def test_one_poll_carries_at_most_a_bounded_batch(self, mesh, phone_key):
        registry, queue = mesh
        collect(mesh, poll(phone_key))
        for index in range(MAX_PER_POLL + 5):
            command = build_command(
                owner_id=OWNER,
                origin_device_id=HOST,
                target_device_id=PHONE,
                tool="app.navigate",
                arguments={"route": f"success://notes/n{index}"},
                requires_confirmation=False,
            )
            queue.enqueue(sign_command(command), status="QUEUED")
        out = collect(mesh, poll(phone_key, sentAtMs=now_ms() + 1))
        assert out["count"] == MAX_PER_POLL
