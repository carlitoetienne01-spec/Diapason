"""§100 : la voix attend le calcul lancé, dépasse le fond en attente et s'annule."""

import asyncio
import json

import httpx
import pytest

from diapason.engine.scheduling import InferenceScheduler, background_work
from diapason.speech.realtime import local_voice


@pytest.mark.asyncio
async def test_la_voix_passe_avant_le_fond_et_son_annulation_libere_le_creneau(
    monkeypatch,
):
    ordonnanceur = InferenceScheduler(quiet_seconds=0)
    monkeypatch.setattr(
        "diapason.engine.scheduling.scheduler_for", lambda _: ordonnanceur
    )
    actif, liberer = asyncio.Event(), asyncio.Event()
    suite = asyncio.Event()
    ordre = []

    async def fond(premier):
        with background_work():
            async with ordonnanceur.async_slot("modele"):
                ordre.append("déjà lancé" if premier else "fond en attente")
                if premier:
                    actif.set()
                    await liberer.wait()
                else:
                    suite.set()

    class Client:
        status_code = 200

        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def stream(self, *_args, **_kwargs):
            ordre.append("voix")
            return self

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "Bonjour."}})
            await asyncio.Event().wait()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    premier = asyncio.create_task(fond(True))
    await asyncio.wait_for(actif.wait(), 1)
    suivant = asyncio.create_task(fond(False))
    file = local_voice._default_llm("modele", "Contexte oral")([])
    try:
        async with asyncio.timeout(1):
            while not ordonnanceur._waiting:
                await asyncio.sleep(0)
        assert ordre == ["déjà lancé"], "ne pas prétendre préempter le calcul en cours"
        liberer.set()
        assert await asyncio.wait_for(file.get(), 1) == "Bonjour."
        assert ordre == ["déjà lancé", "voix"], "la voix dépasse le fond en attente"
        file.abort()
        await asyncio.wait_for(suite.wait(), 1)
        assert ordre[-1] == "fond en attente", "l'annulation rend le créneau"
    finally:
        liberer.set()
        file.abort()
        await asyncio.gather(premier, suivant, file.producer, return_exceptions=True)
