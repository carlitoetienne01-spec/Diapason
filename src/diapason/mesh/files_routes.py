"""File-transfer routes: offer, send, verify, publish.

Spatial Mesh, phase 3 — 25 August 2026. Four routes, one session, and a
credential that is NOT the API key: the sending device does not have it.

- ``POST /v1/mesh/files/offer`` — an Ed25519-signed envelope checked by the
  same ``verify_payload`` as presence beacons: seven checks, including
  revocation. Pairing is durable consent: a ``TRUSTED`` peer immediately
  receives a session without a second click for every file.
- ``POST /v1/mesh/files/{id}/chunk`` — one encrypted chunk authorized by the
  session token. The signature guards the door; the token guards the hall.
- ``POST /v1/mesh/files/{id}/finish`` — verifies the digest and exposes the
  file atomically.

The real ceiling on these routes is not a rate but a VOLUME, enforced here:
bytes received per session and the number of simultaneous sessions. A
request-rate limiter says nothing about body size.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/mesh/files", tags=["mesh-files"])

OFFER_VERSION = 1
_CHAMPS_SIGNES = (
    "version",
    "ownerId",
    "deviceId",
    "sentAtMs",
    "sessionNonce",
    "manifest",
    "ephemeralPublicKey",
)

# LA RÉPONSE AUSSI SE SIGNE, et elle ne le faisait pas.
#
# L'offre entrante était signée ; la réponse ne l'était pas. Or elle porte
# `ephemeralPublicKey` — la moitié de clé dont l'émetteur DÉRIVE la clé de
# session, sur parole (`envoi_fichier.py`). Quiconque se plaçait entre les
# deux appareils n'avait qu'à substituer sa propre moitié pour partager la
# clé avec l'émetteur, et lire le contenu de CHAQUE fichier transféré. Tout
# le chiffrement de `coffre.py` reposait sur un octet non authentifié.
#
# Inoffensif tant que la route n'écoutait que sur la loopback ; elle a été
# ouverte au réseau le 26 août 2026, et corrigée le même jour.
#
# `status` en fait partie : sans lui, un intercepteur forge un
# « ALREADY_PRESENT » et l'émetteur croit son fichier arrivé sans que rien
# ne soit parti.
_CHAMPS_REPONSE = (
    "version",
    "ownerId",
    "deviceId",
    "sentAtMs",
    "status",
    "requestId",
    "requestToken",
    "sessionId",
    "uploadToken",
    "ephemeralPublicKey",
    "pollAfterMs",
    "expiresInS",
    "remainingS",
    "missing",
    "path",
    "bytes",
    "userSafeMessage",
)


def _repondre(corps: dict[str, Any]) -> dict[str, Any]:
    """Signer une réponse d'offre avec l'identité de CETTE machine."""
    import time as _time

    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.signed import sign_payload

    complet = {
        "version": 1,
        "ownerId": owner_id(),
        "deviceId": device_identity().device_id,
        "sentAtMs": int(_time.time() * 1000),
        "requestId": "",
        "requestToken": "",
        "sessionId": "",
        "uploadToken": "",
        "ephemeralPublicKey": "",
        **corps,
    }
    return sign_payload(complet, _CHAMPS_REPONSE)


# Une session abandonnée ne doit pas tenir le disque indéfiniment.
_TTL_SESSION_S = 3600.0
# Au-delà, quelqu'un essaie autre chose que de partager un fichier.
_SESSIONS_MAX = 8

# How much the reception folder may hold, all files together.
#
# 28 August 2026 removed the per-file consent: a paired peer no longer has to
# ask. That was the right call for daily use — being asked for every file is
# how a safeguard turns into a reflex — but it took away the ONLY bound that
# existed, and nothing replaced it. An audit reproduced the consequence on
# this very code: three hundred files dropped in a row with the window shut,
# no approval and no event; and twenty manifests announcing two gibibytes
# each accepted without anything ever adding them up.
#
# Five gibibytes, and not less: one legitimate file may weigh
# TAILLE_MAX_DEFAUT (2 GiB), so a lower ceiling would refuse a normal send.
# And not more: past that, a folder nobody empties becomes a disk nobody
# understands.
_VOLUME_MAX_RECEPTION = 5 * 1024 * 1024 * 1024

# What we refuse to eat of someone else's disk. A folder ceiling does not
# protect a machine that is ALREADY nearly full: the two guards answer two
# different questions, and one does not imply the other.
_ESPACE_LIBRE_MINIMUM = 2 * 1024 * 1024 * 1024


@dataclass
class _Session:
    """Un transfert en cours, du côté qui reçoit."""

    session_id: str
    jeton: str
    device_id: str
    device_name: str
    reception: Any
    cle: bytes
    octets_recus: int = 0
    ouverte_a: float = field(default_factory=time.monotonic)

    @property
    def perimee(self) -> bool:
        return (time.monotonic() - self.ouverte_a) > _TTL_SESSION_S


_sessions: dict[str, _Session] = {}


def _purger() -> None:
    for sid in [s for s, v in _sessions.items() if v.perimee]:
        try:
            _sessions[sid].reception.abandonner()
        except Exception:  # noqa: BLE001
            pass
        _sessions.pop(sid, None)


def reinitialiser_pour_tests() -> None:
    """Vider les sessions — les tests ne doivent pas se contaminer."""
    for session in list(_sessions.values()):
        try:
            session.reception.abandonner()
        except Exception:  # noqa: BLE001
            pass
    _sessions.clear()


def dossier_de_reception() -> Path:
    from diapason.core.paths import get_data_dir

    return Path(get_data_dir()) / "transfers"


def _volume_recu() -> int:
    """What the reception folder already holds — partial files included.

    Partials count: they occupy the disk exactly like finished files, and a
    peer that opens sessions without ever finishing them would otherwise slip
    under the ceiling forever.
    """
    dossier = dossier_de_reception()
    total = 0
    try:
        enfants = list(dossier.iterdir())
    except OSError:
        return 0
    for enfant in enfants:
        try:
            if enfant.is_file():
                total += enfant.stat().st_size
        except OSError:
            # A file that vanished mid-scan is a file that costs nothing.
            continue
    return total


def _espace_libre() -> int | None:
    """Free bytes on the volume that holds the folder, or None if unknowable.

    None is not zero. A filesystem that will not answer must not be treated
    as full — refusing every transfer because a call failed would be the same
    class of lie as accepting every one.
    """
    import shutil

    dossier = dossier_de_reception()
    sonde = dossier if dossier.exists() else dossier.parent
    try:
        return shutil.disk_usage(sonde).free
    except OSError:
        return None


def _refus_de_volume(taille: int) -> str | None:
    """The sentence to refuse with, or None when there is room.

    Returns the user-facing reason rather than a boolean: a refusal the user
    cannot act on is barely better than a silent one.
    """
    dossier = dossier_de_reception()
    if _volume_recu() + taille > _VOLUME_MAX_RECEPTION:
        return (
            "Le dossier de réception est plein "
            f"({_VOLUME_MAX_RECEPTION // (1024 * 1024 * 1024)} Gio) : ce fichier "
            f"n'a pas été accepté. Vide « {dossier} » pour en recevoir d'autres."
        )
    libre = _espace_libre()
    if libre is not None and libre - taille < _ESPACE_LIBRE_MINIMUM:
        return (
            "Il ne reste pas assez de place sur le disque de cet appareil : "
            "ce fichier n'a pas été accepté."
        )
    return None


def _taille_max() -> int:
    from diapason.mesh.transfert import TAILLE_MAX_DEFAUT

    return TAILLE_MAX_DEFAUT


def _display_name(value: Any) -> str:
    """Keep a paired-device label from changing how the arrival card reads."""
    clean = "".join(
        character
        for character in unicodedata.normalize("NFC", str(value or ""))
        if not unicodedata.category(character).startswith("C")
    )
    return " ".join(clean.split())[:80] or "Appareil jumelé"


class Offre(BaseModel):
    """A signed file announcement from an already trusted peer."""

    version: int = OFFER_VERSION
    ownerId: str = ""
    deviceId: str = ""
    sentAtMs: int = 0
    sessionNonce: str = Field(default="", max_length=64)
    manifest: dict = Field(default_factory=dict)
    ephemeralPublicKey: str = Field(default="", max_length=100)
    signature: str = Field(default="", max_length=200)


@router.post("/offer")
def offrir(body: Offre) -> dict[str, Any]:
    """Verify the offer and open a session for that already trusted peer."""
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.registry import TRUST_TRUSTED, DeviceRegistry
    from diapason.mesh.signed import SignedRejected, verify_payload
    from diapason.mesh.transfert import (
        Manifeste,
        RefusDeTransfert,
        deja_present,
        verifier_le_manifeste,
    )

    _purger()
    if len(_sessions) >= _SESSIONS_MAX:
        raise HTTPException(
            status_code=429,
            detail="Trop de transferts en cours. Réessaie dans un moment.",
        )

    registry = DeviceRegistry()
    brut = body.model_dump()
    try:
        device_id = verify_payload(
            brut,
            fields=_CHAMPS_SIGNES,
            version=OFFER_VERSION,
            registry=registry,
            local_owner_id=owner_id(),
            local_device_id=device_identity().device_id,
            now_ms=int(time.time() * 1000),
            subject="offre de fichier",
        )
    except SignedRejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # `verify_payload` already accepts only a TRUSTED peer key. Reading the
    # row again closes the small race where the device is revoked immediately
    # after signature verification, before even deduplication can reveal a
    # file already present on this machine.
    appareil = registry.find(device_id)
    if appareil is None or appareil.get("trustLevel") != TRUST_TRUSTED:
        raise HTTPException(
            status_code=403,
            detail="Cet appareil n'est plus autorisé à envoyer des fichiers.",
        )

    try:
        manifeste = Manifeste.from_dict(body.manifest or {})
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(
            status_code=400, detail="Manifeste de fichier illisible."
        ) from exc
    dossier = dossier_de_reception()

    # Vérifier le manifeste ne crée ni dossier ni fichier. Avant cette
    # séparation, `ouvrir_reception` faisait mkdir puis répondait ACCEPTED :
    # la décision était prise et le disque touché avant le premier regard.
    try:
        verifier_le_manifeste(manifeste, taille_max=_taille_max())
    except RefusDeTransfert as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    # Déduplication AVANT tout octet (§45) : si le contenu est déjà là,
    # l'annoncer coûte une réponse, le transférer coûterait le fichier.
    existant = deja_present(manifeste, dossier)
    if existant is not None:
        return _repondre(
            {
                "status": "ALREADY_PRESENT",
                "path": str(existant),
                "userSafeMessage": (
                    f"« {existant.name} » est déjà là — rien à envoyer."
                ),
            }
        )

    # A paired peer no longer has to ask (28 August 2026), and that is
    # deliberate. But "no longer asks" must not mean "without limit": these
    # two guards are the whole of what now stands between a paired device
    # gone hostile and a full disk. Checked AFTER deduplication on purpose —
    # a file already present costs no bytes, and refusing it for lack of room
    # would be refusing something we were not going to store.
    refus = _refus_de_volume(manifeste.taille)
    if refus is not None:
        logger.warning(
            "file transfer refused for lack of room: from=%s size=%d",
            device_id,
            manifeste.taille,
        )
        raise HTTPException(status_code=507, detail=refus)

    reponse = _open_session(
        device_id=device_id,
        device_name=_display_name(appareil.get("name")),
        manifeste=manifeste,
        sender_public_key=body.ephemeralPublicKey,
    )
    logger.info(
        "file transfer accepted automatically: from=%s size=%d",
        device_id,
        manifeste.taille,
    )
    return _repondre(reponse)


def _open_session(
    *,
    device_id: str,
    device_name: str,
    manifeste: Any,
    sender_public_key: str,
) -> dict[str, Any]:
    """Create one encrypted upload session for a verified trusted peer."""
    if len(_sessions) >= _SESSIONS_MAX:
        raise HTTPException(
            status_code=429,
            detail="Trop de transferts en cours. Réessaie dans un moment.",
        )
    from diapason.mesh.coffre import cle_de_session, nouvelle_demi_cle
    from diapason.mesh.transfert import ouvrir_reception

    session_id = secrets.token_urlsafe(18).replace("-", "_")[:32]
    demi = nouvelle_demi_cle()
    try:
        cle = cle_de_session(demi, sender_public_key, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reception = ouvrir_reception(
        manifeste,
        dossier_de_reception(),
        session_id=session_id,
        taille_max=_taille_max(),
    )
    upload_token = secrets.token_urlsafe(24)
    _sessions[session_id] = _Session(
        session_id=session_id,
        jeton=upload_token,
        device_id=device_id,
        device_name=device_name,
        reception=reception,
        cle=cle,
    )
    return {
        "status": "ACCEPTED",
        "sessionId": session_id,
        "uploadToken": upload_token,
        "ephemeralPublicKey": demi.publique_b64,
        "missing": reception.manquants,
        "userSafeMessage": "Appareil jumelé — transfert autorisé.",
    }


def journal_des_receptions() -> Path:
    from diapason.core.paths import get_data_dir

    return Path(get_data_dir()) / "receptions.jsonl"


def _record_arrival(session: _Session, target: Path, size: int) -> None:
    """Write the arrival down, whether or not anyone is watching.

    Until now the only trace of a received file was the shell animation, and
    `_publish_received_file` drops that when no window is collecting. With
    consent gone, a file could therefore arrive on this machine leaving
    nothing behind but a `logger.info` line in a file nobody reads — and the
    user had no way to find out who had sent what, or when.

    A line of JSON, appended, never rewritten. Not a database: this must
    survive a corrupt tail, be readable with `tail`, and cost nothing to
    write on a path that is already doing disk work.
    """
    entree = {
        "receivedAtMs": int(time.time() * 1000),
        "fileName": target.name,
        "path": str(target),
        "sizeBytes": size,
        "mimeType": session.reception.manifeste.type_mime,
        "sourceDeviceId": session.device_id,
        "sourceDeviceName": session.device_name,
        "sessionId": session.session_id,
    }
    chemin = journal_des_receptions()
    try:
        from diapason.security.file_utils import secure_create

        secure_create(chemin)
        with chemin.open("a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except OSError:
        # The file HAS arrived. Losing its journal line must not undo that,
        # nor turn a completed transfer into an error for the sender.
        logger.exception("could not record the arrival of %s", target.name)


def _publish_received_file(session: _Session, target: Path, size: int) -> None:
    """Tell an attached shell, without making UI delivery part of file truth."""
    from diapason.mesh.executor import push_shell_event, shell_is_collecting

    # The server may receive while the Tauri shell is closed. The file still
    # arrived, but queuing a windowless animation would make it appear out of
    # context hours later. The visual event therefore remains opportunistic.
    if not shell_is_collecting():
        return
    queued = push_shell_event(
        {
            "fileReceived": {
                "fileName": target.name,
                "sizeBytes": size,
                "mimeType": session.reception.manifeste.type_mime,
                "sourceDeviceId": session.device_id,
                "sourceDeviceName": session.device_name,
            },
            "commandId": f"transfer:{session.session_id}",
            "originDeviceId": session.device_id,
            "receivedAtMs": int(time.time() * 1000),
        }
    )
    if not queued:
        logger.warning(
            "file arrived but shell event queue is full: session=%s",
            session.session_id,
        )


def _session_autorisee(session_id: str, request: Request) -> _Session:
    _purger()
    session = _sessions.get(session_id)
    if session is None or session.perimee:
        raise HTTPException(status_code=404, detail="Session de transfert inconnue.")
    presente = request.headers.get("X-Transfer-Token", "")
    # Comparaison à temps constant : un jeton ne se devine pas octet par
    # octet en mesurant les réponses.
    if not presente or not secrets.compare_digest(
        presente.encode("utf-8"), session.jeton.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Jeton de transfert invalide.")
    return session


@router.post("/{session_id}/chunk")
async def morceau(session_id: str, index: int, request: Request) -> dict[str, Any]:
    """Recevoir un morceau chiffré, à sa place exacte."""
    from diapason.mesh.coffre import desceller
    from diapason.mesh.transfert import RefusDeTransfert

    session = _session_autorisee(session_id, request)
    scelle = await request.body()
    # LE plafond qui compte : un limiteur de requêtes ne dit rien de la
    # taille d'un corps. On borne ce qu'une session a le droit de peser.
    plafond = session.reception.manifeste.taille + (1024 * 64)
    if session.octets_recus + len(scelle) > plafond:
        session.reception.abandonner()
        _sessions.pop(session_id, None)
        raise HTTPException(
            status_code=413,
            detail="Cette session a envoyé plus que ce qu'elle avait annoncé.",
        )
    try:
        clair = desceller(session.cle, index, scelle)
        session.reception.ecrire(index, clair)
    except (ValueError, RefusDeTransfert) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.octets_recus += len(scelle)
    return {
        "received": index,
        "missing": session.reception.manquants,
        "complete": session.reception.complet,
    }


@router.post("/{session_id}/finish")
def finir(session_id: str, request: Request) -> dict[str, Any]:
    """Vérifier l'empreinte, puis rendre le fichier visible d'un seul coup."""
    from diapason.mesh.transfert import RefusDeTransfert

    session = _session_autorisee(session_id, request)
    try:
        cible = session.reception.finaliser()
    except RefusDeTransfert as exc:
        _sessions.pop(session_id, None)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _sessions.pop(session_id, None)
    taille = cible.stat().st_size
    # Recorded BEFORE the shell is told: the journal is what makes the
    # arrival true, the animation is only what makes it visible.
    _record_arrival(session, cible, taille)
    _publish_received_file(session, cible, taille)
    logger.info("file transfer complete: %s", cible.name)
    return _repondre(
        {
            "status": "COMPLETE",
            "sessionId": session_id,
            "path": str(cible),
            "name": cible.name,
            "bytes": taille,
            "userSafeMessage": f"« {cible.name} » est arrivé.",
        }
    )


@router.post("/{session_id}/status")
def etat(session_id: str, request: Request) -> dict[str, Any]:
    """Ce qui manque encore — c'est là que vit la reprise."""
    session = _session_autorisee(session_id, request)
    return {
        "sessionId": session_id,
        "missing": session.reception.manquants,
        "complete": session.reception.complet,
    }


__all__ = [
    "OFFER_VERSION",
    "dossier_de_reception",
    "reinitialiser_pour_tests",
    "router",
]
