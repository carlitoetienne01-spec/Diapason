"""§100 : READY attend le vrai contexte, et fermer abandonne sa préparation."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

import httpx
import pytest

from diapason.speech.realtime import local_voice as v


@pytest.fixture
def transport(monkeypatch):
    requetes = []

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def post(self, url, json):
            requetes.append(deepcopy(json))
            return httpx.Response(200, request=httpx.Request("POST", url))

    class Ordonnanceur:
        @asynccontextmanager
        async def async_slot(self, *_args, **_kwargs):
            yield

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        "diapason.engine.scheduling.scheduler_for", lambda _: Ordonnanceur()
    )
    return requetes


@pytest.mark.asyncio
async def test_la_chauffe_utilise_la_fenetre_de_la_conversation(monkeypatch, transport):
    monkeypatch.setattr(v, "_num_ctx", lambda: 8192)
    outils = [{"type": "function", "function": {"name": "current_time"}}]
    await v._prewarm_prefix("modele-local", "Contexte oral", outils)
    assert len(transport) == 1, "la chauffe doit atteindre le moteur"
    assert transport[0]["options"]["num_ctx"] == 8192, (
        "ne pas charger un autre contexte"
    )
    assert transport[0]["tools"] == outils, "le préfixe garde la même trousse"


@pytest.mark.asyncio
async def test_la_chauffe_prepare_aussi_les_messages_importes_du_chat(transport):
    """§100 : READY doit préparer les messages que le premier tour relira."""
    historique = [
        {"role": "user", "content": "Je travaille mon anglais."},
        {"role": "assistant", "content": "Nous pouvons pratiquer ensemble."},
    ]
    await v._prewarm_prefix("modele-local", "Contexte oral", [], historique)
    assert transport[0]["messages"][1:] == historique, (
        "le premier échange ne doit pas payer la lecture du chat après READY"
    )
    assert transport[0]["options"]["num_predict"] == 1, (
        "la chauffe prépare le contexte, sans fabriquer une réponse complète"
    )


@pytest.mark.asyncio
async def test_la_session_transmet_son_contexte_initial_a_la_chauffe(monkeypatch):
    """§5 : le paramètre historique doit être exercé dans le vrai démarrage."""
    recus = []

    async def chauffer(_modele, _systeme, _outils, historique):
        recus.extend(historique)

    monkeypatch.setattr(v, "_prewarm_prefix", chauffer)
    monkeypatch.setattr(v, "ollama_reachable", lambda: True)
    historique = [{"role": "user", "content": "Je débute en anglais."}]
    session = v.LocalVoiceSession(
        stt=lambda _: "", tts=lambda _: b"", enable_tools=False, historique=historique
    )
    try:
        await session.connect()
        assert recus == historique, "la préparation doit contenir le contexte reçu"
        assert (await session._queue.get()).kind == "ready"
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("annuler", [False, True])
async def test_la_preparation_ne_promet_pas_ready_avant_la_fin(monkeypatch, annuler):
    commence, liberer, fini = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def chauffer(*_):
        commence.set()
        try:
            await liberer.wait()
        finally:
            fini.set()

    monkeypatch.setattr(v, "_prewarm_prefix", chauffer)
    monkeypatch.setattr(v, "ollama_reachable", lambda: True)
    s = v.LocalVoiceSession(stt=lambda _: "", tts=lambda _: b"", enable_tools=False)
    connexion = asyncio.create_task(s.connect())
    await asyncio.wait_for(commence.wait(), 1)
    assert s._queue.empty(), "la préparation en cours ne dit pas déjà prête"
    if annuler:
        await s.close()

        await asyncio.gather(connexion, return_exceptions=True)
        assert fini.is_set(), "la fermeture abandonne la préparation"
        evenements = []
        while not s._queue.empty():
            evenement = s._queue.get_nowait()
            if evenement is not None:
                evenements.append(evenement.kind)
        assert "ready" not in evenements, "ne pas armer un micro après fermeture"
    else:
        liberer.set()
        await asyncio.wait_for(connexion, 1)
        assert (await s._queue.get()).kind == "ready"
        await s.close()


@pytest.mark.asyncio
async def test_un_echec_de_preparation_ne_devient_pas_un_succes_au_second_essai(
    monkeypatch,
):
    tentatives = []

    async def chauffer(*_):
        tentatives.append(True)
        raise RuntimeError("Moteur encore indisponible")

    monkeypatch.setattr(v, "_prewarm_prefix", chauffer)
    monkeypatch.setattr(v, "ollama_reachable", lambda: True)
    s = v.LocalVoiceSession(stt=lambda _: "", tts=lambda _: b"", enable_tools=False)
    for _ in range(2):
        await s.connect()
        assert (await s._queue.get()).kind == "error", "aucun faux READY"
        assert s._llm is None, "le contexte non préparé reste à préparer"
    assert len(tentatives) == 2, "la seconde tentative doit vraiment refaire la chauffe"
    await s.close()
