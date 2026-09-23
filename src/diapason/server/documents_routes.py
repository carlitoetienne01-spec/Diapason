"""La route qui lit un document joint à un message du chat.

22 septembre 2026. L'extraction se fait ICI, une seule fois, quand l'usager
joint le fichier — et non à chaque tour de la conversation : relire un PDF
de cent pages à chaque question coûterait une seconde par tour pour un
résultat identique.

Elle rend aussi ce qu'elle a lu : le nombre de pages, de caractères, et si
le texte a été coupé. L'usager doit voir CE QUE le modèle verra, avant de
poser sa question — sans quoi il lui demande de conclure sur un document
dont la moitié n'a jamais été montrée (§5).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from diapason.server.documents_joints import (
    DocumentRefuse,
    lire,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/chat", tags=["documents"])


class DemandeDocument(BaseModel):
    nom: str
    # Base64, avec ou sans l'en-tête « data: » que rend FileReader. JSON et
    # jamais multipart : la fenêtre Tauri est une WKWebView, qui échoue sur
    # un corps binaire avec un « Load failed » opaque (CLAUDE.md).
    contenu: str


@router.post("/documents")
async def lire_document(demande: DemandeDocument) -> dict[str, Any]:
    """Extrait le texte d'un document joint, et dit ce qu'il en a retenu."""
    try:
        # pdfplumber est bloquant et un gros PDF prend une seconde : dans une
        # route async, cela figerait la boucle d'événements — donc le
        # WebSocket vocal, le flux du chat et la cloche d'approbation avec
        # elle (piège déjà payé, CLAUDE.md).
        document = await asyncio.to_thread(lire, demande.nom, demande.contenu)
    except DocumentRefuse as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Clés anglaises sur le fil, comme tout ce qui voyage (CLAUDE.md) : un
    # champ en snake_case se lit « undefined » côté TypeScript, en silence.
    return {
        "nom": document.nom,
        "texte": document.texte,
        "pages": document.pages,
        "characters": document.caracteres,
        "sourceCharacters": document.caracteres_source,
        "truncated": document.tronque,
    }


__all__ = ["router"]
