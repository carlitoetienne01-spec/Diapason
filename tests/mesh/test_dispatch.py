"""Sending commands: the queue, the offline policies, and never lying.

The property under test throughout is spec §57 — a command that did not run
is never reported as having run — and its corollary: the wording must
distinguish "will happen later" from "will not happen", because a user acts
on the difference.
"""

from __future__ import annotations

import base64

import pytest

from diapason.mesh.commands import NonceStore
from diapason.mesh.dispatch import dispatch_command, receive_command
from diapason.mesh.queue import CommandQueue
from diapason.mesh.registry import DeviceRegistry, now_ms
from diapason.mesh.transport import (
    TransportError,
    address_is_private,
    assert_may_reach_device,
)
from diapason.security.signing import generate_keypair

TARGET = "dev_windows_pc"


@pytest.fixture
def mesh(tmp_path, monkeypatch):
    """A local identity plus one paired PC, both on a temp home."""
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
    import importlib

    from diapason.core import paths

    importlib.reload(paths)
    from diapason.mesh import identity as identity_module

    importlib.reload(identity_module)

    registry = DeviceRegistry(tmp_path / "mesh.db")
    queue = CommandQueue(tmp_path / "mesh.db")

    local = identity_module.device_identity()
    invitation = registry.create_pairing("Ce Mac")
    registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=local.device_id,
        public_key_b64=local.public_key_b64,
        name="Ce Mac",
        platform="MACOS",
        device_type="LAPTOP",
        declared_capabilities=["app.navigate", "app.show_resource"],
    )
    invitation2 = registry.create_pairing("PC du bureau")
    registry.redeem_pairing(
        invitation2["pairingToken"],
        device_id=TARGET,
        public_key_b64=base64.b64encode(generate_keypair().public_key).decode(),
        name="PC du bureau",
        platform="WINDOWS",
        device_type="DESKTOP",
        declared_capabilities=["app.navigate", "app.show_resource"],
    )
    registry.heartbeat(TARGET, address="http://192.168.1.42:8000")
    yield registry, queue, identity_module
    importlib.reload(paths)


def send(mesh, **kwargs):
    registry, queue, _ = mesh
    defaults = dict(
        target_device_id=TARGET,
        tool="app.navigate",
        arguments={"route": "success://projects/flashprime"},
        registry=registry,
        queue=queue,
    )
    defaults.update(kwargs)
    return dispatch_command(**defaults)


class TestHappyPath:
    def test_a_reachable_device_receives_the_command(self, mesh):
        """Acceptance TEST B: « Ouvre FlashPrime sur mon PC »."""
        sent = {}

        def transport(command, device):
            sent["route"] = command.arguments["route"]
            sent["target"] = device["deviceId"]
            return {"status": "SUCCESS", "userSafeMessage": "FlashPrime est ouvert."}

        result = send(mesh, transport=transport)
        assert result["status"] == "SUCCESS"
        assert result["userSafeMessage"] == "FlashPrime est ouvert."
        assert sent["route"] == "success://projects/flashprime"
        assert sent["target"] == TARGET

    def test_the_command_is_recorded_before_it_leaves(self, mesh):
        """Transactional outbox: a command on the wire always has a row."""
        registry, queue, _ = mesh
        seen = {}

        def transport(command, device):
            # Mid-flight, the row must already exist.
            seen["row"] = queue.get(command.command_id)
            return {"status": "SUCCESS", "userSafeMessage": "ok"}

        send(mesh, transport=transport)
        assert seen["row"]["tool"] == "app.navigate"


class TestOfflineHonesty:
    """Acceptance TEST D: never claim an offline device did something."""

    def _put_offline(self, registry, tmp_days: int = 1):
        import sqlite3

        with sqlite3.connect(registry.db_path) as conn:
            conn.execute(
                "UPDATE mesh_devices SET last_seen_at_ms=? WHERE device_id=?",
                (now_ms() - 86_400_000, TARGET),
            )
            conn.commit()

    def test_require_online_tool_refuses_rather_than_pretends(self, mesh):
        registry, _, _ = mesh
        self._put_offline(registry)
        called = []
        result = send(mesh, transport=lambda c, d: called.append(1))
        assert result["status"] == "OFFLINE"
        assert "hors ligne" in result["userSafeMessage"]
        assert "n'a pas été effectuée" in result["userSafeMessage"]
        assert not called  # nothing was even attempted

    def test_a_queueable_tool_says_queued_not_done(self, mesh):
        registry, _, _ = mesh
        self._put_offline(registry)
        # notifications.show is QUEUE_UNTIL_EXPIRATION, but this PC did not
        # declare that capability — use show_resource, which it did.
        result = send(
            mesh,
            tool="app.show_resource",
            arguments={"resourceType": "project", "resourceId": "p1"},
            transport=lambda c, d: {"status": "SUCCESS"},
        )
        assert result["status"] == "QUEUED"
        assert "en attente" in result["userSafeMessage"]
        assert "dès son retour" in result["userSafeMessage"]

    def test_a_queued_command_is_listed_for_later_delivery(self, mesh):
        registry, queue, _ = mesh
        self._put_offline(registry)
        send(
            mesh,
            tool="app.show_resource",
            arguments={"resourceType": "task", "resourceId": "t1"},
        )
        pending = queue.pending_for(TARGET)
        assert len(pending) == 1
        assert pending[0]["tool"] == "app.show_resource"

    def test_a_transport_failure_is_not_a_success(self, mesh):
        def broken(command, device):
            raise TransportError("Cet appareil n'a pas pu être joint.")

        result = send(mesh, transport=broken)
        assert result["status"] != "SUCCESS"
        assert result["status"] in {"QUEUED", "OFFLINE"}

    def test_awake_but_unreachable_is_not_described_as_offline(self, mesh):
        """A device that answered a heartbeat and then failed on the wire is
        not asleep — it is a network problem. Calling it « hors ligne » sends
        the user to check a machine that is in fact on."""

        def broken(command, device):
            raise TransportError("Cet appareil n'a pas pu être joint.")

        result = send(mesh, transport=broken)
        assert "hors ligne" not in result["userSafeMessage"]
        assert "n'a pas pu être joint" in result["userSafeMessage"]
        assert result["errorCode"] == "TRANSPORT_FAILED"

    def test_a_genuinely_offline_device_still_says_offline(self, mesh):
        registry, _, _ = mesh
        self._put_offline(registry)
        result = send(mesh, transport=lambda c, d: {"status": "SUCCESS"})
        assert "hors ligne" in result["userSafeMessage"]
        assert result["errorCode"] == "TARGET_OFFLINE"

    def test_a_queueable_command_outlives_a_phone_s_sleep(self, mesh):
        """One minute is useless for a device that has to come and fetch.

        iOS suspends an app within seconds of backgrounding, so a queued
        reminder used to die long before its phone ever polled again — and
        « partira dès son retour » was true of a command already expired.
        """
        from diapason.mesh.commands import QUEUED_TTL_MS

        registry, queue, _ = mesh
        self._put_offline(registry)
        send(
            mesh,
            tool="app.show_resource",
            arguments={"resourceType": "note", "resourceId": "n1"},
        )
        # An hour later — a plausible night's interruption — it still stands.
        assert queue.expire_stale(now=now_ms() + 3_600_000) == 0
        assert queue.history()[0]["status"] == "QUEUED"

        # Past its window it stops claiming it will happen.
        changed = queue.expire_stale(now=now_ms() + QUEUED_TTL_MS + 60_000)
        assert changed == 1
        assert queue.history()[0]["status"] == "EXPIRED"

    def test_a_command_that_must_act_now_keeps_the_short_window(self, mesh):
        """« Ouvre mes tâches » an hour later would be a surprise, not a
        service. Only the tools allowed to wait get the long window."""
        from diapason.mesh.commands import DEFAULT_TTL_MS, QUEUED_TTL_MS

        _, queue, _ = mesh
        now = now_ms()
        immediate = send(mesh, transport=lambda c, d: {"status": "SUCCESS"})
        deferrable = send(
            mesh,
            tool="app.show_resource",
            arguments={"resourceType": "note", "resourceId": "n1"},
            transport=lambda c, d: {"status": "SUCCESS"},
        )

        short = queue.get(immediate["commandId"])["expiresAtMs"] - now
        long_ = queue.get(deferrable["commandId"])["expiresAtMs"] - now
        assert short <= DEFAULT_TTL_MS + 1_000
        assert long_ >= QUEUED_TTL_MS - 1_000


class TestRefusalsBeforeSending:
    def test_an_unknown_tool_never_reaches_the_wire(self, mesh):
        called = []
        result = send(
            mesh,
            tool="system.execute_shell",
            arguments={},
            transport=lambda c, d: called.append(1),
        )
        assert result["status"] == "UNSUPPORTED"
        assert not called

    def test_an_unpaired_target_is_denied(self, mesh):
        result = send(mesh, target_device_id="dev_stranger")
        assert result["status"] == "DENIED"
        assert "pas appairé" in result["userSafeMessage"]

    def test_a_revoked_target_is_denied(self, mesh):
        registry, _, _ = mesh
        registry.revoke(TARGET)
        result = send(mesh)
        assert result["status"] == "DENIED"

    def test_a_capability_the_target_lacks_fails_here_not_there(self, mesh):
        """Better a clear refusal locally than a shrug on the far side."""
        result = send(mesh, tool="notifications.show", arguments={"title": "Coucou"})
        assert result["status"] == "UNSUPPORTED"
        assert "ne peut pas faire cela" in result["userSafeMessage"]

    def test_a_bad_argument_never_travels(self, mesh):
        called = []
        result = send(
            mesh,
            arguments={"route": "success://today", "script": "rm -rf /"},
            transport=lambda c, d: called.append(1),
        )
        assert result["status"] == "DENIED"
        assert not called


class TestIdempotency:
    def test_the_same_intent_is_not_executed_twice(self, mesh):
        """Acceptance TEST F, sender side."""
        calls = []

        def transport(command, device):
            calls.append(command.command_id)
            return {"status": "SUCCESS", "userSafeMessage": "ok"}

        first = send(mesh, idempotency_key="idem_open_flashprime", transport=transport)
        second = send(mesh, idempotency_key="idem_open_flashprime", transport=transport)
        assert first["status"] == "SUCCESS"
        assert second["commandId"] == first["commandId"]
        assert len(calls) == 1


class TestReceiving:
    def test_a_redelivered_command_replays_its_result(self, mesh, tmp_path):
        """Acceptance TEST F, receiver side: three deliveries, one effect."""
        registry, queue, identity_module = mesh
        nonces = NonceStore(tmp_path / "mesh.db")
        local = identity_module.device_identity()

        # A peer we trust, signing a command addressed to us.
        peer_keys = generate_keypair()
        invitation = registry.create_pairing("iPhone")
        registry.redeem_pairing(
            invitation["pairingToken"],
            device_id="dev_iphone",
            public_key_b64=base64.b64encode(peer_keys.public_key).decode(),
            name="iPhone",
            platform="IOS",
            device_type="PHONE",
            declared_capabilities=["app.navigate"],
        )

        from diapason.mesh.commands import build_command
        from diapason.mesh.identity import canonical_bytes
        from diapason.security.signing import sign_b64

        command = build_command(
            owner_id=identity_module.owner_id(),
            origin_device_id="dev_iphone",
            target_device_id=local.device_id,
            tool="app.navigate",
            arguments={"route": "success://today"},
            idempotency_key="idem_today",
        )
        payload = command.to_dict(with_signature=False)
        raw = {
            **payload,
            "signature": sign_b64(canonical_bytes(payload), peer_keys.private_key),
        }

        runs = []

        def executor(cmd):
            runs.append(cmd.command_id)
            return {"userSafeMessage": "Écran ouvert."}

        first = receive_command(
            raw, registry=registry, queue=queue, nonces=nonces, executor=executor
        )
        assert first["status"] == "SUCCESS"
        assert len(runs) == 1

        # Redelivered: the nonce is spent, so it is refused outright — the
        # effect happened exactly once either way.
        second = receive_command(
            raw, registry=registry, queue=queue, nonces=nonces, executor=executor
        )
        assert len(runs) == 1
        assert second["status"] in {"SUCCESS", "DENIED"}

    def test_a_device_with_no_executor_admits_it(self, mesh, tmp_path):
        registry, queue, identity_module = mesh
        nonces = NonceStore(tmp_path / "mesh.db")
        local = identity_module.device_identity()
        peer_keys = generate_keypair()
        invitation = registry.create_pairing("iPhone")
        registry.redeem_pairing(
            invitation["pairingToken"],
            device_id="dev_iphone2",
            public_key_b64=base64.b64encode(peer_keys.public_key).decode(),
            name="iPhone",
            platform="IOS",
            device_type="PHONE",
            declared_capabilities=["app.navigate"],
        )
        from diapason.mesh.commands import build_command
        from diapason.mesh.identity import canonical_bytes
        from diapason.security.signing import sign_b64

        command = build_command(
            owner_id=identity_module.owner_id(),
            origin_device_id="dev_iphone2",
            target_device_id=local.device_id,
            tool="app.navigate",
            arguments={"route": "success://today"},
        )
        payload = command.to_dict(with_signature=False)
        raw = {
            **payload,
            "signature": sign_b64(canonical_bytes(payload), peer_keys.private_key),
        }
        result = receive_command(raw, registry=registry, queue=queue, nonces=nonces)
        assert result["status"] == "UNSUPPORTED"
        assert "ne sait pas encore" in result["userSafeMessage"]


class TestPrivacyBoundary:
    """The mesh's one exemption to local-only, and its limits."""

    def test_private_addresses_are_recognised(self):
        assert address_is_private("http://192.168.1.42:8000")
        assert address_is_private("http://10.0.0.5:8000")
        assert address_is_private("http://127.0.0.1:8000")
        assert address_is_private("http://localhost:8000")

    def test_public_addresses_are_not(self):
        assert not address_is_private("https://sync.example.com")
        assert not address_is_private("http://8.8.8.8")
        # Link-local is where cloud metadata services live.
        assert not address_is_private("http://169.254.169.254")
        assert not address_is_private("")

    def test_an_untrusted_device_gets_no_exemption(self, monkeypatch):
        from diapason.core import local_mode

        monkeypatch.setattr(local_mode, "local_only", lambda config=None: True)
        with pytest.raises(local_mode.LocalOnlyError, match="pas appairé"):
            assert_may_reach_device(
                {"trustLevel": "REVOKED"}, "http://192.168.1.42:8000"
            )

    def test_a_public_address_gets_no_exemption(self, monkeypatch):
        from diapason.core import local_mode

        monkeypatch.setattr(local_mode, "local_only", lambda config=None: True)
        with pytest.raises(local_mode.LocalOnlyError, match="réseau local"):
            assert_may_reach_device(
                {"trustLevel": "TRUSTED"}, "https://relay.example.com"
            )

    def test_a_paired_device_on_the_lan_is_reachable(self, monkeypatch):
        from diapason.core import local_mode

        monkeypatch.setattr(local_mode, "local_only", lambda config=None: True)
        # No exception: this is the user's own other computer.
        assert_may_reach_device({"trustLevel": "TRUSTED"}, "http://192.168.1.42:8000")


class TestUnRefusNeSePresentePas:
    """La route d'arrivée des commandes vit hors du mur d'authentification :
    la signature Ed25519 de l'enveloppe EST la créance.

    Mais un refus répondait en donnant l'identifiant permanent de la
    machine. Le 26 août 2026, un POST au corps vide, sans la moindre
    créance, a obtenu « mac-73d5a8b0c742888a » depuis le Wi-Fi. Un
    identifiant stable est ce avec quoi on suit une machine d'un réseau à
    l'autre — il ne se donne pas à qui n'a rien prouvé.

    Un expéditeur légitime, lui, ne perd rien : il vient d'écrire cet
    identifiant dans son enveloppe, et le recevoir en retour ne lui apprend
    rien qu'il ne sache déjà.
    """

    def test_un_corps_vide_n_obtient_pas_l_identifiant_de_la_machine(self):
        from diapason.mesh.dispatch import receive_command
        from diapason.mesh.identity import device_identity

        reponse = receive_command({})
        assert reponse["errorCode"] == "MALFORMED"
        assert device_identity().device_id not in str(reponse)
        assert reponse["targetDeviceId"] == ""

    def test_une_enveloppe_illisible_non_plus(self):
        from diapason.mesh.dispatch import receive_command
        from diapason.mesh.identity import device_identity

        reponse = receive_command({"commandId": "x", "envelope": "pas du json"})
        assert device_identity().device_id not in str(reponse)

    def test_le_champ_existe_toujours_et_fait_echo(self):
        """Le contrat avec le client mobile ne change pas de FORME : le champ
        reste présent, et un expéditeur retrouve ce qu'il a demandé."""
        from diapason.mesh.dispatch import receive_command

        reponse = receive_command({"targetDeviceId": "dev_ceQueJAiDemande"})
        assert "targetDeviceId" in reponse
        assert reponse["targetDeviceId"] == "dev_ceQueJAiDemande"


class TestUneReponseForgeeNeSupprimeJamaisLaCle:
    """LE test de l'étape 5, et le plus important du lot.

    La première version du plan rendait OBLIGATOIRE une rétrogradation vers
    le clair quand le pair répondait « je ne connais pas cet outil ». Or
    cette réponse est un corps HTTP **non signé** : un attaquant sur le
    chemin n'avait qu'à la forger pour éteindre le chiffrement, commande
    par commande, et durablement. Un chiffrement qu'on coupe à volonté est
    pire que pas de chiffrement, parce qu'on croit l'avoir.

    Il n'existe donc AUCUN code de rétrogradation dans ce dépôt, et ce test
    est là pour que cela reste vrai : quelle que soit la réponse, la clé
    enregistrée ne bouge pas.
    """

    @pytest.mark.parametrize(
        "reponse",
        [
            {"status": "UNSUPPORTED", "userSafeMessage": "« mesh.sealed » inconnu."},
            {"status": "DENIED", "errorCode": "MALFORMED"},
            {"status": "FAILED", "userSafeMessage": "impossible d'ouvrir le sceau"},
            {},
            {"status": "SUCCESS"},
        ],
        ids=["unsupported", "denied", "failed", "vide", "succes"],
    )
    def test_aucune_reponse_ne_fait_oublier_la_cle(self, mesh, reponse):
        from diapason.mesh.coffre import nouvelle_demi_cle

        registry, _queue, _ = mesh
        cle = nouvelle_demi_cle().publique_b64
        assert registry.record_seal_key(TARGET, cle, 1_000) is True

        send(mesh, transport=lambda *a, **k: dict(reponse))

        assert registry.seal_key_of(TARGET) == (cle, 1_000), (
            "une réponse non signée a modifié la clé de scellement"
        )

    def test_le_depot_ne_contient_aucun_code_de_retrogradation(self):
        """Un cliquet sur l'intention, pas seulement sur un cas.

        `forget_seal_key` est la sortie de secours manuelle. Si elle
        apparaissait un jour dans un chemin qui lit une réponse réseau, ce
        serait la rétrogradation revenue par la fenêtre.
        """
        import pathlib

        racine = pathlib.Path(__file__).resolve().parents[2] / "src" / "diapason"
        appelants = [
            chemin.relative_to(racine).as_posix()
            for chemin in racine.rglob("*.py")
            if "forget_seal_key" in chemin.read_text(encoding="utf-8")
        ]
        assert set(appelants) <= {"mesh/registry.py"}, (
            f"`forget_seal_key` est appelée depuis {appelants} — vérifier "
            "qu'aucun de ces chemins ne lit une réponse réseau"
        )
