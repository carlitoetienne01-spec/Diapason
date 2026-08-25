"""La route par laquelle l'interface dit ce qu'elle affiche.

Spatial Mesh, handoff — 25 août 2026. Voir ``desktop/contexte_app`` pour le
pourquoi. Une seule route, volontairement minuscule : le cliché est
volatile, il ne mérite ni base ni historique.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/context", tags=["context"])


class VueCourante(BaseModel):
    """Ce que l'interface affiche à l'instant."""

    path: str = Field(default="/", max_length=200)
    resourceType: str = Field(default="", max_length=40)
    resourceId: str = Field(default="", max_length=120)
    resourceTitle: str = Field(default="", max_length=200)


@router.post("/view")
def poser_la_vue(body: VueCourante) -> dict[str, Any]:
    """Enregistrer l'écran courant. Idempotent, sans effet de bord durable."""
    from diapason.desktop.contexte_app import decrire, poser_contexte

    contexte = poser_contexte(
        body.path,
        ressource_type=body.resourceType,
        ressource_id=body.resourceId,
        ressource_titre=body.resourceTitle,
    )
    if contexte is None:
        # Écran hors liste blanche : on le dit, on ne fait pas semblant.
        return {"tracked": False, "reason": "UNKNOWN_SCREEN"}
    return {"tracked": True, "described": decrire(contexte)}


@router.delete("/view")
def oublier_la_vue() -> dict[str, Any]:
    """L'onglet se ferme : ce qu'il affichait n'est plus vrai."""
    from diapason.desktop.contexte_app import oublier

    oublier()
    return {"tracked": False}


@router.get("/view")
def lire_la_vue() -> dict[str, Any]:
    from diapason.desktop.contexte_app import decrire, dernier_contexte

    contexte: Optional[Any] = dernier_contexte()
    if contexte is None:
        return {"tracked": False}
    return {
        "tracked": True,
        "path": contexte.chemin,
        "screen": contexte.ecran,
        "resourceType": contexte.ressource_type,
        "resourceId": contexte.ressource_id,
        "resourceTitle": contexte.ressource_titre,
        "described": decrire(contexte),
    }


__all__ = ["router"]
