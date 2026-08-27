"""Human consent for one incoming file, backed by the existing approval bell."""

from __future__ import annotations

import unicodedata
from typing import Any

ACTION_TYPE = "file_transfer"
REQUEST_TTL_S = 120
REQUESTS_MAX = 3


def _texte_sur(texte: str, maximum: int = 80) -> str:
    """Remove invisible direction controls from text shown to the user."""
    propre = "".join(
        caractere
        for caractere in unicodedata.normalize("NFC", str(texte or ""))
        if unicodedata.category(caractere) != "Cf"
    )
    propre = " ".join(propre.split())
    return propre[:maximum] or "appareil inconnu"


def taille_lisible(octets: int) -> str:
    for unite, seuil in (("Go", 1 << 30), ("Mo", 1 << 20), ("Ko", 1 << 10)):
        if octets >= seuil:
            return f"{octets / seuil:.1f} {unite}"
    return f"{max(0, int(octets))} o"


def poser(manifeste: Any, appareil: dict[str, Any]) -> str:
    """Queue an always-ask action and return its durable action id."""
    from diapason.server.approval_bridge import announce_approval
    from diapason.tools.approval_store import TIER_HIGH, ApprovalStore

    nom = _texte_sur(getattr(manifeste, "nom", ""), 120)
    appareil_nom = _texte_sur(str(appareil.get("name") or ""))
    taille = taille_lisible(int(getattr(manifeste, "taille", 0)))
    description = f"« {nom} » ({taille}) — de « {appareil_nom} »"
    store = ApprovalStore()
    try:
        action = store.queue_action(
            action_type=ACTION_TYPE,
            description=description,
            payload={
                "fileName": nom,
                "sizeBytes": int(getattr(manifeste, "taille", 0)),
                "mimeType": str(getattr(manifeste, "type_mime", "")),
                "deviceId": str(appareil.get("deviceId") or ""),
                "deviceName": appareil_nom,
            },
            permission_key=(
                f"mesh.file_receive:{str(appareil.get('deviceId') or 'unknown')}"
            ),
            # A file is content, not a routine command. A previous "yes"
            # never grants a future sender permanent permission.
            tier=TIER_HIGH,
            ttl_hours=1,
        )
    finally:
        store.close()
    announce_approval(
        "Un appareil veut t'envoyer un fichier",
        f"{description} — accepte ou refuse dans Diapason ({REQUEST_TTL_S} s).",
    )
    return action.id


def decision(action_id: str) -> str:
    """PENDING, ACCEPTED, DENIED or EXPIRED; an approval is consumed once."""
    from diapason.tools.approval_store import (
        STATUS_APPROVED,
        STATUS_DENIED,
        STATUS_EXECUTED,
        STATUS_EXPIRED,
        STATUS_PENDING,
        ApprovalStore,
    )

    store = ApprovalStore()
    try:
        action = store.get_action(action_id)
        if action is None:
            return "EXPIRED"
        if action.status == STATUS_APPROVED:
            store.update_status(action_id, STATUS_EXECUTED)
            return "ACCEPTED"
        # execute_pending_actions can consume an approved row between two
        # polls. EXECUTED still means the human said yes; treating it as a no
        # would invert their decision.
        if action.status == STATUS_EXECUTED:
            return "ACCEPTED"
        if action.status == STATUS_DENIED:
            return "DENIED"
        if action.status == STATUS_EXPIRED:
            return "EXPIRED"
        return "PENDING" if action.status == STATUS_PENDING else "EXPIRED"
    finally:
        store.close()


def expirer(action_id: str) -> None:
    from diapason.tools.approval_store import STATUS_EXPIRED, ApprovalStore

    store = ApprovalStore()
    try:
        action = store.get_action(action_id)
        if action is not None and action.status == "pending":
            store.update_status(action_id, STATUS_EXPIRED)
    finally:
        store.close()


__all__ = [
    "ACTION_TYPE",
    "REQUESTS_MAX",
    "REQUEST_TTL_S",
    "decision",
    "expirer",
    "poser",
    "taille_lisible",
]
