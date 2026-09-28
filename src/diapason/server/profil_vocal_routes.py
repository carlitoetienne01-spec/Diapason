"""Enregistrement explicite de la voix, réservé au bureau local (§78)."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from diapason.core.origine_telephone import depuis_le_telephone
from diapason.speech.speaker_id import (
    PHRASES_GUIDEES,
    ProfilVocalInvalide,
    get_verifier,
)


def reserver_au_bureau(request: Request) -> None:
    if depuis_le_telephone() or request.scope.get("diapason.appareil"):
        raise HTTPException(status_code=403, detail="desktopOnly")


profil_vocal_router = APIRouter(
    prefix="/v1/voice/profile",
    tags=["voice-profile"],
    dependencies=[Depends(reserver_au_bureau)],
)


class CaptureProfil(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # PCM16 mono, 16 kHz, huit secondes au plus, transmis en JSON pour WKWebView.
    audio: str = Field(min_length=4, max_length=341336)

    def pcm(self) -> bytes:
        try:
            pcm = base64.b64decode(self.audio, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(
                status_code=400, detail={"reason": "invalidSample"}
            ) from exc
        if not pcm or len(pcm) % 2 or len(pcm) > 256000:
            raise HTTPException(status_code=400, detail={"reason": "invalidSample"})
        return pcm


class EssaiProfil(CaptureProfil):
    index: int = Field(ge=0, lt=PHRASES_GUIDEES)


class EnregistrementProfil(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1, max_length=64)
    samples: list[CaptureProfil] = Field(
        min_length=PHRASES_GUIDEES, max_length=PHRASES_GUIDEES
    )


def traduire_erreur(exc: ProfilVocalInvalide) -> HTTPException:
    return HTTPException(
        status_code=409 if exc.motif == "conflict" else 422,
        detail={"reason": exc.motif, "index": exc.indice},
    )


@profil_vocal_router.get("")
def etat_profil() -> dict:
    v = get_verifier()
    return {"enrolled": v.arme, "sampleCount": v.echantillons, "revision": v.revision}


@profil_vocal_router.post("/sample")
def verifier_capture(capture: EssaiProfil) -> dict:
    # Routes synchrones : ONNX et le disque tournent dans le pool Starlette,
    # jamais sur la boucle qui porte le WebSocket vocal (27/09/2026).
    try:
        get_verifier().preparer_echantillon(capture.pcm(), capture.index)
    except ProfilVocalInvalide as exc:
        raise traduire_erreur(exc) from exc
    return {"accepted": True}


@profil_vocal_router.put("")
def enregistrer_profil(capture: EnregistrementProfil) -> dict:
    try:
        get_verifier().remplacer_guide(
            [e.pcm() for e in capture.samples], capture.revision
        )
    except ProfilVocalInvalide as exc:
        raise traduire_erreur(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail={"reason": "saveFailed"}) from exc
    return etat_profil()


@profil_vocal_router.post("/check")
def essayer_profil(capture: CaptureProfil) -> dict:
    verdict = get_verifier().evaluer(capture.pcm())
    # Un essai n'enrôle rien et n'ouvre aucune commande, même reconnu.
    return {"result": verdict.etat}
