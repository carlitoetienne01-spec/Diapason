"""Le mode Étudier partage l'authentification du chat, jamais la sous-app LAN."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import ValidationError

from diapason.core.paths import get_config_dir
from diapason.etudes.magasin import ConflitEtude, MagasinEtudes, vue_publique
from diapason.etudes.modeles import ActionEtude, DemandeEtude, MaterielEtude

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/study", tags=["study"])


def magasin(request: Request) -> MagasinEtudes:
    return magasin_application(request.app)


def magasin_application(app: FastAPI) -> MagasinEtudes:
    existant = getattr(app.state, "etudes_store", None)
    return (
        existant
        if existant is not None
        else MagasinEtudes(get_config_dir() / "etudes.db")
    )


def supprimer_etudes_conversation(app: FastAPI, conversation: str) -> None:
    magasin_application(app).supprimer_conversation(conversation)


Depot = Annotated[MagasinEtudes, Depends(magasin)]


def _erreur(exc: Exception, *, preparation: bool = False) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, "Cette épreuve n'existe plus.")
    if isinstance(exc, ConflitEtude):
        return HTTPException(409, str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(
            422,
            "Le modèle a produit une préparation ou une correction invalide. "
            "Aucune note n'a été enregistrée.",
        )
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    if isinstance(exc, TimeoutError):
        return HTTPException(
            504,
            "La préparation a dépassé le délai prévu. Aucun nouveau cours "
            "n'a été enregistré."
            if preparation
            else "La correction n'a pas abouti dans le délai prévu. Tes réponses "
            "enregistrées sont conservées.",
        )
    logger.warning("Le parcours Étudier a échoué : %s", type(exc).__name__)
    return HTTPException(
        503,
        "Le modèle local n'est pas disponible pour préparer ce cours."
        if preparation
        else "Le modèle local n'est pas disponible. Tes réponses enregistrées "
        "sont conservées.",
    )


def service_application(app: FastAPI):
    from diapason.etudes.service import ServiceEtudes

    if not hasattr(app.state, "etudes_service"):
        app.state.etudes_service = ServiceEtudes(
            magasin_application(app), app.state.engine
        )
    # Le moteur peut être rechargé ; les tests changent aussi leur faux moteur.
    app.state.etudes_service.moteur = app.state.engine
    return app.state.etudes_service


def verrou(request: Request) -> asyncio.Lock:
    return service_application(request.app).verrou


@router.get("/sessions")
def lister(depot: Depot, conversationId: str = Query(min_length=1, max_length=160)):
    return {"sessions": depot.lister(conversationId)}


@router.get("/materials")
def lire_materiel(
    depot: Depot, conversationId: str = Query(min_length=1, max_length=160)
):
    return {"sources": depot.lire_sources(conversationId)}


@router.put("/materials")
def garder_materiel(materiel: MaterielEtude, depot: Depot):
    try:
        depot.garder_sources(
            materiel.conversation,
            [s.model_dump(by_alias=True) for s in materiel.sources],
        )
        return {"saved": True}
    except Exception as exc:
        raise _erreur(exc) from exc


@router.get("/sessions/{session_id}")
def lire(session_id: str, depot: Depot):
    try:
        return vue_publique(depot.lire(session_id))
    except KeyError as exc:
        raise _erreur(exc) from exc


@router.delete("/sessions/{session_id}")
def supprimer(session_id: str, depot: Depot):
    depot.supprimer(session_id)
    return {"deleted": True}


@router.post("/sessions")
async def creer(demande: DemandeEtude, request: Request, depot: Depot):
    try:
        return await service_application(request.app).creer(demande)
    except Exception as exc:
        raise _erreur(exc, preparation=True) from exc


@router.post("/sessions/{session_id}/actions")
async def agir(session_id: str, action: ActionEtude, request: Request, depot: Depot):
    try:
        return await service_application(request.app).agir(session_id, action)
    except Exception as exc:
        raise _erreur(exc) from exc
