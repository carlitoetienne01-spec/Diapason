"""The half of « partira dès son retour » that makes the sentence true.

An adversarial audit found this missing: nothing in production ever re-read
the queue, so a command for a sleeping laptop sat QUEUED until it expired
while the user had been told it would arrive on the device's return. The
message was the flagship of the honesty contract and it was false.

These tests exist to keep it true.
"""

from __future__ import annotations

import base64
import sqlite3

import pytest

from diapason.mesh.commands import build_command, now_ms, sign_command
from diapason.mesh.dispatch import dispatch_command, flush_pending
from diapason.mesh.queue import CommandQueue
from diapason.mesh.registry import DeviceRegistry
from diapason.mesh.transport import TransportError
from diapason.security.signing import generate_keypair

OWNER = "owner_" + "e" * 32
HOST = "mac_de_carlito"
LAPTOP = "dev_portable"
PHONE = "dev_iphone"


@pytest.fixture
def mesh(tmp_path):
    registry = DeviceRegistry(db_path=tmp_path / "mesh.db")
    queue = CommandQueue(db_path=tmp_path / "mesh.db")
    for device_id, name, platform, kind in [
        (LAPTOP, "Portable du salon", "MACOS", "LAPTOP"),
        (PHONE, "iPhone de Carlito", "IOS", "PHONE"),
    ]:
        invitation = registry.create_pairing(name)
        registry.redeem_pairing(
            invitation["pairingToken"],
            device_id=device_id,
            public_key_b64=base64.b64encode(generate_keypair().public_key).decode(),
            name=name,
            platform=platform,
            device_type=kind,
            declared_capabilities=[
                "app.navigate",
                "app.show_resource",
                "app.open",
                "notifications.show",
            ],
        )
    return registry, queue


def sleep_device(registry, device_id):
    with sqlite3.connect(registry.db_path) as conn:
        conn.execute(
            "UPDATE mesh_devices SET last_seen_at_ms=? WHERE device_id=?",
            (now_ms() - 86_400_000, device_id),
        )
        conn.commit()


def wake_device(registry, device_id, *, address="http://192.168.1.30:8000"):
    registry.heartbeat(device_id, transport="lan", address=address)


def queue_for(mesh, device_id, *, tool="notifications.show"):
    registry, queue = mesh
    return dispatch_command(
        target_device_id=device_id,
        tool=tool,
        arguments={"title": "Diapason", "body": "Bilan du soir"},
        registry=registry,
        queue=queue,
        transport=lambda c, d: {"status": "SUCCESS"},
    )


class TestThePromiseIsKept:
    def test_a_queued_command_leaves_when_the_device_comes_back(self, mesh):
        registry, queue = mesh
        wake_device(registry, LAPTOP)
        sleep_device(registry, LAPTOP)

        queued = queue_for(mesh, LAPTOP)
        assert queued["status"] == "QUEUED"
        assert "dès son retour" in queued["userSafeMessage"]

        # It comes back.
        wake_device(registry, LAPTOP)
        sent = []
        out = flush_pending(
            registry=registry,
            queue=queue,
            transport=lambda c, d: (
                sent.append(c)
                or {"status": "SUCCESS", "userSafeMessage": "C'est fait."}
            ),
        )
        assert out["delivered"] == 1
        assert len(sent) == 1
        assert queue.get(queued["commandId"])["status"] == "SUCCESS"

    def test_the_command_travels_verbatim_not_re_signed(self, mesh):
        """Re-signing would mint a different command, and the receiver's
        replay protection could no longer tell a retry from a duplicate."""
        registry, queue = mesh
        wake_device(registry, LAPTOP)
        sleep_device(registry, LAPTOP)
        queued = queue_for(mesh, LAPTOP)
        original = queue.envelope_of(queued["commandId"])

        wake_device(registry, LAPTOP)
        sent = []
        flush_pending(
            registry=registry,
            queue=queue,
            transport=lambda c, d: sent.append(c) or {"status": "SUCCESS"},
        )
        assert sent[0].command_id == original.command_id
        assert sent[0].signature == original.signature
        assert sent[0].nonce == original.nonce


class TestItDoesNotOverreach:
    def test_a_still_sleeping_device_is_left_alone(self, mesh):
        registry, queue = mesh
        wake_device(registry, LAPTOP)
        sleep_device(registry, LAPTOP)
        queue_for(mesh, LAPTOP)

        sent = []
        out = flush_pending(
            registry=registry, queue=queue, transport=lambda c, d: sent.append(c)
        )
        assert out["delivered"] == 0
        assert not sent

    def test_a_polling_device_is_never_pushed_to(self, mesh):
        """It fetches its own. Delivering as well is not a courtesy — it is
        the same command arriving twice by two paths."""
        registry, queue = mesh
        registry.heartbeat_signed(PHONE, transport="pull", sent_at_ms=now_ms())
        queued = queue_for(mesh, PHONE)
        assert queued["status"] == "QUEUED"

        sent = []
        out = flush_pending(
            registry=registry, queue=queue, transport=lambda c, d: sent.append(c)
        )
        assert out["delivered"] == 0
        assert not sent

    def test_a_revoked_device_is_not_drained_to(self, mesh):
        registry, queue = mesh
        wake_device(registry, LAPTOP)
        sleep_device(registry, LAPTOP)
        queue_for(mesh, LAPTOP)
        wake_device(registry, LAPTOP)
        registry.revoke(LAPTOP)

        sent = []
        out = flush_pending(
            registry=registry, queue=queue, transport=lambda c, d: sent.append(c)
        )
        assert out["delivered"] == 0
        assert not sent

    def test_an_expired_command_is_settled_not_delivered(self, mesh):
        registry, queue = mesh
        wake_device(registry, LAPTOP)
        sleep_device(registry, LAPTOP)
        queued = queue_for(mesh, LAPTOP)
        with sqlite3.connect(queue.db_path) as conn:
            conn.execute(
                "UPDATE mesh_commands SET expires_at_ms=? WHERE command_id=?",
                (now_ms() - 1000, queued["commandId"]),
            )
            conn.commit()

        wake_device(registry, LAPTOP)
        sent = []
        flush_pending(
            registry=registry, queue=queue, transport=lambda c, d: sent.append(c)
        )
        assert not sent
        assert queue.get(queued["commandId"])["status"] == "EXPIRED"


class TestItSurvivesTheRealWorld:
    def test_a_peer_that_fails_mid_drain_is_not_hammered(self, mesh):
        """Twenty timeouts against one unreachable machine helps nobody, and
        delays every other device in the fleet."""
        registry, queue = mesh
        wake_device(registry, LAPTOP)
        sleep_device(registry, LAPTOP)
        for _ in range(5):
            command = build_command(
                owner_id=OWNER,
                origin_device_id=HOST,
                target_device_id=LAPTOP,
                tool="notifications.show",
                arguments={"title": "x", "body": "y"},
                requires_confirmation=False,
            )
            queue.enqueue(sign_command(command), status="QUEUED")
        wake_device(registry, LAPTOP)

        attempts = []

        def broken(command, device):
            attempts.append(command)
            raise TransportError("injoignable")

        out = flush_pending(registry=registry, queue=queue, transport=broken)
        assert len(attempts) == 1
        assert out["delivered"] == 0
        assert out["skipped"] == 1

    def test_a_failed_drain_leaves_the_command_collectable(self, mesh):
        registry, queue = mesh
        wake_device(registry, LAPTOP)
        sleep_device(registry, LAPTOP)
        queued = queue_for(mesh, LAPTOP)
        wake_device(registry, LAPTOP)

        def broken(command, device):
            raise TransportError("injoignable")

        flush_pending(registry=registry, queue=queue, transport=broken)
        assert queue.get(queued["commandId"])["status"] == "QUEUED"
        # And the next pass, once it really is back, delivers it.
        out = flush_pending(
            registry=registry, queue=queue, transport=lambda c, d: {"status": "SUCCESS"}
        )
        assert out["delivered"] == 1

    def test_an_empty_fleet_is_a_no_op(self, tmp_path):
        registry = DeviceRegistry(db_path=tmp_path / "empty.db")
        queue = CommandQueue(db_path=tmp_path / "empty.db")
        assert flush_pending(registry=registry, queue=queue) == {
            "delivered": 0,
            "skipped": 0,
        }


class TestIdempotencyIsTheSendersWord:
    """A key is the SENDER's word for « the same intent ».

    It used to be a single global namespace, so a paired device could pick a
    key it had seen in its own inbox and collide with a row this machine
    owned: enqueue handed back OUR row, the command executed anyway, and mark
    then raised KeyError on a command_id no row carried — a 500, and nothing
    recording that anything had run.
    """

    def test_two_senders_may_use_the_same_key(self, mesh):
        _, queue = mesh
        ours = build_command(
            owner_id=OWNER,
            origin_device_id=HOST,
            target_device_id=LAPTOP,
            tool="app.navigate",
            arguments={"route": "success://today"},
            requires_confirmation=False,
            idempotency_key="meme-mot",
        )
        queue.enqueue(sign_command(ours), status="QUEUED")

        theirs = build_command(
            owner_id=OWNER,
            origin_device_id=LAPTOP,
            target_device_id=HOST,
            tool="app.open",
            arguments={},
            requires_confirmation=False,
            idempotency_key="meme-mot",
        )
        recorded = queue.enqueue(sign_command(theirs), status="RUNNING")

        assert recorded["commandId"] == theirs.command_id
        # And settling theirs must not need a row that does not exist.
        queue.mark(theirs.command_id, "SUCCESS", user_message="C'est fait.")
        assert queue.get(theirs.command_id)["status"] == "SUCCESS"
        assert queue.get(ours.command_id)["status"] == "QUEUED"

    def test_the_same_sender_reusing_a_key_still_gets_one_command(self, mesh):
        _, queue = mesh

        def one():
            return build_command(
                owner_id=OWNER,
                origin_device_id=HOST,
                target_device_id=LAPTOP,
                tool="app.navigate",
                arguments={"route": "success://today"},
                requires_confirmation=False,
                idempotency_key="une-seule-fois",
            )

        first = queue.enqueue(sign_command(one()), status="QUEUED")
        again = queue.enqueue(sign_command(one()), status="QUEUED")
        assert again["commandId"] == first["commandId"]

    def test_a_peer_cannot_settle_our_command_by_colliding_on_its_key(self, mesh):
        _, queue = mesh
        ours = build_command(
            owner_id=OWNER,
            origin_device_id=HOST,
            target_device_id=LAPTOP,
            tool="notifications.show",
            arguments={"title": "Diapason", "body": "Bilan"},
            requires_confirmation=False,
            idempotency_key="cle-visee",
        )
        queue.enqueue(sign_command(ours), status="QUEUED")

        found = queue.find_by_idempotency("cle-visee", origin_device_id=LAPTOP)
        assert found is None, "un pair ne doit pas retrouver notre ligne par sa clé"


class TestUneCommandeScelleeAttendSansPerdreSonSceau:
    """Étape 6 du plan du 26 août 2026.

    Une commande poussée vers un pair endormi attend jusqu'à six heures dans
    la file. C'est précisément le chemin qui a fait écarter un design à clé
    éphémère : un pair absent ne peut pas fournir sa moitié, et ce chemin
    serait alors parti en clair, en silence.
    """

    def _sceller_dans_la_file(self, mesh, device_id):
        """Ranger une commande scellée, comme `dispatch_command` le fait."""
        from diapason.mesh.coffre import nouvelle_demi_cle
        from diapason.mesh.registry import now_ms

        registry, queue = mesh
        # AVEC UN INSTANT COURANT : daté de 1970, la clé serait périmée et
        # rien ne serait scellé. Le premier jet de ce test l'a appris à ses
        # dépens — et c'est le contrôle de fraîcheur qui faisait son travail.
        registry.record_seal_key(device_id, nouvelle_demi_cle().publique_b64, now_ms())
        sleep_device(registry, device_id)
        queued = queue_for(mesh, device_id)
        return queue.envelope_of(queued["commandId"])

    def test_elle_repart_telle_quelle_des_heures_plus_tard(self, mesh):
        registry, queue = mesh
        rangee = self._sceller_dans_la_file(mesh, LAPTOP)

        wake_device(registry, LAPTOP)
        partie = []
        flush_pending(
            registry=registry,
            queue=queue,
            transport=lambda c, d: partie.append(c) or {"status": "SUCCESS"},
        )
        assert partie, "rien n'est reparti"
        # Verbatim : la signature couvre le chiffré, donc re-sceller
        # produirait une enveloppe qui ne vérifie plus.
        assert partie[0].signature == rangee.signature
        assert partie[0].to_dict() == rangee.to_dict()

    def test_ce_qui_dort_dans_la_file_est_deja_scelle(self, mesh):
        """Ce qui attend est exactement ce qui partira. Sceller au moment de
        l'envoi, des heures plus tard, supposerait que la clé du pair n'a pas
        changé entre-temps — et obligerait à re-signer."""
        from diapason.mesh.scellement import SENTINELLE

        rangee = self._sceller_dans_la_file(mesh, LAPTOP)
        sur_le_fil = rangee.to_dict()
        assert sur_le_fil["tool"] == SENTINELLE, (
            "la commande en file n'a pas été scellée"
        )
        assert set(sur_le_fil["arguments"]) == {"s", "e", "k"}
