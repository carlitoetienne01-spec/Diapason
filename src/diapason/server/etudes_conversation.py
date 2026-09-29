"""Raccord minimal du parcours pédagogique aux transports existants."""

import asyncio

from fastapi import Request

from diapason.etudes.conversation import (
    ContexteEtudes,
    documents_du_chat,
    utiliser_contexte,
)
from diapason.server.etudes_routes import service_application
from diapason.server.models import ChatCompletionRequest


def contexte_application(
    app, conversation, modele, *, messages=(), sources=None, demande=""
):
    if not isinstance(conversation, str) or not 1 <= len(conversation) <= 160:
        return None
    return ContexteEtudes(
        service_application(app),
        conversation,
        modele,
        asyncio.get_running_loop(),
        sources=sources if isinstance(sources, list) else documents_du_chat(messages),
        demande=demande,
    )


async def contexte_etudes_chat(request: Request, request_body: ChatCompletionRequest):
    demande = next(
        (m.content for m in reversed(request_body.messages) if m.role == "user"), ""
    )
    contexte = contexte_application(
        request.app,
        request_body.conversationId,
        request_body.model,
        messages=request_body.messages,
        demande=demande,
    )
    if contexte:
        dernier = next(
            (m for m in reversed(request_body.messages) if m.role == "user"), None
        )
        fraiches = documents_du_chat([dernier]) if dernier else []
        materiel = await asyncio.to_thread(
            contexte.service.depot.lire_sources, contexte.conversation
        )
        contexte.sources = fraiches or materiel or contexte.sources
    if contexte and contexte.sources and (fraiches or not materiel):
        try:
            await asyncio.to_thread(
                contexte.service.depot.garder_sources,
                contexte.conversation,
                contexte.sources,
            )
        except ValueError:
            # Le chat peut discuter d'un document partiel ; seul préparer une
            # épreuve complète est refusé, avec sa raison par l'outil study.
            pass
    with utiliser_contexte(contexte):
        yield
