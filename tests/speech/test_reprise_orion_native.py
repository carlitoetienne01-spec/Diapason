"""§100 — le vrai modèle reprend son préfixe, sans rejouer ni inventer un outil."""

import asyncio
import os

import pytest

from diapason.engine.scheduling import interactive_turn
from diapason.speech.realtime.local_voice import _default_llm, ollama_reachable


@pytest.mark.live
@pytest.mark.asyncio
async def test_la_reprise_native_conserve_les_mots_et_les_appels(monkeypatch):
    if os.environ.get("DIAPASON_TEST_REPRISE_NATIVE") != "1":
        pytest.skip("Banc Ollama natif activé explicitement")
    if not await asyncio.to_thread(ollama_reachable):
        pytest.skip("Ollama local absent")

    import httpx

    class ClientDetermine(httpx.AsyncClient):
        def stream(self, *args, json, **kwargs):
            # Même décodage déterministe des deux côtés : comparer deux
            # tirages aléatoires confond la reprise avec la formulation.
            # Ce réglage ne change que le banc, jamais le produit.
            json["options"].update(temperature=0, seed=42)
            return super().stream(*args, json=json, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", ClientDetermine)

    async def recevoir(messages, *, pause, outils=None):
        file = _default_llm(
            "qwen3.5:9b",
            "Respecte exactement la demande et son contexte. "
            "Pour une récitation, ne change aucun mot, sans préambule.",
            outils,
            pause_phrases=pause,
        )(messages)
        texte, appels = [], []
        try:
            async with asyncio.timeout(60):
                while (item := await file.get()) is not None:
                    if isinstance(item, tuple):
                        appels.extend(item[1])
                    else:
                        assert not item.startswith("\x00ERROR\x00"), item
                        texte.append(item)
                    file.reprendre()
        finally:
            file.abort()
            await asyncio.gather(file.producer, return_exceptions=True)
        return "".join(texte).strip(), appels

    with interactive_turn():
        for attendu in (
            "Le ciel est bleu. Le soleil brille. La nuit arrive.",
            "Le coffre reste fermé. Les trois éléments sont : bleu, vert et or. "
            "Nous avons terminé.",
            "Bonjour.",
        ):
            messages = [
                {
                    "role": "user",
                    "content": f"Récite exactement ce texte : « {attendu} »",
                }
            ]
            normal, outils_normal = await recevoir(messages, pause=False)
            repris, outils_repris = await recevoir(messages, pause=True)
            assert normal == repris, (normal, repris)
            assert normal.strip("«» ") == attendu, (normal, attendu)
            assert not outils_normal and not outils_repris

        messages = [
            {
                "role": "user",
                "content": "Je débute en anglais. J'ai dix minutes par jour.",
            },
            {
                "role": "assistant",
                "content": "Écoute un dialogue simple, puis répète une phrase.",
            },
            {
                "role": "user",
                "content": "Donne-moi un exemple concret de phrase à répéter, "
                "avec sa traduction. Réponds en trois phrases au maximum.",
            },
        ]
        normal, _ = await recevoir(messages, pause=False)
        repris, _ = await recevoir(messages, pause=True)
        # Un nouveau préremplissage peut reformuler la suite libre même
        # avec le même décodage déterministe. Le contrat est le contenu
        # demandé et son contexte, pas l'identité d'une réponse non générée.
        for reponse in (normal, repris):
            assert reponse.count("I have ten minutes a day to learn English.") == 1
            assert (
                reponse.count("J'ai dix minutes par jour pour apprendre l'anglais") == 1
            )

        # L'outil est seulement demandé : ce banc ne l'exécute jamais.
        outil = {
            "type": "function",
            "function": {
                "name": "current_time",
                "description": "Lire l'heure exacte de l'ordinateur.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        _, appels = await recevoir(
            [{"role": "user", "content": "Vérifie l'heure exacte avec current_time."}],
            pause=True,
            outils=[outil],
        )
        assert [a["function"]["name"] for a in appels] == ["current_time"], (
            "l'appel structuré doit rester exploitable, sans duplication"
        )
