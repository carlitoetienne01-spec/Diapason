"""Les routes du transfert de fichiers : offrir, envoyer, finir.

Spatial Mesh, phase 3 — 25 août 2026. Quatre routes, une session, et une
créance qui n'est PAS la clé d'API : l'appareil qui envoie ne l'a pas.

- ``POST /v1/mesh/files/offer`` — enveloppe SIGNÉE Ed25519, vérifiée par le
  même ``verify_payload`` que les balises de présence : sept contrôles, dont
  la révocation. Elle annonce le manifeste et une clé publique éphémère, et
  rend une demande opaque. Elle ne crée encore ni dossier ni session.
- ``POST /v1/mesh/files/requests/{id}/state`` — jeton de demande ; rend
  PENDING, DENIED, EXPIRED, ou ouvre la session après l'accord humain.
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


@dataclass
class _Demande:
    """Une offre vérifiée qui attend encore le oui d'un humain."""

    request_id: str
    jeton: str
    action_id: str
    device_id: str
    manifeste: Any
    cle_emetteur: str
    ouverte_a: float = field(default_factory=time.monotonic)
    reponse_session: dict[str, Any] | None = None

    @property
    def perimee(self) -> bool:
        from diapason.mesh.demande_de_reception import REQUEST_TTL_S

        return (time.monotonic() - self.ouverte_a) > REQUEST_TTL_S

    @property
    def retirable(self) -> bool:
        """Keep an expired tombstone long enough to answer the sender."""
        from diapason.mesh.demande_de_reception import REQUEST_TTL_S

        return (time.monotonic() - self.ouverte_a) > REQUEST_TTL_S * 2


_demandes: dict[str, _Demande] = {}


def _purger() -> None:
    for sid in [s for s, v in _sessions.items() if v.perimee]:
        try:
            _sessions[sid].reception.abandonner()
        except Exception:  # noqa: BLE001
            pass
        _sessions.pop(sid, None)
    for demande in [d for d in _demandes.values() if d.perimee]:
        try:
            from diapason.mesh.demande_de_reception import expirer

            expirer(demande.action_id)
        except Exception:  # noqa: BLE001
            pass
    for request_id in [r for r, demande in _demandes.items() if demande.retirable]:
        _demandes.pop(request_id, None)


def reinitialiser_pour_tests() -> None:
    """Vider les sessions — les tests ne doivent pas se contaminer."""
    for session in list(_sessions.values()):
        try:
            session.reception.abandonner()
        except Exception:  # noqa: BLE001
            pass
    _sessions.clear()
    _demandes.clear()


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
    """Vérifier l'offre, puis demander — jamais accepter à la place de l'humain."""
    from diapason.mesh.demande_de_reception import REQUESTS_MAX, poser
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.registry import DeviceRegistry
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

    pendantes = sum(
        1
        for demande in _demandes.values()
        if not demande.perimee and not demande.reponse_session
    )
    if pendantes >= REQUESTS_MAX:
        raise HTTPException(
            status_code=429,
            detail=(
                "Trop de demandes attendent déjà une réponse. Réessaie dans un moment."
            ),
        )

    from diapason.mesh.registry import DeviceRegistry

    appareil = DeviceRegistry().find(device_id) or {
        "deviceId": device_id,
        "name": "Appareil appairé",
    }
    request_id = secrets.token_urlsafe(12).replace("-", "_")[:20]
    jeton = secrets.token_urlsafe(24)
    action_id = poser(manifeste, appareil)
    _demandes[request_id] = _Demande(
        request_id=request_id,
        jeton=jeton,
        action_id=action_id,
        device_id=device_id,
        manifeste=manifeste,
        cle_emetteur=body.ephemeralPublicKey,
    )
    logger.info(
        "transfert proposé : demande=%s de=%s taille=%d",
        request_id,
        device_id,
        manifeste.taille,
    )
    return _repondre(
        {
            "status": "PENDING",
            "requestId": request_id,
            "requestToken": jeton,
            "pollAfterMs": 2000,
            "expiresInS": 120,
            "userSafeMessage": "En attente de l'accord sur l'appareil destinataire.",
        }
    )


def _demande_autorisee(request_id: str, request: Request) -> _Demande:
    _purger()
    demande = _demandes.get(request_id)
    if demande is None:
        raise HTTPException(status_code=404, detail="Demande de transfert inconnue.")
    presente = request.headers.get("X-Transfer-Token", "")
    if not presente or not secrets.compare_digest(
        presente.encode("utf-8"), demande.jeton.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Jeton de demande invalide.")
    return demande


def _ouvrir_apres_accord(demande: _Demande) -> dict[str, Any]:
    """Créer la réception une fois, après le oui, et jamais avant."""
    if demande.reponse_session is not None:
        return dict(demande.reponse_session)
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
        cle = cle_de_session(demi, demande.cle_emetteur, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reception = ouvrir_reception(
        demande.manifeste,
        dossier_de_reception(),
        session_id=session_id,
        taille_max=_taille_max(),
    )
    upload_token = secrets.token_urlsafe(24)
    _sessions[session_id] = _Session(
        session_id=session_id,
        jeton=upload_token,
        device_id=demande.device_id,
        reception=reception,
        cle=cle,
    )
    demande.reponse_session = {
        "status": "ACCEPTED",
        "requestId": demande.request_id,
        "sessionId": session_id,
        "uploadToken": upload_token,
        "ephemeralPublicKey": demi.publique_b64,
        "missing": reception.manquants,
    }
    return dict(demande.reponse_session)


@router.post("/requests/{request_id}/state")
def etat_demande(request_id: str, request: Request) -> dict[str, Any]:
    """Sonder sans bloquer un fil serveur pendant que l'humain réfléchit."""
    from diapason.mesh.demande_de_reception import REQUEST_TTL_S, decision

    demande = _demande_autorisee(request_id, request)
    issue = decision(demande.action_id)
    if issue == "PENDING":
        restant = max(0, int(REQUEST_TTL_S - (time.monotonic() - demande.ouverte_a)))
        return _repondre(
            {
                "status": "PENDING",
                "requestId": request_id,
                "pollAfterMs": 2000,
                "remainingS": restant,
            }
        )
    if issue in {"DENIED", "EXPIRED"}:
        return _repondre(
            {
                "status": issue,
                "requestId": request_id,
                "userSafeMessage": (
                    "Le fichier a été refusé."
                    if issue == "DENIED"
                    else "Aucune réponse n'a été donnée — rien n'a été envoyé."
                ),
            }
        )
    return _repondre(_ouvrir_apres_accord(demande))


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
    logger.info("transfert terminé : %s", cible.name)
    return _repondre(
        {
            "status": "COMPLETE",
            "sessionId": session_id,
            "path": str(cible),
            "name": cible.name,
            "bytes": cible.stat().st_size,
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
