"""Envoyer un fichier à un appareil de la flotte — le côté qui pousse.

Spatial Mesh, phase 3 — 25 août 2026. Le pendant de ``files_routes``. Il
annonce, attend l'accord, chiffre morceau par morceau, et ne dit « arrivé »
que quand le RÉCEPTEUR l'a dit.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DELAI_S = 30.0


class EnvoiRefuse(RuntimeError):
    """Le transfert n'a pas eu lieu, et le message dit pourquoi."""


@dataclass(frozen=True, slots=True)
class Envoi:
    statut: str
    message: str
    chemin_distant: str = ""
    octets: int = 0
    morceaux: int = 0


def envoyer_fichier(
    chemin: Path | str,
    device: dict,
    *,
    poster: Any = None,
    progression: Any = None,
    attente: Any = None,
    dormir: Any = time.sleep,
    maintenant: Any = time.monotonic,
) -> Envoi:
    """Pousser un fichier vers un appareil déjà appairé.

    ``device`` est la ligne du registre : il porte l'adresse et le niveau de
    confiance. La vérification que l'on a le DROIT de le joindre reste celle
    du transport — un seul endroit décide de ce qui sort de la machine.
    """

    from diapason.mesh.coffre import cle_de_session, nouvelle_demi_cle
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.signed import sign_payload
    from diapason.mesh.transfert import decrire_fichier, lire_morceaux
    from diapason.mesh.transport import assert_may_reach_device

    chemin = Path(chemin).expanduser()
    if not chemin.is_file():
        raise EnvoiRefuse(f"{chemin} n'est pas un fichier.")
    adresse = str(device.get("address") or "").strip()
    if not adresse:
        raise EnvoiRefuse("L'adresse de cet appareil est inconnue.")
    # Le même garde que pour les commandes : ce qui sort de la machine passe
    # par une seule porte, jamais par une seconde écrite pour l'occasion.
    assert_may_reach_device(device, adresse)

    manifeste = decrire_fichier(chemin)
    demi = nouvelle_demi_cle()
    offre = sign_payload(
        {
            "version": 1,
            "ownerId": owner_id(),
            "deviceId": device_identity().device_id,
            "sentAtMs": int(time.time() * 1000),
            "sessionNonce": secrets.token_urlsafe(12),
            "manifest": manifeste.to_dict(),
            "ephemeralPublicKey": demi.publique_b64,
        },
        _champs(),
    )

    base = adresse.rstrip("/")
    envoyer = poster or _poster
    reponse = _verifier_reponse(
        envoyer(f"{base}/v1/mesh/files/offer", offre, None), device
    )

    if reponse.get("status") == "ALREADY_PRESENT":
        return Envoi(
            statut="ALREADY_PRESENT",
            message=str(reponse.get("userSafeMessage") or "Déjà présent."),
            chemin_distant=str(reponse.get("path") or ""),
        )

    if reponse.get("status") == "PENDING":
        request_id = str(reponse.get("requestId") or "")
        request_token = str(reponse.get("requestToken") or "")
        if not request_id or not request_token:
            raise EnvoiRefuse("La demande d'accord du destinataire est incomplète.")
        message_attente = str(
            reponse.get("userSafeMessage")
            or "En attente de l'accord sur l'appareil destinataire."
        )
        if attente is not None:
            try:
                attente(message_attente)
            except Exception:  # noqa: BLE001 - l'affichage n'arrête pas l'envoi
                pass

        try:
            delai_accord = int(reponse.get("expiresInS") or 120)
        except (TypeError, ValueError, OverflowError):
            delai_accord = 120
        # La réponse est signée, mais le récepteur ne décide pas combien de
        # temps l'émetteur garde une commande bloquée. Deux minutes est aussi
        # le TTL côté réception : plus long ne pourrait que sonder un cadavre.
        limite = maintenant() + min(max(delai_accord, 1), 120)
        while reponse.get("status") == "PENDING":
            restant = limite - maintenant()
            if restant <= 0:
                return Envoi(
                    statut="EXPIRED",
                    message="Aucune réponse n'a été donnée — rien n'a été envoyé.",
                )
            try:
                pause = float(reponse.get("pollAfterMs") or 2000) / 1000
            except (TypeError, ValueError, OverflowError):
                pause = 2.0
            dormir(min(max(pause, 0.25), 5.0, restant))
            reponse = _verifier_reponse(
                envoyer(
                    f"{base}/v1/mesh/files/requests/{request_id}/state",
                    {},
                    request_token,
                ),
                device,
            )
            rendu_id = str(reponse.get("requestId") or "")
            if rendu_id and rendu_id != request_id:
                raise EnvoiRefuse("Le destinataire a répondu à une autre demande.")

    statut = str(reponse.get("status") or "")
    if statut in {"DENIED", "EXPIRED"}:
        return Envoi(
            statut=statut,
            message=str(
                reponse.get("userSafeMessage")
                or "Le destinataire n'a pas accepté ce fichier."
            ),
        )
    if statut != "ACCEPTED":
        raise EnvoiRefuse(
            f"Réponse inattendue du destinataire : {statut or 'sans statut'}."
        )

    session_id = str(reponse.get("sessionId") or "")
    jeton = str(reponse.get("uploadToken") or "")
    if not session_id or not jeton:
        raise EnvoiRefuse("L'appareil n'a pas ouvert de session de transfert.")
    cle = cle_de_session(demi, str(reponse.get("ephemeralPublicKey") or ""), session_id)

    from diapason.mesh.coffre import sceller

    envoyes = 0
    for index, bloc in lire_morceaux(chemin):
        envoyer(
            f"{base}/v1/mesh/files/{session_id}/chunk?index={index}",
            sceller(cle, index, bloc),
            jeton,
        )
        envoyes += 1
        if progression is not None:
            try:
                progression(envoyes, manifeste.morceaux)
            except Exception:  # noqa: BLE001 - l'affichage n'arrête pas l'envoi
                pass

    fin = _verifier_reponse(
        envoyer(f"{base}/v1/mesh/files/{session_id}/finish", {}, jeton), device
    )
    if str(fin.get("sessionId") or "") != session_id:
        raise EnvoiRefuse("Le destinataire a confirmé une autre session.")
    # La phrase vient du récepteur : lui seul a vérifié l'empreinte. Depuis le
    # 26 août 2026, sa confirmation est signée elle aussi ; sinon un voisin
    # pouvait forger COMPLETE après avoir jeté le dernier morceau.
    return Envoi(
        statut=str(fin.get("status") or "?"),
        message=str(fin.get("userSafeMessage") or ""),
        chemin_distant=str(fin.get("path") or ""),
        octets=int(fin.get("bytes") or 0),
        morceaux=envoyes,
    )


def _verifier_reponse(
    reponse: dict[str, Any], device: dict[str, Any]
) -> dict[str, Any]:
    """Refuser toute décision de transfert qui ne vient pas de la cible."""
    from diapason.mesh.files_routes import _CHAMPS_REPONSE
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.registry import DeviceRegistry
    from diapason.mesh.signed import SignedRejected, verify_payload

    try:
        signataire = verify_payload(
            reponse,
            fields=_CHAMPS_REPONSE,
            version=1,
            registry=DeviceRegistry(),
            local_owner_id=owner_id(),
            local_device_id=device_identity().device_id,
            now_ms=int(time.time() * 1000),
            subject="réponse de transfert",
        )
    except SignedRejected as exc:
        raise EnvoiRefuse(f"Réponse de transfert refusée : {exc}") from exc

    # Signée par un pair de la flotte, oui — mais par CELUI qu'on visait ?
    # Sans ce contrôle, un autre appareil jumelé pourrait se glisser à la
    # place du destinataire.
    vise = str(device.get("deviceId") or "")
    if vise and signataire != vise:
        raise EnvoiRefuse(f"La réponse vient de {signataire}, pas de l'appareil visé.")
    return reponse


def _champs():
    from diapason.mesh.files_routes import _CHAMPS_SIGNES

    return _CHAMPS_SIGNES


def _poster(url: str, charge: Any, jeton: Optional[str]) -> dict:
    """Le POST réel — JSON pour l'offre, octets bruts pour un morceau."""
    import httpx

    entetes = {"X-Transfer-Token": jeton} if jeton else {}
    try:
        if isinstance(charge, (bytes, bytearray)):
            entetes["Content-Type"] = "application/octet-stream"
            reponse = httpx.post(
                url, content=bytes(charge), headers=entetes, timeout=_DELAI_S
            )
        else:
            reponse = httpx.post(url, json=charge, headers=entetes, timeout=_DELAI_S)
    except httpx.HTTPError as exc:
        raise EnvoiRefuse(
            f"Cet appareil n'a pas pu être joint : {str(exc)[:100]}"
        ) from exc
    if reponse.status_code >= 400:
        detail = ""
        try:
            detail = str((reponse.json() or {}).get("detail") or "")
        except Exception:  # noqa: BLE001
            detail = reponse.text[:150]
        raise EnvoiRefuse(detail or f"Refusé (HTTP {reponse.status_code}).")
    return reponse.json()


__all__ = ["Envoi", "EnvoiRefuse", "envoyer_fichier"]
