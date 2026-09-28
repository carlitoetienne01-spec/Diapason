"""§100 — chauffer et converser doivent conserver le même runner Ollama."""

import json

import httpx
import pytest

from diapason.core.types import Message, Role
from diapason.engine import ollama
from diapason.speech.realtime import local_voice


@pytest.mark.parametrize(
    "systeme,architecture,modele,attendu",
    [
        ("Darwin", "arm64", "qwen3.5:9b", {"num_batch": 128}),
        ("Darwin", "arm64", "gemma3:4b", {}),
        ("Darwin", "x86_64", "qwen3.5:9b", {}),
        ("Windows", "AMD64", "qwen3.5:9b", {}),
        ("Linux", "aarch64", "qwen3.5:9b", {}),
    ],
)
def test_le_reglage_ne_deborde_pas_du_moteur_mesure(
    monkeypatch, systeme, architecture, modele, attendu
):
    monkeypatch.setattr(ollama.platform, "system", lambda: systeme)
    monkeypatch.setattr(ollama.platform, "machine", lambda: architecture)
    assert ollama.runtime_batch_options(modele) == attendu, (
        "ne pas appliquer un banc Apple Silicon à un moteur non mesuré"
    )


@pytest.mark.asyncio
async def test_chauffe_chat_et_voix_conservent_les_options_du_runner(monkeypatch):
    """§100 — un seul oubli provoquait un rechargement au changement de vue."""
    monkeypatch.setattr(ollama.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ollama.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(ollama, "_default_num_ctx", lambda: 16384)
    requetes = []

    def repondre(request):
        payload = json.loads(request.content)
        requetes.append(payload)
        resultat = {"message": {"content": "Bonjour."}, "done": True}
        if payload["stream"]:
            return httpx.Response(200, text=json.dumps(resultat) + "\n")
        return httpx.Response(200, json=resultat)

    transport = httpx.MockTransport(repondre)
    moteur = ollama.OllamaEngine(host="http://testhost:11434")
    moteur._client.close()
    moteur._client = httpx.Client(base_url="http://testhost:11434", transport=transport)
    moteur._async_transport = transport
    client_reel = httpx.AsyncClient

    class ClientVocal(client_reel):
        def __init__(self, **kwargs):
            super().__init__(**{**kwargs, "transport": transport})

    monkeypatch.setattr(httpx, "AsyncClient", ClientVocal)
    monkeypatch.setattr(local_voice, "_ollama_base", lambda: "http://testhost:11434")
    messages = [Message(role=Role.USER, content="Bonjour")]
    try:
        assert moteur.prewarm("qwen3.5:9b")
        moteur.generate(messages, model="qwen3.5:9b")
        assert [x async for x in moteur.stream(messages, model="qwen3.5:9b")]
        assert [x async for x in moteur.stream_full(messages, model="qwen3.5:9b")]
        await local_voice._prewarm_prefix("qwen3.5:9b", "Contexte conservé", [])
        file = local_voice._default_llm("qwen3.5:9b", "Contexte conservé")([])
        assert await file.get() == "Bonjour."
        assert await file.get() is None
        await file.producer
        assert len(requetes) == 6, "les six chemins doivent vraiment être exercés"
        for requete in requetes:
            assert requete["options"]["num_batch"] == 128, requete["stream"]
            assert requete["options"]["num_ctx"] == 16384, (
                "réduire le lot ne réduit pas la fenêtre de contexte"
            )
    finally:
        await moteur._get_async_client().aclose()
        moteur.close()
