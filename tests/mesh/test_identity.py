"""This device's mesh identity: derived, private, and stable.

The properties that matter are not "it returns a string" but: the id comes
FROM the key rather than being asserted, the private half never surfaces, a
second call is the same device, and a tampered payload fails verification.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway DIAPASON_HOME with the module tree pointed at it."""
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
    from diapason.core import paths

    importlib.reload(paths)
    from diapason.mesh import identity as module

    importlib.reload(module)
    yield tmp_path, module
    monkeypatch.delenv("DIAPASON_HOME", raising=False)
    importlib.reload(paths)


class TestCreation:
    def test_identity_is_created_on_first_call(self, home):
        root, module = home
        identity = module.device_identity()
        assert identity.device_id
        assert len(identity.public_key) == 32  # Ed25519 raw public key
        assert (root / "mesh" / "device_key").exists()
        assert (root / "mesh" / "device.json").exists()

    def test_second_call_is_the_same_device(self, home):
        _, module = home
        first = module.device_identity()
        second = module.device_identity()
        # A device whose key silently changed would be, to every peer it had
        # paired with, an impostor.
        assert first.device_id == second.device_id
        assert first.public_key == second.public_key

    def test_device_id_is_derived_from_the_key(self, home):
        root, module = home
        identity = module.device_identity()
        # No succes.db in this home, so the fingerprint path is taken.
        assert identity.device_id.startswith("dev_")
        assert identity.device_id == module._fingerprint(identity.public_key)


class TestSecrecy:
    def test_private_key_is_owner_only(self, home):
        root, module = home
        module.device_identity()
        mode = (root / "mesh" / "device_key").stat().st_mode & 0o777
        assert mode == 0o600

    def test_manifest_carries_no_private_material(self, home):
        root, module = home
        identity = module.device_identity()
        manifest = json.loads((root / "mesh" / "device.json").read_text())
        assert manifest["publicKey"] == identity.public_key_b64
        assert "privateKey" not in manifest
        # The public dict is what gets published to peers: it must be safe by
        # construction, not by the caller remembering to strip fields.
        assert set(identity.to_public_dict()) == {
            "deviceId",
            "publicKey",
            "name",
            "platform",
            "createdAtMs",
            # The fleet identity travels with the device: a peer needs it to
            # tell "same owner" from "someone else's Diapason" (spec §9).
            "ownerId",
        }

    def test_a_symlinked_key_is_refused(self, home):
        root, module = home
        module.device_identity()
        key = root / "mesh" / "device_key"
        stolen = root / "elsewhere"
        stolen.write_bytes(key.read_bytes())
        key.unlink()
        key.symlink_to(stolen)
        if not hasattr(os, "O_NOFOLLOW"):
            pytest.skip("O_NOFOLLOW unavailable on this platform")
        with pytest.raises(OSError):
            module._read_private_key(key)


class TestSignatures:
    def test_a_signed_payload_verifies(self, home):
        _, module = home
        identity = module.device_identity()
        payload = {"tool": "app.navigate", "route": "success://projects/p1"}
        signature = module.sign_envelope(payload)
        assert module.verify_envelope(payload, signature, identity.public_key)

    def test_a_tampered_payload_is_rejected(self, home):
        _, module = home
        identity = module.device_identity()
        payload = {"tool": "app.navigate", "route": "success://projects/p1"}
        signature = module.sign_envelope(payload)
        payload["route"] = "success://projects/SOMEONE_ELSE"
        assert not module.verify_envelope(payload, signature, identity.public_key)

    def test_another_devices_key_does_not_verify(self, home, tmp_path):
        _, module = home
        payload = {"tool": "app.open"}
        signature = module.sign_envelope(payload)
        from diapason.security.signing import generate_keypair

        stranger = generate_keypair()
        assert not module.verify_envelope(payload, signature, stranger.public_key)

    def test_an_empty_signature_never_passes(self, home):
        _, module = home
        identity = module.device_identity()
        assert not module.verify_envelope({"a": 1}, "", identity.public_key)

    def test_canonical_bytes_ignore_key_order(self, home):
        _, module = home
        # Both sides must hash the same bytes for the same meaning, whatever
        # order their JSON encoder happened to produce.
        assert module.canonical_bytes({"b": 1, "a": 2}) == module.canonical_bytes(
            {"a": 2, "b": 1}
        )


class TestContinuity:
    def test_an_existing_succes_device_id_is_adopted(self, home):
        """This machine's 150 recorded operations must stay one device.

        Splitting history the day the mesh arrives would break attribution
        for everything already written.
        """
        root, module = home
        import sqlite3

        db = Path(root) / "succes.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE succes_meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO succes_meta VALUES ('device_id', 'mac-deadbeefdeadbeef')"
            )
            conn.commit()

        identity = module.device_identity()
        assert identity.device_id == "mac-deadbeefdeadbeef"
        # …and it is still a real key pair, not a bare string.
        assert len(identity.public_key) == 32
