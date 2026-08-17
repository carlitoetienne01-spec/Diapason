"""The signed command envelope, and the eleven checks it must survive.

A command crossing between devices is the mesh's sharpest edge: it makes one
machine act on another's word. Spec §9 lists what must be verified, and the
value of the list is that it is verified in ONE place — a check spread across
call sites is a check that will be forgotten at one of them.

    identity · origin · destination · signature · expiry · nonce ·
    idempotency · permissions · capabilities · risk · confirmation

Two properties are worth stating plainly, because they are what make the
difference between a protocol and a hope:

* The signature covers the whole envelope EXCEPT itself, over canonical
  bytes. Change one character of one argument and verification fails.
* A nonce may be spent once. Replaying a captured command — the classic way
  to make "open this" become "open this forty times" — is refused by the
  second attempt, even with a perfect signature.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from diapason.core.paths import get_data_dir

__all__ = [
    "COMMAND_VERSION",
    "CommandError",
    "CommandRejected",
    "RemoteCommand",
    "NonceStore",
    "build_command",
    "sign_command",
    "verify_command",
    "STATUS_VALUES",
]

COMMAND_VERSION = 1

# How long a command may remain valid. Short on purpose: an envelope that
# lives for hours is an envelope worth stealing.
DEFAULT_TTL_MS = 60_000

# Tolerance for clock disagreement between two devices. Beyond this, a
# command "from the future" is refused rather than silently trusted.
MAX_CLOCK_SKEW_MS = 30_000

STATUS_VALUES = (
    "ACCEPTED",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "DENIED",
    "EXPIRED",
    "OFFLINE",
    "UNSUPPORTED",
)


class CommandError(RuntimeError):
    """Malformed command — the sender got the protocol wrong."""


class CommandRejected(RuntimeError):
    """A well-formed command that must not run.

    Carries a machine-readable ``code`` for the caller's status field and a
    French ``message`` safe to show the user (never the failing signature,
    never a nonce, never an argument value).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RemoteCommand:
    """One instruction from one device to another (spec §8)."""

    command_id: str
    owner_id: str
    origin_device_id: str
    target_device_id: str
    tool: str
    arguments: dict[str, Any]
    created_at_ms: int
    expires_at_ms: int
    nonce: str
    idempotency_key: str
    requires_confirmation: bool = False
    confirmation_id: str = ""
    signature: str = ""
    version: int = COMMAND_VERSION
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self, *, with_signature: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "commandId": self.command_id,
            "ownerId": self.owner_id,
            "originDeviceId": self.origin_device_id,
            "targetDeviceId": self.target_device_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "createdAtMs": self.created_at_ms,
            "expiresAtMs": self.expires_at_ms,
            "nonce": self.nonce,
            "idempotencyKey": self.idempotency_key,
            "requiresConfirmation": self.requires_confirmation,
        }
        if self.confirmation_id:
            payload["confirmationId"] = self.confirmation_id
        if with_signature and self.signature:
            payload["signature"] = self.signature
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RemoteCommand:
        if not isinstance(raw, Mapping):
            raise CommandError("La commande est illisible.")
        try:
            return cls(
                version=int(raw.get("version") or 0),
                command_id=str(raw["commandId"]),
                owner_id=str(raw["ownerId"]),
                origin_device_id=str(raw["originDeviceId"]),
                target_device_id=str(raw["targetDeviceId"]),
                tool=str(raw["tool"]),
                arguments=dict(raw.get("arguments") or {}),
                created_at_ms=int(raw["createdAtMs"]),
                expires_at_ms=int(raw["expiresAtMs"]),
                nonce=str(raw["nonce"]),
                idempotency_key=str(raw["idempotencyKey"]),
                requires_confirmation=bool(raw.get("requiresConfirmation")),
                confirmation_id=str(raw.get("confirmationId") or ""),
                signature=str(raw.get("signature") or ""),
            )
        except KeyError as exc:
            raise CommandError(f"Champ de commande manquant : {exc.args[0]}.") from exc
        except (TypeError, ValueError) as exc:
            raise CommandError("La commande est mal formée.") from exc


def now_ms() -> int:
    return int(time.time() * 1000)


def build_command(
    *,
    owner_id: str,
    origin_device_id: str,
    target_device_id: str,
    tool: str,
    arguments: Mapping[str, Any] | None = None,
    ttl_ms: int = DEFAULT_TTL_MS,
    requires_confirmation: bool = False,
    confirmation_id: str = "",
    idempotency_key: str = "",
) -> RemoteCommand:
    """Assemble an unsigned command with fresh anti-replay material."""
    created = now_ms()
    return RemoteCommand(
        command_id=f"cmd_{uuid.uuid4().hex}",
        owner_id=owner_id,
        origin_device_id=origin_device_id,
        target_device_id=target_device_id,
        tool=tool,
        arguments=dict(arguments or {}),
        created_at_ms=created,
        expires_at_ms=created + max(1_000, int(ttl_ms)),
        nonce=secrets.token_urlsafe(24),
        # Default idempotency is per-command, so a retry of the SAME envelope
        # is idempotent while two deliberate invocations are not conflated.
        idempotency_key=idempotency_key or f"idem_{uuid.uuid4().hex}",
        requires_confirmation=requires_confirmation,
        confirmation_id=confirmation_id,
    )


def sign_command(command: RemoteCommand) -> RemoteCommand:
    """Sign with THIS device's private key, over everything but the signature."""
    from diapason.mesh.identity import sign_envelope

    signature = sign_envelope(command.to_dict(with_signature=False))
    return RemoteCommand(**{**command.__dict__, "signature": signature})


class NonceStore:
    """Spent nonces, so a captured command cannot be replayed.

    Entries are pruned past the maximum command lifetime: a nonce can only be
    replayed while its command could still be valid, so remembering it beyond
    that adds storage without adding safety.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or (get_data_dir() / "mesh.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS mesh_nonces (
                       nonce TEXT PRIMARY KEY,
                       device_id TEXT NOT NULL,
                       seen_at_ms INTEGER NOT NULL
                   )"""
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def spend(
        self, nonce: str, device_id: str, *, retention_ms: int = 3_600_000
    ) -> bool:
        """Consume *nonce*. False when it was already spent — a replay.

        The INSERT itself is the check: relying on the primary key makes the
        test atomic, where a SELECT-then-INSERT would let two concurrent
        deliveries of the same command both pass.
        """
        stamp = now_ms()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM mesh_nonces WHERE seen_at_ms < ?", (stamp - retention_ms,)
            )
            try:
                conn.execute(
                    "INSERT INTO mesh_nonces(nonce, device_id, seen_at_ms) "
                    "VALUES (?,?,?)",
                    (nonce, device_id, stamp),
                )
            except sqlite3.IntegrityError:
                return False
            conn.commit()
        return True


def verify_command(
    raw: Mapping[str, Any],
    *,
    registry: Any,
    local_device_id: str,
    local_owner_id: str,
    nonces: NonceStore,
    now: int | None = None,
) -> RemoteCommand:
    """Run every check of spec §9. Raises on the first failure.

    Order matters: the cheap structural checks come first so a malformed or
    misaddressed command never reaches the cryptography, and the nonce is
    spent LAST — otherwise a command rejected for another reason would burn
    a nonce the legitimate sender still needs.
    """
    stamp = now_ms() if now is None else now
    command = RemoteCommand.from_dict(raw)

    # 1. protocol version — refuse what we cannot fully understand
    if command.version != COMMAND_VERSION:
        raise CommandRejected(
            "UNSUPPORTED", "Cette commande utilise une version non prise en charge."
        )

    # 2. identity — same fleet
    if not command.owner_id or command.owner_id != local_owner_id:
        raise CommandRejected(
            "DENIED", "Cette commande vient d'un autre ensemble d'appareils."
        )

    # 3. destination — addressed to us
    if command.target_device_id != local_device_id:
        raise CommandRejected(
            "DENIED", "Cette commande ne s'adresse pas à cet appareil."
        )

    # 4. origin — a device we know, trust, and hold a key for. A revoked
    #    device has no key here (registry returns None), so it stops at once.
    if command.origin_device_id == local_device_id:
        raise CommandRejected("DENIED", "Une commande ne peut pas venir d'elle-même.")
    public_key = registry.public_key_of(command.origin_device_id)
    if public_key is None:
        raise CommandRejected(
            "DENIED", "L'appareil émetteur n'est pas autorisé sur cet appareil."
        )

    # 5. expiry, with bounded clock tolerance in both directions
    if command.expires_at_ms <= command.created_at_ms:
        raise CommandRejected("EXPIRED", "Cette commande a une validité invalide.")
    if command.created_at_ms - MAX_CLOCK_SKEW_MS > stamp:
        raise CommandRejected("DENIED", "Cette commande est datée du futur.")
    if command.expires_at_ms + MAX_CLOCK_SKEW_MS < stamp:
        raise CommandRejected("EXPIRED", "Cette commande a expiré.")

    # 6. signature — over the envelope without itself
    from diapason.mesh.identity import verify_envelope

    if not command.signature:
        raise CommandRejected("DENIED", "Cette commande n'est pas signée.")
    if not verify_envelope(
        command.to_dict(with_signature=False), command.signature, public_key
    ):
        raise CommandRejected("DENIED", "La signature de cette commande est invalide.")

    # 7. tool must exist, be narrow, and be allowed remotely (spec §21)
    from diapason.mesh.tools import get_remote_tool

    spec = get_remote_tool(command.tool)
    if spec is None:
        raise CommandRejected(
            "UNSUPPORTED", f"L'outil « {command.tool} » n'existe pas."
        )

    # 8. arguments must match the tool's declared shape — no free-form passthrough
    spec.validate(command.arguments)

    # 9. capabilities — what THIS device can actually honour.
    #
    # Read from the platform ceiling, NOT from a registry row: a device is
    # never listed in its own registry, so looking itself up returned None
    # and this check quietly did nothing on every receiver. The sender's
    # identical check is not a substitute — it consults what the sender
    # recorded about us, which is exactly the thing an attacker would have
    # tampered with.
    from diapason.mesh.capabilities import local_capabilities

    if spec.capability not in local_capabilities():
        raise CommandRejected(
            "UNSUPPORTED",
            f"Cet appareil ne peut pas exécuter « {command.tool} ».",
        )

    # 10. risk / confirmation — an impactful tool may not run unconfirmed
    if spec.requires_confirmation and not command.requires_confirmation:
        raise CommandRejected(
            "DENIED",
            f"L'outil « {command.tool} » exige une confirmation explicite.",
        )

    # 11. nonce — spent last, and only once
    if not nonces.spend(command.nonce, command.origin_device_id):
        raise CommandRejected("DENIED", "Cette commande a déjà été reçue.")

    return command
