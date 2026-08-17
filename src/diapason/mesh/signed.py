"""What a paired device must prove to be heard, whatever it is saying.

Three surfaces are open to devices that hold no API key — the presence
beacon, the command poll, and the result acknowledgement — and all three
answer the same question first: *is this really that device, saying this,
now?* The answer is one Ed25519 signature and seven checks, and they live
here so there is exactly one copy of them to get right.

What each surface signs stays its own business: every caller passes the
explicit tuple of fields covered by the signature. Listing them rather than
signing "everything but the signature" means adding a field later is a
deliberate act with a version bump, not an accident that silently changes
what is protected.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = [
    "SignedRejected",
    "MAX_SIGNED_SKEW_MS",
    "signable",
    "sign_payload",
    "verify_payload",
]

# A claim about *now* that is half a minute stale is not about now. Shorter
# than the command window on purpose: a command carries its own expiry and
# may legitimately wait, whereas presence and polls are only ever current.
MAX_SIGNED_SKEW_MS = 30_000


class SignedRejected(Exception):
    """Refused, with a reason already written for the user in French."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def signable(payload: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """The exact subset the signature covers, in a stable order."""
    return {field: payload.get(field) for field in fields}


def sign_payload(payload: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """Return *payload* with this device's signature over *fields* attached."""
    from diapason.mesh.identity import sign_envelope

    body = dict(payload)
    body["signature"] = sign_envelope(signable(body, fields))
    return body


def verify_payload(
    raw: Mapping[str, Any],
    *,
    fields: Sequence[str],
    version: int,
    registry: Any,
    local_owner_id: str,
    local_device_id: str,
    now_ms: int,
    stamp_field: str = "sentAtMs",
    subject: str = "requête",
) -> str:
    """Run the seven checks every device-signed request must pass.

    Order matches ``verify_command``: the cheap structural checks first, so a
    malformed or misaddressed payload never reaches the cryptography.

    ``subject`` names the thing being refused, so somebody debugging why their
    phone will not pair reads « Cette relève est trop ancienne » rather than a
    generic noun. It must be a FEMININE French noun — the sentences below
    agree with it (« Cette … n'est pas signée »).

    @returns the verified sending device id.
    """
    if int(raw.get("version") or 0) != version:
        raise SignedRejected(
            "UNSUPPORTED", f"Cette {subject} utilise une version non prise en charge."
        )

    owner = str(raw.get("ownerId") or "")
    if not owner or owner != local_owner_id:
        raise SignedRejected(
            "DENIED", f"Cette {subject} vient d'un autre ensemble d'appareils."
        )

    device_id = str(raw.get("deviceId") or "")
    if not device_id:
        raise SignedRejected("DENIED", f"Cette {subject} ne dit pas qui l'envoie.")
    if device_id == local_device_id:
        raise SignedRejected("DENIED", "Un appareil ne s'adresse pas à lui-même.")

    # A revoked device holds no key here, so revocation stops it at once —
    # the same single choke point revocation already uses for commands.
    public_key = registry.public_key_of(device_id)
    if public_key is None:
        raise SignedRejected(
            "DENIED", "Cet appareil n'est pas autorisé sur cette machine."
        )

    sent_at = int(raw.get(stamp_field) or 0)
    if sent_at - MAX_SIGNED_SKEW_MS > now_ms:
        raise SignedRejected("DENIED", f"Cette {subject} est datée du futur.")
    if sent_at + MAX_SIGNED_SKEW_MS < now_ms:
        raise SignedRejected("EXPIRED", f"Cette {subject} est trop ancienne.")

    from diapason.mesh.identity import verify_envelope

    signature = str(raw.get("signature") or "")
    if not signature:
        raise SignedRejected("DENIED", f"Cette {subject} n'est pas signée.")
    if not verify_envelope(signable(raw, fields), signature, public_key):
        raise SignedRejected("DENIED", f"La signature de cette {subject} est invalide.")

    return device_id
