"""§5 : un tour léger part sur le petit modèle, et le journal dit lequel a répondu."""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from diapason.core.config import DiapasonConfig
from diapason.core.types import Message, Role
from diapason.engine.ollama import OllamaEngine
from diapason.server import routes, tour_leger
from diapason.server.tour_leger import (
    LONGUEUR_MAX,
    Routage,
    choisir_le_modele,
    est_un_tour_leger,
)


def fil(question, **extra):
    return [
        Message(role=Role.USER, content="Bonjour"),
        Message(role=Role.ASSISTANT, content="Bonjour !"),
        Message(role=Role.USER, content=question, **extra),
    ]


fil_ = fil


def config(leger="qwen3.5:9b", defaut="qwen3.5:9b"):
    cfg = DiapasonConfig()
    cfg.intelligence.light_model = leger
    cfg.intelligence.default_model = defaut
    return cfg


class TestCeQuiEstLeger:
    """20/09/2026 : 56,6 s et 89,4 s pour deux questions d'une ligne sur le 27b."""

    @pytest.mark.parametrize(
        "question",
        [
            "Qui est le président actuel d’Haïti ?",
            'Que veut dire "Self Aware" en français ?',
            "Traduis « good morning » en français",
            "Quelle heure est-il ?",
            "Merci !",
            "C'est quoi la capitale du Canada",
            # Revue du 20/09/2026 : des noms du quotidien renvoyaient au 27b.
            "Quel cours j'ai demain ?",
            "C'est quoi le plan aujourd'hui ?",
            "As-tu reçu un courriel de La Cité ?",
            "Quand a été créé ce projet ?",
            "C'est quoi la différence par rapport à hier ?",
        ],
    )
    def test_une_question_d_une_ligne_est_legere(self, question):
        assert est_un_tour_leger(fil(question))

    @pytest.mark.parametrize(
        "question",
        [
            "Prepare moi un programme pour la programmation",
            "Explique-moi la relativité générale",
            "Pourquoi le ciel est-il bleu ?",
            "Rédige une lettre de motivation pour La Cité",
            "Donne-moi 30 exercices de conjugaison",
            "Why is the sky blue?",
            "Write a poem about autumn",
            "Résume ce texte",
            "Corrige `def f(x): return x+1`",
            "Code-moi un jeu Snake en Python",
            "Fais-moi un script bash qui renomme mes fichiers .txt en .md",
            "Résous 3x² + 2x - 5 = 0 et détaille chaque étape",
            "Quelle est la dérivée de x^3 ln(x) ?",
            "Peux-tu m'expliquer la photosynthèse ?",
            "Première ligne\nSeconde ligne collée",
            "x" * (LONGUEUR_MAX + 1),
        ],
    )
    def test_production_raisonnement_code_et_volume_gardent_le_modele_choisi(
        self, question
    ):
        assert not est_un_tour_leger(fil(question))

    @pytest.mark.parametrize(
        "suite",
        [
            "Continue",
            "Plus long",
            "Traduis-la en anglais",
            "Ajoute un paragraphe",
            "Encore",
        ],
    )
    def test_une_suite_garde_le_poids_du_tour_qu_elle_prolonge(self, suite):
        # Revue du 20/09/2026 : « Continue » après une lettre du 27b partait
        # sur le 9b, qui évinçait le 27b et prolongeait la lettre autrement.
        lettre = [
            Message(
                role=Role.USER, content="Rédige une lettre de motivation pour La Cité"
            ),
            Message(role=Role.ASSISTANT, content="Madame, Monsieur…"),
        ]
        assert not est_un_tour_leger([*lettre, Message(role=Role.USER, content=suite)])
        chaine = [
            *lettre,
            Message(role=Role.USER, content="Continue"),
            Message(role=Role.ASSISTANT, content="…suite de la lettre"),
            Message(role=Role.USER, content="Encore"),
        ]
        assert not est_un_tour_leger(chaine), (
            "de proche en proche, pas seulement une fois"
        )

    def test_une_suite_apres_un_tour_leger_reste_legere(self):
        fil = [
            *fil_("Merci !"),
            Message(role=Role.ASSISTANT, content="Avec plaisir."),
            Message(role=Role.USER, content="Continue"),
        ]
        assert est_un_tour_leger(fil)

    def test_une_question_neuve_apres_une_lettre_redevient_legere(self):
        fil = [
            Message(
                role=Role.USER, content="Rédige une lettre de motivation pour La Cité"
            ),
            Message(role=Role.ASSISTANT, content="Madame, Monsieur…"),
            Message(role=Role.USER, content="Quelle est la capitale du Canada ?"),
        ]
        assert est_un_tour_leger(fil), (
            "une vraie nouvelle question n'hérite pas du poids"
        )

    def test_une_image_n_est_jamais_legere(self):
        assert not est_un_tour_leger(fil("C'est quoi ?", images=["data:image/png"]))

    def test_sans_demande_rien_n_est_leger(self):
        assert not est_un_tour_leger([])
        assert not est_un_tour_leger([Message(role=Role.USER, content="   ")])


class TestLeChoixDuModele:
    def test_le_27b_choisi_cede_une_traduction_au_9b(self):
        routage = choisir_le_modele(
            "qwen3.8:27b-mlx", fil('Que veut dire "Self Aware" ?'), config()
        )
        assert routage == Routage(
            "qwen3.5:9b", origine="qwen3.8:27b-mlx", motif="tour léger"
        )
        assert routage.substitue
        assert routage.public() == {
            "model": "qwen3.5:9b",
            "from": "qwen3.8:27b-mlx",
            "reason": "tour léger",
        }

    def test_une_tache_lourde_garde_le_modele_choisi(self):
        routage = choisir_le_modele(
            "qwen3.8:27b-mlx", fil("Explique-moi la relativité"), config()
        )
        assert routage == Routage("qwen3.8:27b-mlx")
        assert not routage.substitue

    def test_sans_modele_leger_configure_rien_ne_change(self):
        assert choisir_le_modele(
            "qwen3.8:27b-mlx", fil("Merci !"), config(leger="")
        ) == (Routage("qwen3.8:27b-mlx"))
        assert choisir_le_modele("qwen3.8:27b-mlx", fil("Merci !"), None) == Routage(
            "qwen3.8:27b-mlx"
        )

    @pytest.mark.parametrize("demande", ["qwen3.5:9b", "default", ""])
    def test_le_leger_deja_choisi_n_est_pas_reroute_sur_lui_meme(self, demande):
        routage = choisir_le_modele(demande, fil("Merci !"), config())
        assert routage == Routage(demande), "aucun faux « rerouté » vers le même modèle"

    def test_une_trousse_du_client_n_est_jamais_reroutee(self):
        # L'API brute demande un modèle précis pour ses appels de fonctions.
        routage = choisir_le_modele(
            "qwen3.8:27b-mlx", fil("Merci !"), config(), trousse_du_client=True
        )
        assert routage == Routage("qwen3.8:27b-mlx")

    def test_un_modele_distant_n_est_jamais_reroute(self, monkeypatch):
        monkeypatch.setattr(
            "diapason.server.cloud_router.is_cloud_model", lambda m: m == "gemini-2.5"
        )
        assert choisir_le_modele("gemini-2.5", fil("Merci !"), config()) == Routage(
            "gemini-2.5"
        )


def etiquettes(request, *modeles):
    """Le GET /api/tags que le routage consulte avant de rerouter."""
    if request.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": m} for m in modeles]})
    return None


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(tour_leger, "_disponibles", {})
    monkeypatch.setattr(routes, "_chat_tooling", lambda *_: None)
    monkeypatch.setattr("diapason.desktop.etat_bureau.etat_du_bureau", lambda: None)
    monkeypatch.setattr(
        "diapason.prompt.builder.SystemPromptBuilder.build", lambda _: "Identité"
    )
    instance = FastAPI()
    instance.include_router(routes.router)
    cfg = config(leger="leger")
    cfg.reflexion.enabled = False
    instance.state.config = cfg
    return instance


def trames(texte):
    return [
        json.loads(line[6:])
        for line in texte.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


class TestLeFluxDitQuiARepondu:
    """§5 : chaque fragment et le bilan portent le modèle qui a vraiment servi."""

    @pytest.mark.asyncio
    async def test_le_tour_leger_part_sur_le_leger_et_le_dit(self, app):
        modeles_ollama = []

        def serveur(request):
            if (liste := etiquettes(request, "leger", "lourd")) is not None:
                return liste
            requete = json.loads(request.content)
            modeles_ollama.append(requete["model"])
            return httpx.Response(
                200,
                text="\n".join(
                    json.dumps(c)
                    for c in [
                        {"message": {"content": "Conscient de soi."}},
                        {"done": True, "done_reason": "stop", "eval_count": 3},
                    ]
                ),
            )

        moteur = OllamaEngine(host="http://local-test")
        moteur._async_transport = httpx.MockTransport(serveur)
        moteur._client = httpx.Client(
            base_url="http://local-test", transport=httpx.MockTransport(serveur)
        )
        app.state.engine = moteur
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                leger = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "lourd",
                        "stream": True,
                        "messages": [
                            {"role": "user", "content": 'Que veut dire "Self Aware" ?'}
                        ],
                    },
                )
                lourd = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "lourd",
                        "stream": True,
                        "messages": [
                            {"role": "user", "content": "Explique-moi la relativité"}
                        ],
                    },
                )
            finally:
                moteur.close()

        assert modeles_ollama == ["leger", "lourd"], "Ollama reçoit le modèle du tour"
        morceaux = trames(leger.text)
        assert {m["model"] for m in morceaux} == {"leger"}, (
            "aucun fragment ne prétend venir du modèle demandé"
        )
        bilan = morceaux[-1]
        assert bilan["routing"] == {
            "model": "leger",
            "from": "lourd",
            "reason": "tour léger",
        }
        assert bilan["telemetry"]["performance"]["routing"]["from"] == "lourd"
        assert bilan["telemetry"]["performance"]["inferences"][0]["model"] == "leger"

        morceaux = trames(lourd.text)
        assert {m["model"] for m in morceaux} == {"lourd"}
        assert "routing" not in morceaux[-1], "rien n'est annoncé quand rien n'a changé"
        assert morceaux[-1]["telemetry"]["performance"]["routing"] is None

    @pytest.mark.asyncio
    async def test_la_memoire_suit_le_modele_qui_vient_de_repondre(self, app):
        """Point 4 du 20/09/2026 : l'extraction ne charge jamais un modèle pour
        elle-même. Après un tour léger elle tourne sur le léger ; après un tour
        lourd, sur le lourd — un 27b résident n'est pas évincé pour un souvenir."""
        from diapason.engine.scheduling import InferenceScheduler
        from diapason.memory.extractor import FactExtractor

        modeles_ollama = []

        def serveur(request):
            if (liste := etiquettes(request, "leger", "lourd")) is not None:
                return liste
            requete = json.loads(request.content)
            modeles_ollama.append(requete["model"])
            if requete.get("stream"):
                return httpx.Response(
                    200,
                    text=json.dumps({"message": {"content": "Oui."}})
                    + "\n"
                    + json.dumps({"done": True, "done_reason": "stop"}),
                )
            return httpx.Response(200, json={"message": {"content": '["Aime le thé"]'}})

        moteur = OllamaEngine(host="http://local-test")
        moteur._scheduler = InferenceScheduler(quiet_seconds=0)
        moteur._async_transport = httpx.MockTransport(serveur)
        moteur._client = httpx.Client(
            base_url="http://local-test", transport=httpx.MockTransport(serveur)
        )
        app.state.engine = moteur
        extracteur = FactExtractor(moteur, "modele-du-demarrage", use_active_model=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                for question in ("Explique-moi la relativité", "Merci !"):
                    await client.post(
                        "/v1/chat/completions",
                        json={
                            "model": "lourd",
                            "stream": True,
                            "messages": [{"role": "user", "content": question}],
                        },
                    )
                    await asyncio.to_thread(extracteur.extract, "J'aime le thé")
            finally:
                moteur.close()
        assert modeles_ollama == ["lourd", "lourd", "leger", "leger"], (
            "chaque extraction reprend le modèle du tour qui la précède"
        )

    @pytest.mark.asyncio
    async def test_un_leger_absent_d_ollama_laisse_le_modele_demande(self, app):
        """Revue du 20/09/2026 : une faute de frappe dans light_model cassait
        tous les tours courts (404) alors que le modèle demandé aurait répondu."""
        modeles_ollama = []

        def serveur(request):
            if (liste := etiquettes(request, "lourd")) is not None:
                return liste
            requete = json.loads(request.content)
            modeles_ollama.append(requete["model"])
            return httpx.Response(
                200,
                text=json.dumps({"message": {"content": "Oui."}})
                + "\n"
                + json.dumps({"done": True, "done_reason": "stop"}),
            )

        moteur = OllamaEngine(host="http://local-test")
        moteur._async_transport = httpx.MockTransport(serveur)
        moteur._client = httpx.Client(
            base_url="http://local-test", transport=httpx.MockTransport(serveur)
        )
        app.state.engine = moteur
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                reponse = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "lourd",
                        "stream": True,
                        "messages": [{"role": "user", "content": "Merci !"}],
                    },
                )
            finally:
                moteur.close()
        assert modeles_ollama == ["lourd"], "aucun 404 : le modèle demandé répond"
        morceaux = trames(reponse.text)
        assert "routing" not in morceaux[-1]
        assert morceaux[1]["choices"][0]["delta"]["content"] == "Oui."

    def test_la_liste_des_modeles_est_relue_au_plus_toutes_les_60_s(self, monkeypatch):
        monkeypatch.setattr(tour_leger, "_disponibles", {})
        appels = []

        class Moteur:
            _host = "http://cache-test"

            def list_models(self):
                appels.append(1)
                return ["leger"] if len(appels) == 1 else []

        horloge = [0.0]

        def disponible():
            return tour_leger.modele_disponible(
                Moteur(), "leger", horloge=lambda: horloge[0]
            )

        assert disponible()
        assert disponible()
        assert len(appels) == 1, "un GET /api/tags par minute, pas par tour"
        horloge[0] = 61.0
        assert not disponible(), "un modèle retiré d'Ollama cesse d'être routé"
        assert len(appels) == 2

    def test_un_moteur_sans_listing_est_cru_sur_parole(self):
        assert tour_leger.modele_disponible(object(), "leger")

    @pytest.mark.asyncio
    async def test_la_reponse_non_diffusee_porte_aussi_le_routage(self, app):
        def serveur(request):
            if (liste := etiquettes(request, "leger", "lourd")) is not None:
                return liste
            requete = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": requete["model"],
                    "message": {"role": "assistant", "content": requete["model"]},
                    "done": True,
                    "done_reason": "stop",
                },
            )

        moteur = OllamaEngine(host="http://local-test")
        moteur._client = httpx.Client(
            base_url="http://local-test", transport=httpx.MockTransport(serveur)
        )
        app.state.engine = moteur
        app.state.agent = None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                reponse = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "lourd",
                        "messages": [{"role": "user", "content": "Merci !"}],
                    },
                )
            finally:
                moteur.close()
        corps = reponse.json()
        assert corps["model"] == "leger"
        assert corps["choices"][0]["message"]["content"] == "leger"
        assert corps["routing"] == {
            "model": "leger",
            "from": "lourd",
            "reason": "tour léger",
        }
