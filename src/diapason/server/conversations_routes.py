"""Routes HTTP de la persistance des conversations du chat.

Montées sur l'app localhost principale, JAMAIS sur la sous-app ``lan`` :
ce sont des transcriptions privées, et le réseau local n'a rien à y lire.
L'authentification par clé s'applique comme à toute route ``/v1``.

Les routes sont des ``def`` SYNCHRONES, pas ``async`` : SQLite bloque, et
ce qu'une route ``async`` fait en ligne s'exécute sur la boucle
d'événements — un accès disque y figerait le WebSocket vocal et le flux du
chat (piège documenté du dépôt). Starlette exécute les ``def`` dans un fil.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

from diapason.server.conversations_store import ConversationsStore


def _valider_conversation(conversation_id: str, body: Any) -> Dict[str, Any]:
    """Valide le corps d'un PUT et rend la conversation prête à stocker.

    Les types sont vérifiés à la main plutôt que par un modèle Pydantic à
    alias : la sortie est construite en camelCase à la main comme partout
    (voir gestes_routes.py), et l'entrée suit. ``bool`` est un ``int`` en
    Python — un ``updatedAt: true`` passerait un simple ``isinstance`` et
    entrerait dans la base comme ``1`` ms, d'où l'exclusion explicite.
    """
    if not isinstance(body, dict):
        raise HTTPException(422, "Le corps doit être un objet Conversation")

    def _entier(champ: str) -> int:
        valeur = body.get(champ)
        if not isinstance(valeur, int) or isinstance(valeur, bool):
            raise HTTPException(422, f"'{champ}' doit être un entier (ms epoch)")
        return valeur

    def _texte(champ: str) -> str:
        valeur = body.get(champ)
        if not isinstance(valeur, str):
            raise HTTPException(422, f"'{champ}' doit être une chaîne")
        return valeur

    # L'id de l'URL PRIME : un corps qui en porte un autre est refusé en 400
    # plutôt qu'écrasé en silence — deux ids qui divergent signalent un bug
    # client (une copie collée sous le mauvais chemin), et l'écraser aurait
    # fait stocker un contenu sous un id que le client ne relira jamais.
    body_id = body.get("id")
    if body_id is not None and body_id != conversation_id:
        raise HTTPException(
            400,
            f"L'id du corps ({body_id!r}) diverge de celui de l'URL "
            f"({conversation_id!r})",
        )

    pinned = body.get("pinned", False)
    if not isinstance(pinned, bool):
        raise HTTPException(422, "'pinned' doit être un booléen")
    messages = body.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(422, "'messages' doit être une liste")

    return {
        "id": conversation_id,
        "title": _texte("title"),
        "createdAt": _entier("createdAt"),
        "updatedAt": _entier("updatedAt"),
        "model": _texte("model"),
        "pinned": pinned,
        # Opaques pour le serveur : stockés et rendus tels quels.
        "messages": messages,
    }


def create_conversations_router(store: ConversationsStore) -> APIRouter:
    router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

    @router.get("")
    def list_conversations(since: Optional[int] = None) -> Dict[str, Any]:
        # ``since`` est un numéro d'écriture (le ``seq`` d'une réponse
        # précédente), PAS une heure : voir conversations_store.py.
        vivantes, tombales, seq = store.list(since)
        return {"conversations": vivantes, "deleted": tombales, "seq": seq}

    @router.put("/{conversation_id}")
    def put_conversation(
        conversation_id: str,
        body: Any = Body(...),
    ) -> Dict[str, Any]:
        conv = _valider_conversation(conversation_id, body)
        return store.upsert(conv)

    @router.delete("/{conversation_id}")
    def delete_conversation(conversation_id: str) -> Dict[str, Any]:
        deleted_at = store.delete(conversation_id)
        return {"deleted": True, "deletedAt": deleted_at}

    return router
