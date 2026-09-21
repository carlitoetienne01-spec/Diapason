"""§5/§100 : une question d'actualité se vérifie sur le web, ou se dit non vérifiée."""

import json

import pytest

from diapason.core.types import Message, Role
from diapason.engine._stubs import StreamChunk
from diapason.security.capabilities import CapabilityPolicy
from diapason.server.actualite import (
    AVERTISSEMENT,
    AVERTISSEMENT_RECHERCHE,
    AVEU,
    CONSIGNE,
    CONSIGNE_FERME,
    consigne_actualite,
    question_courante_d_actualite,
    question_d_actualite,
    recherche_concluante,
)
from diapason.server.agentic_stream import stream_with_tools
from diapason.tools._stubs import BaseTool, ToolExecutor, ToolResult, ToolSpec


class TestCeQuiEstDActualite:
    """20/09/2026 : « Qui est le président actuel du Canada ? » → Trudeau, de tête."""

    @pytest.mark.parametrize(
        "question",
        [
            "Qui est le président actuel du Canada ?",
            "Qui est le premier ministre du Canada ?",
            "Quel est le prix du dernier iPhone ?",
            "Quel temps fait-il aujourd’hui à Ottawa ?",
            "Qui a gagné le match hier ?",
            "C'est quoi le taux directeur de la Banque du Canada en 2026 ?",
            "Who is the current CEO of Apple?",
            "Quelle est la dernière version de macOS ?",
            # Revue du 20/09 : « dis-moi », « je veux savoir » n'excluent rien.
            "Dis-moi qui est le président du Canada",
            "Peux-tu me dire qui est le premier ministre du Canada ?",
            "J'aimerais savoir qui est le président actuel du Canada",
            "Donne-moi la météo à Ottawa aujourd'hui",
            "Quel est le cours du bitcoin aujourd'hui ?",
            "C’est quoi le taux directeur de la Banque du Canada en 2026 ?",
            # Réfuteurs du 20/09 : ces six-là passaient encore de tête.
            "Qui dirige le Canada ?",
            "Va-t-il pleuvoir ce soir ?",
            "Qui a remporté la Coupe Stanley ?",
            "Quelles sont les nouvelles ?",
            "Que se passe-t-il en Haïti ?",
            "Quel est le salaire minimum en Ontario ?",
        ],
    )
    def test_ce_qui_depend_du_moment(self, question):
        assert question_d_actualite(question)

    @pytest.mark.parametrize(
        "question",
        [
            "Quelle est la capitale du Canada ?",
            'Que veut dire "self aware" en français ?',
            "Explique-moi pourquoi le ciel est bleu",
            "C'est quoi un président ?",
            "Quelles sont mes tâches aujourd’hui ?",
            "Est-ce que j'ai reçu un mail du président ?",
            "Résume ce document",
            "C'est quoi le plan aujourd’hui ?",
            "Quel cours ai-je demain ?",
            # Revue du 20/09 : production, calcul, code, histoire ancienne.
            "Écris un nouveau poème sur la mer",
            "Corrige ce texte maintenant",
            "Quel est le résultat de 2 + 2 ?",
            "Comment utiliser match en Python ?",
            "Raconte-moi l'histoire du dernier roi de France",
            "C’est quoi un président ?",
            "Merci !",
            "",
        ],
    )
    def test_ce_qui_ne_se_cherche_pas_sur_le_web(self, question):
        assert not question_d_actualite(question)

    def test_seule_la_demande_courante_compte_et_jamais_une_image(self):
        fil = [
            Message(role=Role.USER, content="Qui est le président actuel du Canada ?"),
            Message(role=Role.ASSISTANT, content="…"),
            Message(role=Role.USER, content="Merci !"),
        ]
        assert not question_courante_d_actualite(fil)
        image = [Message(role=Role.USER, content="Qui est-ce ?", images=["data:…"])]
        assert not question_courante_d_actualite(image)
        assert question_courante_d_actualite(fil[:1])

    def test_la_consigne_se_pose_apres_la_demande(self):
        fil = [Message(role=Role.USER, content="Qui est le président du Canada ?")]
        travail = consigne_actualite(fil)
        assert travail[-1] == Message(role=Role.SYSTEM, content=CONSIGNE)
        assert travail[:-1] == fil, "la demande reste intacte, la consigne la suit"
        assert consigne_actualite(fil, CONSIGNE_FERME)[-1].content == CONSIGNE_FERME


class Outil(BaseTool):
    def __init__(self, nom, reponse=None, succes=True):
        self.nom = nom
        self.executions = []
        self.reponse = reponse
        self.succes = succes

    @property
    def spec(self):
        return ToolSpec(
            name=self.nom,
            description="Un outil.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        )

    def execute(self, **params):
        self.executions.append(params)
        return ToolResult(
            tool_name=self.nom,
            content=self.reponse
            or "Résultat du 20 septembre 2026 : Mark Carney est premier ministre.",
            success=self.succes,
        )


class Moteur:
    def __init__(self, tours):
        self.tours = tours
        self.appels = []

    async def stream_full(self, msgs, **kwargs):
        self.appels.append((list(msgs), kwargs))
        for chunk in self.tours[min(len(self.appels) - 1, len(self.tours) - 1)]:
            yield chunk


def appel_web(requete="premier ministre Canada 2026", ident="w1"):
    # « query », comme le vrai WebSearchTool ; « q » rendait « No query provided ».
    return {
        "index": 0,
        "id": ident,
        "type": "function",
        "function": {"name": "web_search", "arguments": json.dumps({"query": requete})},
    }


async def collecter(moteur, liste, question, **kwargs):
    # web_search exige la capacité réseau (DEFAULT_TOOL_CAPABILITIES) : sans
    # politique, l'exécuteur bloque — le refus serait alors un faux appel raté.
    politique = CapabilityPolicy(default_deny=False)
    executeur = ToolExecutor(
        liste, autoload_capability_policy=False, capability_policy=politique
    )
    return [
        e
        async for e in stream_with_tools(
            moteur,
            "local",
            [Message(role=Role.USER, content=question)],
            tools=liste,
            executor=executeur,
            **kwargs,
        )
    ]


def texte(evts):
    return "".join(e.data for e in evts if e.kind == "token")


QUESTION = "Qui est le président actuel du Canada ?"


class TestLaVerificationAuFilDuChat:
    @pytest.mark.asyncio
    async def test_la_consigne_part_au_tour_courant_et_l_appel_est_normal(self):
        liste = [Outil("web_search"), Outil("current_time")]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [
                    StreamChunk(
                        content="Mark Carney, selon les résultats du 20 sept. 2026.",
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        premier_prompt = moteur.appels[0][0]
        assert premier_prompt[-1].role == Role.SYSTEM
        assert premier_prompt[-1].content == CONSIGNE, "la consigne suit la demande"
        assert liste[0].executions == [
            {"query": "premier ministre Canada 2026", "recency": "year"}
        ], "la fraîcheur est posée par le code : un an pour un titulaire"
        assert texte(evts) == "Mark Carney, selon les résultats du 20 sept. 2026."
        assert len(moteur.appels) == 2, "un appel, une réponse : rien de plus"

    @pytest.mark.asyncio
    async def test_une_reponse_de_memoire_est_retenue_et_relancee_une_fois(self):
        liste = [Outil("web_search")]
        moteur = Moteur(
            [
                [
                    StreamChunk(
                        content="Justin Trudeau, depuis 2015.", finish_reason="stop"
                    )
                ],
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Mark Carney.", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert "Trudeau" not in texte(evts), (
            "l'affirmation de mémoire n'est pas affichée"
        )
        assert texte(evts) == "Mark Carney."
        assert moteur.appels[1][0][-1].content == CONSIGNE_FERME, (
            "la relance porte la consigne ferme"
        )
        assert liste[0].executions, "la relance a produit l'appel"
        assert len(moteur.appels) == 3

    @pytest.mark.asyncio
    async def test_deux_refus_d_appeler_donnent_une_reponse_annoncee_non_verifiee(self):
        liste = [Outil("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(content="Justin Trudeau.", finish_reason="stop")],
                [
                    StreamChunk(
                        content="Justin Trudeau, depuis 2015.", finish_reason="stop"
                    )
                ],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert texte(evts) == AVERTISSEMENT + "Justin Trudeau, depuis 2015."
        assert len(moteur.appels) == 2, "une seule relance, jamais une boucle"
        assert not liste[0].executions

    @pytest.mark.asyncio
    async def test_une_question_stable_ne_paie_rien(self):
        liste = [Outil("web_search")]
        moteur = Moteur([[StreamChunk(content="Ottawa.", finish_reason="stop")]])
        evts = await collecter(moteur, liste, "Quelle est la capitale du Canada ?")
        assert texte(evts) == "Ottawa."
        assert len(moteur.appels) == 1
        assert all(m.content != CONSIGNE for m in moteur.appels[0][0])

    @pytest.mark.asyncio
    async def test_sans_web_search_dans_la_trousse_rien_n_est_retenu(self):
        liste = [Outil("current_time")]
        moteur = Moteur(
            [[StreamChunk(content="Je ne peux pas vérifier.", finish_reason="stop")]]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert texte(evts) == "Je ne peux pas vérifier."
        assert len(moteur.appels) == 1


class TestCeQuiVautVerification:
    """Revue du 20/09 : « un outil a tourné » ne vaut pas vérification."""

    def test_seule_une_recherche_qui_rend_quelque_chose_compte(self):
        assert recherche_concluante("web_search", True, "### Titre\nSource: …")
        assert not recherche_concluante("web_search", True, "No results found.")
        assert not recherche_concluante("web_search", True, "  ")
        assert not recherche_concluante("web_search", False, "Search error: réseau")
        assert not recherche_concluante("current_time", True, "20 septembre 2026")

    @pytest.mark.asyncio
    async def test_current_time_puis_reponse_de_memoire_reste_retenue(self):
        liste = [Outil("web_search"), Outil("current_time", reponse="20 sept. 2026")]
        heure = {
            "index": 0,
            "id": "h1",
            "type": "function",
            "function": {"name": "current_time", "arguments": "{}"},
        }
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[heure])],
                [StreamChunk(content="Justin Trudeau.", finish_reason="stop")],
                [StreamChunk(tool_calls=[appel_web(ident="w2")])],
                [StreamChunk(content="Mark Carney.", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert "Trudeau" not in texte(evts)
        assert texte(evts).strip() == "Mark Carney."
        assert liste[0].executions, "la relance a obtenu la vraie recherche"

    @pytest.mark.asyncio
    async def test_une_recherche_vide_ne_rend_pas_la_reponse_verifiee(self):
        liste = [Outil("web_search", reponse="No results found.")]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Justin Trudeau.", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert texte(evts) == AVERTISSEMENT_RECHERCHE + "Justin Trudeau."
        assert len(moteur.appels) == 2, (
            "après une recherche tentée, aucune relance : on annonce, on n'insiste pas"
        )

    @pytest.mark.asyncio
    async def test_une_recherche_en_echec_est_dite_telle_quelle(self):
        liste = [Outil("web_search", reponse="Search error: hors ligne", succes=False)]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Justin Trudeau.", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert texte(evts).startswith(AVERTISSEMENT_RECHERCHE)

    @pytest.mark.asyncio
    async def test_un_silence_apres_la_relance_devient_un_aveu(self):
        liste = [Outil("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(content="Justin Trudeau.", finish_reason="stop")],
                [StreamChunk(content="", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert texte(evts) == AVEU, "jamais un bandeau sans rien dessous"

    @pytest.mark.asyncio
    async def test_une_reponse_de_memoire_coupee_par_le_plafond_est_relancee(self):
        liste = [Outil("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(content="Justin Trudeau, depuis", finish_reason="length")],
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Mark Carney.", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        assert texte(evts) == "Mark Carney."

    @pytest.mark.asyncio
    async def test_une_demande_de_precision_n_est_pas_une_reponse_de_memoire(self):
        # « Quel billet, train ou avion ? » suit le chemin des questions
        # interactives : ni relance ferme, ni avertissement (revue du 20/09).
        liste = [Outil("web_search")]
        cadrage = "Quel billet veux-tu, train ou avion ?"
        moteur = Moteur(
            [
                [StreamChunk(content=cadrage, finish_reason="stop")],
                [StreamChunk(content="", finish_reason="stop")],
            ]
        )
        evts = await collecter(
            moteur, liste, "Quel est le prix du billet ?", interactive_questions=True
        )
        assert AVERTISSEMENT not in texte(evts)
        assert AVEU not in texte(evts)
        assert all(
            msg.content != CONSIGNE_FERME for msgs, _ in moteur.appels for msg in msgs
        ), "aucune relance ferme sur un cadrage"


class TestLesSourcesEtLeControle:
    """Socle du 20/09 : résultats numérotés, pastilles [N], contrôle a posteriori."""

    def test_les_parametres_suivent_la_question(self):
        from diapason.server.actualite import (
            completer_arguments,
            parametres_de_recherche,
        )

        assert parametres_de_recherche("Qui est le premier ministre du Canada ?") == {
            "recency": "year"
        }
        assert parametres_de_recherche("Quel temps fait-il aujourd’hui à Ottawa ?") == {
            "recency": "week",
            "news": True,
        }
        assert parametres_de_recherche("Qui a gagné le match hier ?") == {
            "recency": "week",
            "news": True,
        }
        # Le modèle peut préciser davantage, jamais relâcher.
        assert json.loads(
            completer_arguments(
                '{"query": "x", "recency": "day"}', "Va-t-il pleuvoir ?"
            )
        ) == {"query": "x", "recency": "day", "news": True}
        assert completer_arguments("pas du json", "Qui ?") == "pas du json"

    def test_ce_que_la_reponse_affirme_sans_source_est_signale(self):
        from diapason.server.actualite import elements_hors_sources

        sources = (
            "[1] Carney assermenté — Le Devoir · 2026-09-18\n"
            "Extrait: Mark Carney a été assermenté 24e premier ministre en mars 2025."
        )
        assert elements_hors_sources(
            "Justin Trudeau, en poste depuis 2015.", sources, "Qui est le PM ?"
        ) == ["2015", "Justin Trudeau"]
        assert (
            elements_hors_sources(
                "Le Canada n'a pas de président. Selon Radio-Canada, Mark Carney "
                "dirige le pays depuis 2025 [1].",
                sources,
                "Qui est le président du Canada ?",
            )
            == []
        ), "les têtes de phrase, les mots de la question et les faits sourcés passent"
        assert elements_hors_sources("", sources) == []
        assert elements_hors_sources("Mark Carney.", "") == []

    def test_les_valeurs_a_symbole_et_les_tetes_de_phrase(self):
        """Revue du 20/09 : « 5 % » n'était jamais vu ; « Actuellement Mark
        Carney » était signalé alors que les sources disaient Mark Carney."""
        from datetime import date

        from diapason.server.actualite import elements_hors_sources

        sources = (
            "[1] Taux — Banque du Canada · 2026-09-18\nExtrait: taux directeur "
            "maintenu à 2,75 %. Mark Carney est premier ministre depuis mars 2025. "
            "L'essence est à 1,63 $ et il fait 18 °C."
        )
        assert elements_hors_sources("Le taux est de 5 % [1].", sources) == ["5 %"]
        assert elements_hors_sources("Le billet coûte 250 $ [1].", sources) == ["250 $"]
        assert (
            elements_hors_sources(
                "Le taux est à 2,75 % [1], l'essence à 1,63 $, il fait 18°C.", sources
            )
            == []
        ), "la même valeur sous une autre typographie est retrouvée"
        assert (
            elements_hors_sources(
                "Actuellement Mark Carney est premier ministre [1]. Le Premier "
                "Ministre Mark Carney l'a redit. D'après Le Devoir, c'est acquis.",
                sources,
            )
            == []
        ), "une tête de phrase ou un titre devant un nom retrouvé n'alerte pas"
        annee = str(date.today().year)
        assert elements_hors_sources(f"En {annee}, Mark Carney [1].", sources) == [], (
            "l'année du jour vient du contexte MAINTENANT, pas d'une source"
        )

    def test_le_modele_precise_mais_ne_relache_jamais(self):
        from diapason.server.actualite import completer_arguments

        pleuvoir = "Va-t-il pleuvoir ce soir ?"
        assert json.loads(
            completer_arguments('{"query":"x","recency":"recent"}', pleuvoir)
        ) == {
            "query": "x",
            "recency": "week",
            "news": True,
        }, "une fraîcheur invalide vaut absente"
        assert json.loads(
            completer_arguments(
                '{"query":"x","recency":"month","news":false}', pleuvoir
            )
        ) == {"query": "x", "recency": "week", "news": True}, (
            "un mois ne remplace pas la semaine décidée par le code, ni news=false"
        )
        assert json.loads(
            completer_arguments('{"query":"x","recency":"day"}', "Qui est le PM ?")
        ) == {"query": "x", "recency": "day"}, "plus strict que le code : gardé"

    @pytest.mark.asyncio
    async def test_les_sources_arrivent_numerotees_et_le_signal_ferme_le_tour(self):
        class Recherche(Outil):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_search",
                    content=(
                        "[1] Carney assermenté — Le Devoir · 2026-09-18\n"
                        "Source: https://ledevoir.com/a\nExtrait: Mark Carney, 24e PM."
                    ),
                    success=True,
                    metadata={
                        "engine": "duckduckgo/news",
                        "sources": [
                            {
                                "ref": 1,
                                "title": "Carney assermenté",
                                "url": "https://ledevoir.com/a",
                                "date": "2026-09-18",
                                "sender": "Le Devoir",
                            }
                        ],
                    },
                )

        liste = [Recherche("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [
                    StreamChunk(
                        content="Mark Carney [1], qui a succédé à Justin Trudeau.",
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        sources = [e.data for e in evts if e.kind == "sources"]
        assert sources == [
            [
                {
                    "ref": 1,
                    "title": "Carney assermenté",
                    "url": "https://ledevoir.com/a",
                    "date": "2026-09-18",
                    "sender": "Le Devoir",
                }
            ]
        ], "l'interface reçoit la liste pour ses pastilles"
        assert texte(evts) == "Mark Carney [1], qui a succédé à Justin Trudeau.", (
            "le signal n'entre pas dans le texte : il se copierait et se relirait"
        )
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"nonRetrouves": ["Justin Trudeau"]}
        ]
        message_outil = next(m for m in moteur.appels[1][0] if m.role == Role.TOOL)
        assert '"sources"' not in (message_outil.content or ""), (
            "la liste structurée n'est pas recopiée au modèle : le texte est numéroté"
        )

    @pytest.mark.asyncio
    async def test_une_seconde_recherche_continue_la_numerotation(self):
        class Recherche(Outil):
            def execute(self, **params):
                self.executions.append(params)
                page = "x" if params.get("query") == "a" else "y"
                return ToolResult(
                    tool_name="web_search",
                    content=(
                        f"[1] Titre — site.ca\nSource: https://site.ca/{page}\n"
                        "Extrait: …\n\n[2] Doublon — site.ca\n"
                        "Source: https://site.ca/x?utm_source=z\nExtrait: …"
                    ),
                    success=True,
                    metadata={
                        "sources": [
                            {
                                "ref": 1,
                                "title": "Titre",
                                "url": f"https://site.ca/{page}",
                            },
                            {
                                "ref": 2,
                                "title": "Doublon",
                                "url": "https://site.ca/x?utm_source=z",
                            },
                        ]
                    },
                )

        liste = [Recherche("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("a", ident="w1")])],
                [StreamChunk(tool_calls=[appel_web("b", ident="w2")])],
                [StreamChunk(content="Réponse [2].", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, QUESTION)
        refs = [
            s["ref"]
            for lot in (e.data for e in evts if e.kind == "sources")
            for s in lot
        ]
        # 1re recherche : x → [1] ; x?utm → même page, aucun nouveau numéro.
        # 2de recherche : y → [2] ; x?utm → reprend [1].
        assert refs == [1, 2], "une page déjà vue garde son premier numéro"
        second = [m for m in moteur.appels[2][0] if m.role == Role.TOOL][-1]
        assert (second.content or "").startswith("[2] Titre"), (
            "le texte lu par le modèle porte le même numéro que la pastille"
        )
        assert "[1] Doublon" in (second.content or ""), (
            "la page déjà connue est renumérotée vers sa première pastille"
        )
