"""Les routes du transfert de fichiers : offrir, envoyer, finir.

Spatial Mesh, phase 3 — 25 août 2026. Trois routes, une session, et une
créance qui n'est PAS la clé d'API : l'appareil qui envoie ne l'a pas.

- ``POST /v1/mesh/files/offer`` — enveloppe SIGNÉE Ed25519, vérifiée par le
  même ``verify_payload`` que les balises de présence : sept contrôles, dont
  la révocation. Elle annonce le manifeste et une clé publique éphémère, et
  rend un identifiant de session, un jeton, et la clé éphémère du récepteur.
- ``POST /v1/mesh/files/{id}/chunk`` — un morceau chiffré, autorisé par le
  jeton de session. Le jeton n'existe que si l'offre a été acceptée : la
  signature garde la porte, le jeton garde le couloir.
- ``POST /v1/mesh/files/{id}/finish`` — vérifie l'empreinte et rend le
  fichier visible d'un seul coup.

Le vrai plafond de ces routes n'est pas un débit mais un VOLUME, et il vit
ici : octets déjà reçus par session, et nombre de sessions simultanées. Un
limiteur de requêtes ne dit rien de la taille d'un corps.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

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

# Une session abandonnée ne doit pas tenir le disque indéfiniment.
_TTL_SESSION_S = 3600.0
# Au-delà, quelqu'un essaie autre chose que de partager un fichier.
_SESSIONS_MAX = 8


@dataclass
class _Session:
    """Un transfert en cours, du côté qui reçoit."""

    session_id: str
    jeton: str
    device_id: str
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


def _taille_max() -> int:
    from diapason.mesh.transfert import TAILLE_MAX_DEFAUT

    return TAILLE_MAX_DEFAUT


class Offre(BaseModel):
    """L'annonce signée d'un fichier. Rien n'est reçu avant son acceptation."""

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
    """Accepter — ou refuser — un fichier AVANT le premier octet."""
    from diapason.mesh.coffre import cle_de_session, nouvelle_demi_cle
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.registry import DeviceRegistry
    from diapason.mesh.signed import SignedRejected, verify_payload
    from diapason.mesh.transfert import (
        Manifeste,
        RefusDeTransfert,
        deja_present,
        ouvrir_reception,
    )

    _purger()
    if len(_sessions) >= _SESSIONS_MAX:
        raise HTTPException(
            status_code=429,
            detail="Trop de transferts en cours. Réessaie dans un moment.",
        )

    brut = body.model_dump()
    try:
        device_id = verify_payload(
            brut,
            fields=_CHAMPS_SIGNES,
            version=OFFER_VERSION,
            registry=DeviceRegistry(),
            local_owner_id=owner_id(),
            local_device_id=device_identity().device_id,
            now_ms=int(time.time() * 1000),
            subject="offre de fichier",
        )
    except SignedRejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    manifeste = Manifeste.from_dict(body.manifest or {})
    dossier = dossier_de_reception()

    # Déduplication AVANT tout octet (§45) : si le contenu est déjà là,
    # l'annoncer coûte une réponse, le transférer coûterait le fichier.
    existant = deja_present(manifeste, dossier)
    if existant is not None:
        return {
            "status": "ALREADY_PRESENT",
            "path": str(existant),
            "userSafeMessage": f"« {existant.name} » est déjà là — rien à envoyer.",
        }

    session_id = secrets.token_urlsafe(18).replace("-", "_")[:32]
    try:
        reception = ouvrir_reception(
            manifeste, dossier, session_id=session_id, taille_max=_taille_max()
        )
    except RefusDeTransfert as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    demi = nouvelle_demi_cle()
    try:
        cle = cle_de_session(demi, body.ephemeralPublicKey, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    jeton = secrets.token_urlsafe(24)
    _sessions[session_id] = _Session(
        session_id=session_id,
        jeton=jeton,
        device_id=device_id,
        reception=reception,
        cle=cle,
    )
    logger.info(
        "transfert accepté : session=%s de=%s taille=%d",
        session_id,
        device_id,
        manifeste.taille,
    )
    return {
        "status": "ACCEPTED",
        "sessionId": session_id,
        "uploadToken": jeton,
        "ephemeralPublicKey": demi.publique_b64,
        "missing": reception.manquants,
    }


def _session_autorisee(session_id: str, request: Request) -> _Session:
    session = _sessions.get(session_id)
    if session is None or session.perimee:
        raise HTTPException(status_code=404, detail="Session de transfert inconnue.")
    presente = request.headers.get("X-Transfer-Token", "")
    # Comparaison à temps constant : un jeton ne se devine pas octet par
    # octet en mesurant les réponses.
    if not presente or not secrets.compare_digest(presente, session.jeton):
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
    logger.info("transfert terminé : %s", cible.name)
    return {
        "status": "COMPLETE",
        "path": str(cible),
        "name": cible.name,
        "bytes": cible.stat().st_size,
        "userSafeMessage": f"« {cible.name} » est arrivé.",
    }


@router.post("/{session_id}/status")
def etat(session_id: str, request: Request) -> dict[str, Any]:
    """Ce qui manque encore — c'est là que vit la reprise."""
    session = _session_autorisee(session_id, request)
    return {
        "sessionId": session_id,
        "missing": session.reception.manquants,
        "complete": session.reception.complet,
    }


__all__ = ["OFFER_VERSION", "dossier_de_reception", "reinitialiser_pour_tests", "router"]
