"""This device's cryptographic identity in the mesh.

Every installation holds one Ed25519 key pair, created on first use. The
public half is what other devices are told about; the private half never
leaves this machine and never appears in a log, a payload or an error.

Why a key pair rather than the opaque ``mac-<hex>`` Succès already had: an
identifier a device simply *asserts* can be asserted by anyone. Section 5 of
the mesh specification rules out IP, hostname, user agent, MAC address and
non-revocable tokens for exactly that reason. A key is different in kind —
the device proves it holds the private half, and revocation is meaningful
because the public half is what was recorded.

Storage follows the local API key's hardened pattern (0700 directory, 0600
file, atomic O_EXCL creation, O_NOFOLLOW read): the same threat — a swapped
symlink or a world-readable secret — applies identically here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import socket
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diapason.core.paths import get_config_dir

__all__ = [
    "DeviceIdentity",
    "adopt_owner_id",
    "device_identity",
    "owner_id",
    "identity_dir",
    "public_identity",
    "sign_envelope",
    "verify_envelope",
    "canonical_bytes",
]

_KEY_FILENAME = "device_key"
_MANIFEST_FILENAME = "device.json"

# Platform label as the mesh speaks it (spec §5). Anything unrecognised stays
# honest rather than guessing.
_PLATFORMS = {
    "Darwin": "MACOS",
    "Windows": "WINDOWS",
    "Linux": "LINUX",
}


@dataclass(frozen=True)
class DeviceIdentity:
    """This device, as the rest of the mesh may know it."""

    device_id: str
    public_key: bytes
    name: str
    platform: str
    created_at_ms: int

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key).decode("ascii")

    def to_public_dict(self) -> dict[str, Any]:
        """Everything shareable — and nothing else. No private key, ever."""
        return {
            "deviceId": self.device_id,
            "publicKey": self.public_key_b64,
            "name": self.name,
            "platform": self.platform,
            "createdAtMs": self.created_at_ms,
            "ownerId": owner_id(),
        }


def identity_dir() -> Path:
    return get_config_dir() / "mesh"


_OWNER_FILENAME = "owner"


def owner_id() -> str:
    """The identity every device of this fleet shares.

    Chosen shape (user decision): a locally minted identity propagated by
    pairing, not an account on a server. No password, no e-mail, nothing to
    breach remotely — and it still gives commands the "same owner" check
    spec §9 requires, because a device only ever learns it by being paired.

    Created once, then read; never regenerated silently, since a changed
    owner id would orphan every device already paired.
    """
    directory = identity_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / _OWNER_FILENAME
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    import secrets

    minted = f"owner_{secrets.token_hex(16)}"
    path.write_text(minted, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # noqa: BLE001
        pass
    return minted


def adopt_owner_id(value: str) -> str:
    """Join an existing fleet: take the owner id our host handed us.

    Refuses to overwrite a different established identity — a device cannot
    silently change fleets, which is how paired devices would lose each other.
    """
    candidate = str(value or "").strip()
    if not candidate.startswith("owner_") or len(candidate) > 80:
        raise ValueError("Identifiant de propriétaire invalide.")
    directory = identity_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / _OWNER_FILENAME
    if path.exists():
        current = path.read_text(encoding="utf-8").strip()
        if current and current != candidate:
            raise ValueError(
                "Cet appareil appartient déjà à un autre ensemble d'appareils."
            )
    path.write_text(candidate, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # noqa: BLE001
        pass
    return candidate


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _default_name() -> str:
    """A name a human recognises in a device list, never a secret."""
    try:
        host = socket.gethostname().split(".")[0].strip()
    except Exception:  # noqa: BLE001 - a nameless device is still a device
        host = ""
    return host or f"{_default_platform().title()} device"


def _default_platform() -> str:
    return _PLATFORMS.get(platform.system(), "UNKNOWN")


def _fingerprint(public_key: bytes) -> str:
    """Device id derived from the public key — not asserted, derived.

    24 hex characters of SHA-256: collision-free in any realistic device
    fleet, and short enough to read aloud when confirming a pairing.
    """
    digest = hashlib.sha256(public_key).hexdigest()
    return f"dev_{digest[:24]}"


def _write_private_key(path: Path, private_key: bytes) -> None:
    """Create the key file atomically, owner-only, refusing to follow links."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        os.write(descriptor, base64.b64encode(private_key))
    finally:
        os.close(descriptor)


def _read_private_key(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    else:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(f"Clé d'appareil au chemin non sûr : {path}")
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(f"Clé d'appareil au chemin non sûr : {path}")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        raw = os.read(descriptor, 4096)
    finally:
        os.close(descriptor)
    return base64.b64decode(raw.strip())


def _legacy_succes_device_id() -> str | None:
    """The id Succès already stamped on its operations, if any.

    Adopting it keeps this machine's existing history attributed to the same
    device instead of splitting it in two the day the mesh arrives. New
    installations get the key fingerprint, which is the better identifier;
    this is purely a continuity bridge and is read best-effort.
    """
    db_path = get_config_dir() / "succes.db"
    if not db_path.exists():
        return None
    try:
        import sqlite3

        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT value FROM succes_meta WHERE key='device_id'"
            ).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception:  # noqa: BLE001 - continuity is a nicety, never a blocker
        return None


def device_identity(*, name: str = "") -> DeviceIdentity:
    """This device's identity, creating the key pair on first call.

    Idempotent: subsequent calls read what the first one wrote. The private
    key is generated once and never regenerated silently — a device whose key
    changed would be, to every peer, a different device.
    """
    from diapason.security.signing import generate_keypair

    directory = identity_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:  # noqa: BLE001 - a stricter umask is fine
        pass

    key_path = directory / _KEY_FILENAME
    manifest_path = directory / _MANIFEST_FILENAME

    if key_path.exists() and manifest_path.exists():
        # Read the private key for its side effects only: it re-asserts 0600
        # and refuses a swapped symlink, so a tampered key fails HERE rather
        # than at the first signature, when a command is already in flight.
        _read_private_key(key_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return DeviceIdentity(
            device_id=str(manifest["deviceId"]),
            public_key=base64.b64decode(manifest["publicKey"]),
            name=str(manifest.get("name") or _default_name()),
            platform=str(manifest.get("platform") or _default_platform()),
            created_at_ms=int(manifest.get("createdAtMs") or _now_ms()),
        )

    keypair = generate_keypair()
    device_id = _legacy_succes_device_id() or _fingerprint(keypair.public_key)
    identity = DeviceIdentity(
        device_id=device_id,
        public_key=keypair.public_key,
        name=name or _default_name(),
        platform=_default_platform(),
        created_at_ms=_now_ms(),
    )
    # Key first, manifest second: a crash between the two is recoverable
    # (the half-written pair is detected by the exists() check above and
    # regenerated), whereas a manifest without its key is not.
    if not key_path.exists():
        _write_private_key(key_path, keypair.private_key)
    manifest_path.write_text(
        json.dumps(identity.to_public_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        manifest_path.chmod(0o600)
    except OSError:  # noqa: BLE001
        pass
    return identity


def public_identity() -> dict[str, Any]:
    """What this device may publish about itself."""
    return device_identity().to_public_dict()


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """The exact bytes both sides sign.

    Signing a dict means agreeing on its serialisation first: sorted keys, no
    incidental whitespace, UTF-8 preserved. Succès already canonicalises its
    operation payloads this way — same rule, one place.
    """
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sign_envelope(payload: dict[str, Any]) -> str:
    """Sign *payload* with this device's private key. Returns base64."""
    from diapason.security.signing import sign_b64

    directory = identity_dir()
    device_identity()  # ensure the pair exists before reading it
    private_key = _read_private_key(directory / _KEY_FILENAME)
    return sign_b64(canonical_bytes(payload), private_key)


def verify_envelope(
    payload: dict[str, Any], signature_b64: str, public_key: bytes
) -> bool:
    """True when *signature_b64* is this payload, signed by *public_key*."""
    from diapason.security.signing import verify_b64

    if not signature_b64:
        return False
    return verify_b64(canonical_bytes(payload), signature_b64, public_key)
