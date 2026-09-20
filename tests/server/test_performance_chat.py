"""§5/§100 : contexte réutilisable, serveur réactif et mesures sans fiction."""

import asyncio
import json
import threading

import httpx
import pytest
from fastapi import FastAPI

from diapason.core.config import DiapasonConfig
from diapason.core.types import Message, Role
from diapason.engine.ollama import OllamaEngine
from diapason.server import routes
from diapason.server.contexte_chat import inserer_au_tour_courant
from diapason.server.models import ChatMessage
from diapason.telemetry.chat_latency import (
    ChatLatency,
    measured_sse,
    record_ollama_metrics,
)


def trames(texte):
    return [
        json.loads(line[6:])
        for line in texte.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


class TestContexteDuTour:
    """§5 : l'heure fraîche ne rend pas périmé tout le préfixe calculé."""

    def test_seule_la_fin_change_avec_l_heure_et_la_memoire(self, monkeypatch):
        monkeypatch.setattr(
            "diapason.prompt.builder.SystemPromptBuilder.build", lambda _: "Identité"
        )
        historique = [
            Message(role=Role.USER, content="Avant"),
            Message(role=Role.ASSISTANT, content="Réponse antérieure"),
            Message(role=Role.USER, content="Maintenant ?"),
        ]
        prepares = []
        for repere in ("première", "deuxième"):
            monkeypatch.setattr(routes, "_now_anchor", lambda r=repere: r)
            enrichi = inserer_au_tour_courant(
                historique, [Message(role=Role.SYSTEM, content=f"Mémoire {repere}")]
            )
            prepares.append(
                routes._ensure_identity_prompt(
                    enrichi, DiapasonConfig(), client_supplied_system=False
                )
            )
        assert prepares[0][:3] == prepares[1][:3], "identité et passé restent stables"
        assert prepares[1][-3].content == "Mémoire deuxième", "la mémoire reste fraîche"
        assert prepares[1][-2].content.startswith("deuxième"), "l'heure reste fraîche"
        assert prepares[1][-1] is historique[-1], "la dernière demande est intacte"
        assert len(historique) == 3, (
            "aucun message injecté n'est stocké dans l'historique"
        )

    def test_ne_separe_pas_les_resultats_de_leurs_appels(self):
        messages = [
            Message(role=Role.SYSTEM, content="Instructions client"),
            Message(role=Role.USER, content="Mes tâches ?"),
            Message(role=Role.ASSISTANT, content="Appel"),
            Message(role=Role.TOOL, content="Résultat", name="succes_tasks"),
        ]
        frais = Message(role=Role.SYSTEM, content="Horloge")
        assert inserer_au_tour_courant(messages, [frais]) == [
            messages[0],
            frais,
            *messages[1:],
        ], "la séquence utilisateur/appel/résultat doit rester contiguë"
        assert inserer_au_tour_courant([], [frais]) == [frais]
        assert inserer_au_tour_courant(messages[:1], [frais]) == [messages[0], frais]

    def test_le_contexte_outille_conserve_les_arguments_et_les_identifiants(self):
        messages = [
            ChatMessage(role="user", content="Mes tâches ?"),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    {
                        "id": "appel-1",
                        "type": "function",
                        "function": {
                            "name": "succes_tasks",
                            "arguments": {"date": "2026-09-19"},
                        },
                    }
                ],
            ),
            ChatMessage(
                role="tool",
                name="succes_tasks",
                tool_call_id="appel-1",
                content="Données",
            ),
        ]
        enrichis = inserer_au_tour_courant(
            messages, [ChatMessage(role="system", content="Souvenir")]
        )
        converts = routes._to_messages(enrichis)
        appel = converts[-2].tool_calls[0]
        assert appel.id == converts[-1].tool_call_id == "appel-1"
        assert appel.name == "succes_tasks"
        assert json.loads(appel.arguments) == {"date": "2026-09-19"}
        assert enrichis[-2] is messages[-2], "l'injection ne reconstruit pas les appels"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(routes, "_chat_tooling", lambda *_: None)
    monkeypatch.setattr("diapason.desktop.etat_bureau.etat_du_bureau", lambda: None)
    monkeypatch.setattr(
        "diapason.prompt.builder.SystemPromptBuilder.build", lambda _: "Identité"
    )
    instance = FastAPI()
    instance.include_router(routes.router)
    config = DiapasonConfig()
    config.reflexion.enabled = False
    instance.state.config = config

    @instance.get("/sonde")
    async def sonde():
        return {"ok": True}

    return instance


class TestReactivite:
    """§5 : une recherche ou une sonde lente ne bloque pas les autres fenêtres."""

    @pytest.mark.asyncio
    async def test_annuler_une_fenetre_ne_recommence_pas_la_trousse_partagee(
        self, app, monkeypatch
    ):
        entre = threading.Event()
        liberer = threading.Event()
        constructions = []

        def construire(etat, config):
            constructions.append(1)
            entre.set()
            liberer.wait(2)
            etat._chat_tooling_cache = None
            return None

        monkeypatch.setattr(routes, "_chat_tooling", construire)
        premier = asyncio.create_task(routes._chat_tooling_async(app.state, None))
        assert await asyncio.to_thread(entre.wait, 2)
        second = asyncio.create_task(routes._chat_tooling_async(app.state, None))
        try:
            premier.cancel()
            with pytest.raises(asyncio.CancelledError):
                await premier
        finally:
            liberer.set()
        assert await second is None
        assert await routes._chat_tooling_async(app.state, None) is None
        assert len(constructions) == 1, "une annulation ne doit pas doubler les outils"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation", ["sante", "memoire", "prompt", "outils"])
    async def test_la_boucle_reste_libre(self, app, monkeypatch, operation):
        entre = threading.Event()
        liberer = threading.Event()
        capture = []

        def lent(*args, **kwargs):
            entre.set()
            # Filet de sécurité du test seulement : évite un fil orphelin
            # si la régression remet cet appel sur la boucle d'événements.
            liberer.wait(2)
            if operation == "memoire":
                return [Message(role=Role.SYSTEM, content="Souvenir"), *args[1]]
            if operation == "outils":
                return None
            if operation == "prompt":
                return "Identité"
            return True

        class Moteur:
            health = staticmethod(lent)

            async def stream(self, messages, **kwargs):
                capture.extend(messages)
                yield "Réponse"

        app.state.engine = Moteur()
        if operation == "memoire":
            app.state.memory_backend = object()
            monkeypatch.setattr("diapason.tools.storage.context.inject_context", lent)
        elif operation == "prompt":
            monkeypatch.setattr(
                "diapason.prompt.builder.SystemPromptBuilder.build", lent
            )
        elif operation == "outils":
            monkeypatch.setattr(routes, "_chat_tooling", lent)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            if operation == "sante":
                requete = asyncio.create_task(client.get("/health"))
            else:
                requete = asyncio.create_task(
                    client.post(
                        "/v1/chat/completions",
                        json={
                            "model": "test",
                            "stream": True,
                            "messages": [
                                {"role": "user", "content": "Avant"},
                                {"role": "assistant", "content": "Passé"},
                                {"role": "user", "content": "Bonjour"},
                            ],
                        },
                    )
                )
            try:
                assert await asyncio.to_thread(entre.wait, 2), "le travail a commencé"
                assert not requete.done(), "le travail doit attendre la libération"
                sonde = await asyncio.wait_for(client.get("/sonde"), timeout=1)
                assert sonde.json() == {"ok": True}, "le serveur continue de répondre"
            finally:
                liberer.set()
                reponse = await requete
            assert reponse.status_code == 200
            if operation == "memoire":
                assert [m.content for m in capture] == [
                    "Identité",
                    "Avant",
                    "Passé",
                    "Souvenir",
                    capture[-2].content,
                    "Bonjour",
                ], "le souvenir doit rester après le passé, sans masquer l'identité"


class TestMesures:
    """§100 : deux flux ne doivent jamais se prêter leurs temps ou compteurs."""

    @pytest.mark.asyncio
    async def test_ollama_alimente_le_flux_ordinaire_et_le_flux_outille(self, app):
        def serveur(request):
            requete = json.loads(request.content)
            model = requete["model"]
            return httpx.Response(
                200,
                text="\n".join(
                    json.dumps(c)
                    for c in [
                        {"message": {"content": model}},
                        {
                            "done": True,
                            "done_reason": "stop",
                            "eval_count": 2,
                            "prompt_eval_count": 10,
                            "load_duration": 1_000_000,
                            "prompt_eval_duration": 2_000_000,
                            "eval_duration": 3_000_000,
                            "total_duration": 6_000_000,
                        },
                    ]
                ),
            )

        moteur = OllamaEngine(host="http://local-test")
        moteur._async_transport = httpx.MockTransport(serveur)
        app.state.engine = moteur
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:

            async def demander(model, outils=False):
                requete = {
                    "model": model,
                    "stream": True,
                    "messages": [{"role": "user", "content": "Bonjour"}],
                }
                if outils:
                    requete["tools"] = [
                        {
                            "type": "function",
                            "function": {
                                "name": "horloge",
                                "parameters": {"type": "object"},
                            },
                        }
                    ]
                return await client.post("/v1/chat/completions", json=requete)

            try:
                reponses = await asyncio.gather(
                    demander("premier"), demander("second", True)
                )
            finally:
                moteur.close()
        ids = []
        for nom, reponse in zip(("premier", "second"), reponses):
            morceaux = trames(reponse.text)
            mesures = morceaux[-1]["telemetry"]["performance"]
            ids.append(mesures["requestId"])
            assert reponse.headers["X-Diapason-Request-Id"] == ids[-1]
            assert len(mesures["inferences"]) == 1, "une seule génération par réponse"
            native = mesures["inferences"][0]
            assert native["model"] == nom, "aucune contamination entre fenêtres"
            assert native["promptEvalMs"] == 2 and native["generationMs"] == 3
            assert native["toolSchemaCount"] == (1 if nom == "second" else 0)
            assert native["toolSchemaCharacters"] >= 2
            assert (
                mesures["firstModelTextMs"]
                <= mesures["firstTextMs"]
                <= mesures["totalMs"]
            )
            assert mesures["preparationMs"] >= mesures["promptMs"]
            assert reponse.text.count("data: [DONE]") == 1
            assert morceaux[1]["choices"][0]["delta"]["content"] == nom
        assert ids[0] != ids[1], "une identité propre par demande"

    @pytest.mark.asyncio
    async def test_ferme_le_moteur_sur_annulation_et_ne_conserve_aucun_contexte(self):
        ferme = asyncio.Event()
        mesure = ChatLatency()

        async def source():
            try:
                record_ollama_metrics({"eval_count": 4}, "local")
                yield 'data: {"choices":[{"delta":{"content":"Bonjour"}}]}\n\n'
                await asyncio.Event().wait()
            finally:
                ferme.set()

        flux = measured_sse(source(), mesure)
        await anext(flux)
        await flux.aclose()
        assert ferme.is_set(), "arrêter la lecture ferme aussi la génération"
        record_ollama_metrics({"eval_count": 99}, "hors-demande")
        assert len(mesure.inferences) == 1, "le contexte de mesure est libéré"

    @pytest.mark.asyncio
    async def test_annuler_la_tache_interrompt_la_lecture_en_attente(self):
        entre = asyncio.Event()
        ferme = asyncio.Event()

        async def source():
            try:
                entre.set()
                await asyncio.Event().wait()
                yield "inaccessible"
            finally:
                ferme.set()

        async def lire():
            async for _ in measured_sse(source(), ChatLatency()):
                pass

        tache = asyncio.create_task(lire())
        await entre.wait()
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache
        assert ferme.is_set(), "le lecteur et sa source doivent tous deux être fermés"

    @pytest.mark.asyncio
    async def test_conserve_toutes_les_passes_et_ne_devine_pas_les_durees(self):
        mesure = ChatLatency()

        async def source():
            record_ollama_metrics(
                {"eval_count": 4, "load_duration": float("nan")}, "local"
            )
            record_ollama_metrics({"eval_count": 6}, "local")
            yield 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
            yield "data: [DONE]\n\n"

        sortie = "".join([c async for c in measured_sse(source(), mesure)])
        donnees = trames(sortie)[0]
        assert donnees["choices"][0]["finish_reason"] == "length"
        mesures = donnees["telemetry"]["performance"]
        assert [m["completionTokens"] for m in mesures["inferences"]] == [4, 6]
        assert mesures["firstTextMs"] is None, "aucun texte n'a été diffusé"
        assert all("loadMs" not in m for m in mesures["inferences"]), "absence ≠ zéro"


class TestFermetureDuFluxComplet:
    """§100 : fermer une réponse SSE doit atteindre la connexion du moteur."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "chemin", ["court", "outils_auto", "outils_client", "long"]
    )
    @pytest.mark.parametrize("routage", [False, True])
    async def test_arreter_apres_le_premier_texte_ferme_ollama(
        self, chemin, routage, monkeypatch
    ):
        from diapason.core.events import EventBus
        from diapason.engine.multi import MultiEngine
        from diapason.security.guardrails import GuardrailsEngine
        from diapason.server.models import ChatCompletionRequest
        from diapason.telemetry.chat_latency import measure_response
        from diapason.telemetry.instrumented_engine import InstrumentedEngine

        monkeypatch.setattr(
            routes, "_ensure_identity_prompt", lambda messages, *a, **kw: messages
        )
        ferme = asyncio.Event()
        attend = asyncio.Event()
        texte = "\n".join(
            f"{i}. Une phrase claire pour apprendre tranquillement."
            for i in range(1, 16)
        )

        class Reponse(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield (json.dumps({"message": {"content": texte}}) + "\n").encode()
                attend.set()
                await asyncio.Event().wait()

            async def aclose(self):
                ferme.set()

        moteur = OllamaEngine(host="http://local-test")
        moteur._async_transport = httpx.MockTransport(
            lambda _: httpx.Response(200, stream=Reponse())
        )
        # Les deux enveloppes réelles, pas un générateur qui ferme uniquement
        # sa propre doublure. Chaque étage doit transmettre aclose.
        enveloppe = InstrumentedEngine(GuardrailsEngine(moteur), EventBus())
        if routage:
            monkeypatch.setattr(moteur, "list_models", lambda: ["local"])
            enveloppe = MultiEngine([("ollama", enveloppe)])
        question = "Donne-moi 50 exemples" if chemin == "long" else "Bonjour"
        req = ChatCompletionRequest(
            model="local",
            messages=[ChatMessage(role="user", content=question)],
            stream=True,
        )
        try:
            if chemin == "outils_client":
                req.tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "lecture",
                            "parameters": {"type": "object"},
                        },
                    }
                ]
                reponse = await routes._handle_stream_tools(enveloppe, "local", req)
            else:
                if chemin == "outils_auto":
                    req.messages[-1].content = "Explique les saisons."
                reponse = await routes._handle_stream(
                    enveloppe,
                    "local",
                    req,
                    tooling=([], None) if chemin == "outils_auto" else None,
                )
            reponse = measure_response(reponse, ChatLatency())
            async with asyncio.timeout(2):
                async for frame in reponse.body_iterator:
                    if any(
                        c.get("delta", {}).get("content")
                        for p in trames(frame)
                        for c in p.get("choices", [])
                    ):
                        break
            assert not attend.is_set(), (
                "le premier texte arrive avant la fin du fournisseur"
            )
            await reponse.body_iterator.aclose()
            assert ferme.is_set(), (
                "la socket Ollama doit être fermée sans attendre le ramasse-miettes"
            )
        finally:
            moteur.close()
