"""§5/§100 : la mémoire cède sa place sans prétendre annuler un calcul lancé."""

import asyncio
import json
import threading
import time
from contextlib import aclosing

import httpx
import pytest

from diapason.engine.ollama import OllamaEngine
from diapason.engine.scheduling import (
    BackgroundStopped,
    InferenceQueueTimeout,
    InferenceScheduler,
    background_work,
    interactive_turn,
    scheduler_for,
)
from diapason.memory.extractor import FactExtractor
from diapason.telemetry.chat_latency import ChatLatency, measured_sse


async def attendre(predicat):
    async with asyncio.timeout(2):
        while not predicat():
            await asyncio.sleep(0.001)


class TestPriorite:
    """§5 : une file Python ne peut pas interrompre une inférence déjà partie."""

    @pytest.mark.asyncio
    async def test_la_question_depasse_la_memoire_en_attente(self):
        scheduler = InferenceScheduler(quiet_seconds=0)
        ordre = []
        actif = asyncio.Event()
        liberer = asyncio.Event()

        async def memoire(nom):
            with background_work():
                async with scheduler.async_slot("m"):
                    ordre.append(nom)
                    if nom == "déjà lancée":
                        actif.set()
                        await liberer.wait()

        async def question():
            async with scheduler.async_slot("m"):
                ordre.append("question")

        premiere = asyncio.create_task(memoire("déjà lancée"))
        await actif.wait()
        seconde = asyncio.create_task(memoire("en attente"))
        await attendre(lambda: len(scheduler._pending) == 1)
        prioritaire = asyncio.create_task(question())
        await attendre(lambda: scheduler._waiting == 1)
        assert ordre == ["déjà lancée"], "une inférence lancée reste non préemptive"
        liberer.set()
        await asyncio.gather(premiere, seconde, prioritaire)
        assert ordre == ["déjà lancée", "question", "en attente"]

    @pytest.mark.asyncio
    async def test_un_annule_ne_prend_jamais_le_creneau_plus_tard(self):
        scheduler = InferenceScheduler(quiet_seconds=0)
        entrees = []

        async def question():
            async with scheduler.async_slot("m"):
                entrees.append("question")

        with background_work():
            async with scheduler.async_slot("m"):
                # Create with a clean task context: this is a foreground caller.
                import contextvars

                demande = asyncio.create_task(question(), context=contextvars.Context())
                await attendre(lambda: scheduler._waiting == 1)
                demande.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await demande
        async with scheduler.async_slot("m"):
            entrees.append("suivant")
        assert entrees == ["suivant"], "aucun fil orphelin ne réclame le moteur"
        assert scheduler._waiting == scheduler._foreground == 0

    @pytest.mark.asyncio
    async def test_les_deux_fenetres_gardent_le_parallelisme_interactif(self):
        scheduler = InferenceScheduler(quiet_seconds=0)
        async with scheduler.async_slot("m"):
            async with scheduler.async_slot("m", timeout=0.1):
                assert scheduler._foreground == 2, "Ollama conserve son parallélisme"

    @pytest.mark.asyncio
    async def test_le_tour_protege_aussi_le_temps_passe_dans_un_outil(self):
        scheduler = InferenceScheduler(quiet_seconds=0)
        lectures = []

        async def memoire():
            with background_work():
                async with scheduler.async_slot("m"):
                    lectures.append("mémoire")

        with interactive_turn():
            async with scheduler.async_slot("m"):
                pass
            extraction = asyncio.create_task(memoire())
            await attendre(lambda: len(scheduler._pending) == 1)
            await asyncio.sleep(0.025)
            assert not lectures, "l'outil ne doit pas laisser passer la mémoire"
        await extraction
        assert lectures == ["mémoire"], "la mémoire différée finit par s'exécuter"

    @pytest.mark.asyncio
    async def test_le_calme_est_reserve_a_la_memoire_pas_aux_questions(self):
        scheduler = InferenceScheduler(quiet_seconds=0.07)
        async with scheduler.async_slot("m"):
            pass
        debut = time.monotonic()
        async with scheduler.async_slot("m") as lease:
            assert lease.wait_ms < 50, "la question n'attend pas le délai de calme"
        with background_work():
            async with scheduler.async_slot("m"):
                assert time.monotonic() - debut >= 0.07

    @pytest.mark.asyncio
    async def test_le_delai_local_ne_ment_pas_sur_la_connexion(self):
        scheduler = InferenceScheduler(quiet_seconds=0)
        with background_work():
            async with scheduler.async_slot("m"):
                import contextvars

                async def question():
                    async with scheduler.async_slot("m", timeout=0.02):
                        pytest.fail("la mémoire est encore en cours")

                demande = asyncio.create_task(question(), context=contextvars.Context())
                with pytest.raises(InferenceQueueTimeout, match="occupé"):
                    await demande
        assert scheduler._waiting == 0

    def test_un_arret_du_service_retire_la_memoire_sans_inference(self):
        scheduler = InferenceScheduler(quiet_seconds=0)
        stop = threading.Event()
        sorties = []

        def memoire():
            with background_work(stop=stop):
                try:
                    with scheduler.slot("m"):
                        sorties.append("interdit")
                except BackgroundStopped:
                    sorties.append("arrêt")

        with interactive_turn():
            thread = threading.Thread(target=memoire)
            thread.start()
            stop.set()
            thread.join(1)
            assert not thread.is_alive(), "l'arrêt ne laisse pas de fil en attente"
        assert sorties == ["arrêt"]
        assert not scheduler._pending

    def test_plusieurs_clients_du_meme_serveur_partagent_la_priorite(self):
        a = scheduler_for("http://localhost:11434/")
        assert a is scheduler_for("http://127.0.0.1:11434")
        assert a is scheduler_for("http://[::1]:11434")
        assert a is not scheduler_for("http://localhost:11435")


class TestRaccordMoteur:
    """§100 : les vrais chemins HTTP respectent l'attente et libèrent leur place."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fin", ["fermeture", "erreur"])
    async def test_fin_du_sse_debloque_la_memoire(self, fin):
        scheduler = InferenceScheduler(quiet_seconds=0)
        entrees = []

        async def source():
            yield 'data: {"choices":[]}\n\n'
            if fin == "erreur":
                raise RuntimeError("flux interrompu")
            await asyncio.Event().wait()

        async def memoire():
            with background_work():
                async with scheduler.async_slot("m"):
                    entrees.append("mémoire")

        flux = measured_sse(source(), ChatLatency())
        await anext(flux)
        extraction = asyncio.create_task(memoire())
        await attendre(lambda: len(scheduler._pending) == 1)
        assert not entrees
        if fin == "erreur":
            with pytest.raises(RuntimeError, match="interrompu"):
                await anext(flux)
        else:
            await flux.aclose()
        await extraction
        assert entrees == ["mémoire"], "aucun tour fantôme ne bloque les suivants"

    def test_le_prechargement_explicite_garde_le_modele_demande(self):
        moteur = OllamaEngine(host="http://prewarm.test")
        moteur._scheduler = InferenceScheduler(quiet_seconds=0)
        moteur._scheduler.remember_model("ancien")
        demandes = []

        def repondre(request):
            demandes.append(json.loads(request.content))
            return httpx.Response(200, json={"done": True})

        moteur._client.close()
        moteur._client = httpx.Client(
            base_url=moteur._host, transport=httpx.MockTransport(repondre)
        )
        try:
            assert moteur.prewarm("choisi")
            assert demandes[0]["model"] == "choisi", (
                "ne pas annoncer un autre modèle prêt"
            )
            assert demandes[0]["prompt"] == ""
            assert not moteur._scheduler._background_active
        finally:
            moteur.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["stream", "stream_full"])
    async def test_le_flux_libere_le_moteur_et_la_memoire_suit_son_modele(self, method):
        moteur = OllamaEngine(host="http://lot4.test:11434")
        moteur._scheduler = InferenceScheduler(quiet_seconds=0)
        requetes = []

        def repondre(request):
            contenu = json.loads(request.content)
            requetes.append(contenu["model"])
            if contenu["stream"]:
                return httpx.Response(
                    200,
                    content=json.dumps({"message": {"content": "Bonjour"}}) + "\n",
                )
            return httpx.Response(
                200, json={"message": {"content": '["Préfère le thé"]'}}
            )

        moteur._async_transport = httpx.MockTransport(repondre)
        moteur._client.close()
        moteur._client = httpx.Client(
            base_url=moteur._host, transport=httpx.MockTransport(repondre)
        )
        try:
            async with aclosing(getattr(moteur, method)([], model="récent")) as source:
                await anext(source)
                assert moteur._scheduler._foreground == 1
            assert moteur._scheduler._foreground == 0, (
                "fermer le flux libère le créneau"
            )
            extractor = FactExtractor(moteur, "ancien", use_active_model=True)
            facts = await asyncio.to_thread(extractor.extract, "J'aime le thé")
            assert facts == ["Préfère le thé"], "le souvenir continue d'être extrait"
            assert requetes == ["récent", "récent"], (
                "pas de retour au modèle du démarrage"
            )
            explicite = FactExtractor(moteur, "choisi", use_active_model=False)
            await asyncio.to_thread(explicite.extract, "Je confirme")
            assert requetes[-1] == "choisi", "un modèle explicite est respecté"
        finally:
            await moteur._get_async_client().aclose()
            moteur.close()

    @pytest.mark.asyncio
    async def test_annuler_un_http_en_cours_libere_la_place(self):
        moteur = OllamaEngine(host="http://annulation.test")
        moteur._scheduler = InferenceScheduler(quiet_seconds=0)
        entre = asyncio.Event()
        ferme = asyncio.Event()

        async def lent(request):
            entre.set()
            try:
                await asyncio.Event().wait()
            finally:
                ferme.set()

        moteur._async_transport = httpx.MockTransport(lent)
        source = moteur.stream_full([], model="m")
        demande = asyncio.create_task(anext(source))
        try:
            await entre.wait()
            demande.cancel()
            with pytest.raises(asyncio.CancelledError):
                await demande
            assert ferme.is_set(), "l'annulation atteint le transport"
            assert moteur._scheduler._foreground == 0
        finally:
            await source.aclose()
            await moteur._get_async_client().aclose()
            moteur.close()

    def test_un_echec_synchrone_libere_le_moteur(self):
        moteur = OllamaEngine(host="http://echec.test")
        moteur._scheduler = InferenceScheduler(quiet_seconds=0)
        moteur._client.close()
        moteur._client = httpx.Client(
            base_url=moteur._host,
            transport=httpx.MockTransport(lambda _: httpx.Response(500, text="échec")),
        )
        try:
            with pytest.raises(RuntimeError):
                moteur.generate([], model="absent")
            assert moteur._scheduler._foreground == 0
            assert moteur._scheduler._model == "", (
                "un modèle en échec n'est pas résident"
            )
        finally:
            moteur.close()

    @pytest.mark.asyncio
    async def test_l_attente_mesuree_appartient_a_la_bonne_requete(self):
        moteur = OllamaEngine(host="http://mesure.test")
        moteur._scheduler = InferenceScheduler(quiet_seconds=0)
        moteur._async_transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200, content='{"message":{"content":"ok"},"done":true}\n'
            )
        )
        libere = threading.Event()
        entre = threading.Event()

        def memoire():
            with background_work():
                with moteur._scheduler.slot("m"):
                    entre.set()
                    libere.wait(2)

        async def trames():
            async with aclosing(moteur.stream_full([], model="m")) as source:
                async for _ in source:
                    yield 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield "data: [DONE]\n\n"

        thread = threading.Thread(target=memoire)
        thread.start()
        await asyncio.to_thread(entre.wait, 1)
        mesure = ChatLatency()

        async def lire():
            return [frame async for frame in measured_sse(trames(), mesure)]

        lecture = asyncio.create_task(lire())
        try:
            await attendre(lambda: moteur._scheduler._waiting == 1)
            await asyncio.sleep(0.03)
            libere.set()
            await lecture
            assert mesure.snapshot()["inferenceQueueMs"] >= 25
            assert "inferenceQueueMs" not in ChatLatency().snapshot()
        finally:
            libere.set()
            thread.join(1)
            await moteur._get_async_client().aclose()
            moteur.close()
