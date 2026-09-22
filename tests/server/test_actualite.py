"""§5/§100 : une question d'actualité se vérifie sur le web, ou se dit non vérifiée."""

import json

import pytest

from diapason.core.types import Message, Role
from diapason.engine._stubs import StreamChunk
from diapason.security.capabilities import CapabilityPolicy
from diapason.server.actualite import (
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
    # Sémantique du client de bureau : le niveau part dans l'événement, pas
    # dans le texte. L'API standard (signal_textuel=True) a son propre test.
    kwargs.setdefault("signal_textuel", False)
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
        assert texte(evts) == "Justin Trudeau, depuis 2015.", (
            "plus de préfixe dans le texte (21/09) : il se copiait et se prononçait"
        )
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "memory", "searchTried": False}
        ], "le niveau « de mémoire » part avec le signal, calculé par le code"
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
        assert texte(evts) == "Justin Trudeau."
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "memory", "searchTried": True}
        ], "recherche tentée, rien rendu : de mémoire, et l'interface le sait"
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
        assert texte(evts) == "Justin Trudeau."
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "memory", "searchTried": True}
        ]

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
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "memory", "searchTried": False}
        ]

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
        assert AVEU not in texte(evts)
        assert not [e for e in evts if e.kind == "verification"], (
            "un cadrage n'est pas une réponse : aucun niveau"
        )
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
            {"notFound": ["Justin Trudeau"], "level": "partial", "searchTried": True}
        ], "un élément hors sources rend la vérification partielle"
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


# ---------------------------------------------------------------------------
# 21/09/2026 : cinq sources, et « Justin Trudeau [3] ». Ce que le code
# établit sur les sources avant que le modèle rédige.
# ---------------------------------------------------------------------------

PAGE_DU_POSTE = (
    "[2] Premier ministre du Canada — Wikipédia — fr.wikipedia.org"
    " · publié 2002-11-24 · modifié 2026-08-14\n"
    "Source: https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada\n"
    "Début : Premier ministre du Canada\n"
    "Titulaire actuel | Mark Carney | depuis le 14 mars 2025\n"
    "Premier titulaire | John A. Macdonald\n"
    "Mark Carney, le premier ministre actuel, a prêté serment le 14 mars 2025, "
    "après la démission de Justin Trudeau.\n"
)
EXTRAIT_TRUDEAU = (
    "[3] Justin Trudeau - Wikipedia — en.wikipedia.org · 2026-09-19\n"
    "Source: https://en.wikipedia.org/wiki/Justin_Trudeau\n"
    "Extrait: Justin Trudeau served as the 23rd prime minister from 2015 to 2025. "
    "His former chief of staff Katie Telford is currently a producer.\n"
)
PAGE_ANGLAISE = (
    "[1] Prime Minister of Canada - Wikipedia — en.wikipedia.org · 2026-09-01\n"
    "Source: https://en.wikipedia.org/wiki/Prime_Minister_of_Canada\n"
    "Début : The 24th and current prime minister is Mark Carney, who took office "
    "on March 14, 2025, following the resignation of Justin Trudeau. Former prime "
    "minister Stephen Harper served until 2015.\n"
)
# Une page du poste périmée : même forme d'infobox, un autre nom, une autre date.
INFOBOX_ANGLAISE_PERIMEE = (
    "[1] Prime Minister of Canada - Wikipedia — en.wikipedia.org · 2024-01-01\n"
    "Source: https://en.wikipedia.org/wiki/Prime_Minister_of_Canada\n"
    "Début : Prime Minister of Canada\n"
    "Incumbent | Justin Trudeau | since November 4, 2015\n"
)
AGENDA_PM = (
    "[5] Tuesday, April 28, 2026 | Prime Minister of Canada — pm.gc.ca · 2026-04-27\n"
    "Source: https://www.pm.gc.ca/en/news/2026/04/27\n"
    "Extrait: The Prime Minister will meet with the current Minister of Finance "
    "and National Revenue, François-Philippe Champagne.\n"
)
PREMIER_MINISTRE = "Qui est le premier ministre du Canada ?"


class TestLeTitulaireSelonLesSources:
    def test_l_infobox_et_le_paragraphe_designent_le_meme_nom(self):
        """Le prédécesseur (« après la démission de Justin Trudeau ») est à
        quarante caractères du mot « actuel » : il ne compte pas."""
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(PAGE_DU_POSTE, PREMIER_MINISTRE) == [
            {"nom": "Mark Carney", "ref": 2, "date": "2026-08-14"}
        ]

    def test_la_page_anglaise_dit_current_prime_minister(self):
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(PAGE_ANGLAISE, PREMIER_MINISTRE) == [
            {"nom": "Mark Carney", "ref": 1, "date": "2026-09-01"}
        ], "« Former prime minister Stephen Harper » n'est pas un titulaire"

    def test_currently_loin_de_la_fonction_ne_designe_personne(self):
        """« Katie Telford is currently a producer » avait « prime minister »
        à 75 caractères : un marqueur générique doit être collé à la fonction."""
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(EXTRAIT_TRUDEAU, PREMIER_MINISTRE) == []

    def test_un_intitule_de_ministere_n_est_pas_un_nom(self):
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(AGENDA_PM, PREMIER_MINISTRE) == [], (
            "« current Minister of Finance » n'est pas le premier ministre, et "
            "« National Revenue » n'est pas une personne"
        )
        assert titulaires_selon_sources(
            AGENDA_PM, "Qui est le ministre des Finances du Canada ?"
        ) == [{"nom": "François-Philippe Champagne", "ref": 5, "date": "2026-04-27"}]

    def test_le_premier_ministre_ne_repond_pas_pour_un_ministre(self):
        from diapason.server.actualite import titulaires_selon_sources

        assert (
            titulaires_selon_sources(
                PAGE_DU_POSTE, "Qui est le ministre des Finances du Canada ?"
            )
            == []
        ), "« le premier ministre actuel » ne désigne pas un ministre des Finances"

    def test_l_infobox_d_un_autre_poste_ne_compte_pas(self):
        """« Titulaire actuel » vaut pour la fonction de SA page."""
        from diapason.server.actualite import titulaires_selon_sources

        assert (
            titulaires_selon_sources(
                PAGE_DU_POSTE, "Qui est le président de la France ?"
            )
            == []
        )

    def test_qui_dirige_ne_designe_personne(self):
        """« Qui dirige le Canada ? » ne nomme pas de fonction : premier
        ministre et gouverneure générale répondraient tous deux, et le code
        annoncerait un désaccord qui n'existe pas (revue du 21/09). Silence."""
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(PAGE_ANGLAISE, "Qui dirige le Canada ?") == []

    def test_les_lignes_ne_se_collent_pas(self):
        """Sur le bloc entier, « …du Canada\\nTitulaire actuel » faisait un nom
        de « Canada Titulaire »."""
        from diapason.server.actualite import titulaires_selon_sources

        noms = [
            t["nom"] for t in titulaires_selon_sources(PAGE_DU_POSTE, PREMIER_MINISTRE)
        ]
        assert "Canada Titulaire" not in noms and "Macdonald Mark Carney" not in noms

    def test_le_plus_recent_d_abord_et_une_fois_par_nom(self):
        from diapason.server.actualite import titulaires_selon_sources

        corpus = PAGE_DU_POSTE + PAGE_ANGLAISE
        assert titulaires_selon_sources(corpus, PREMIER_MINISTRE) == [
            {"nom": "Mark Carney", "ref": 1, "date": "2026-09-01"}
        ], "le même nom dans deux sources compte une fois, avec la plus récente"


class TestLaPageDeReference:
    SOURCES = [
        {
            "ref": 1,
            "title": "Mark Carney - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Mark_Carney",
        },
        {
            "ref": 2,
            "title": "Liste des Premiers ministres du Canada — Wikipédia",
            "url": "https://fr.wikipedia.org/wiki/Liste",
        },
        {
            "ref": 3,
            "title": "Premier ministre du Canada — Wikipédia",
            "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
        },
    ]

    def test_la_page_de_la_fonction_avant_la_liste_et_la_biographie(self):
        from diapason.server.actualite import page_de_reference

        assert page_de_reference(self.SOURCES, PREMIER_MINISTRE) == (
            "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        )

    def test_sinon_la_page_wikipedia_qui_situe_la_question(self):
        """Essai du 21/09 : « Qui est le président actuel du Canada ? » (aucun
        titre ne porte « président ») lisait la biographie de Justin Trudeau,
        première page Wikipédia venue ; celle du poste portait « Canada »."""
        from diapason.server.actualite import page_de_reference

        assert page_de_reference(self.SOURCES[:2], PREMIER_MINISTRE) == (
            "https://en.wikipedia.org/wiki/Mark_Carney"
        )
        sources = [
            {
                "ref": 1,
                "title": "Justin Trudeau - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Justin_Trudeau",
            },
            {
                "ref": 2,
                "title": "Premier ministre du Canada — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
            },
        ]
        assert page_de_reference(
            sources, "Qui est le président actuel du Canada ?"
        ).endswith("Premier_ministre_du_Canada")

    def test_sans_fonction_ni_wikipedia_on_ne_lit_rien(self):
        from diapason.server.actualite import page_de_reference

        assert page_de_reference(self.SOURCES, "Quel est le taux directeur ?") == ""
        assert (
            page_de_reference(
                [{"ref": 1, "title": "Nouvelles", "url": "https://tva.ca/x"}],
                PREMIER_MINISTRE,
            )
            == ""
        )


class TestLesSourcesDatees:
    def test_des_sources_fraiches_ne_disent_rien(self):
        from datetime import date

        from diapason.server.actualite import sources_datees

        assert (
            sources_datees([{"date": date.today().isoformat()}], PREMIER_MINISTRE) == ""
        )

    def test_un_titulaire_sur_des_pages_de_deux_ans(self):
        from diapason.server.actualite import sources_datees

        assert (
            sources_datees(
                [{"date": "2024-03-01"}, {"date": "2023-01-01"}], PREMIER_MINISTRE
            )
            == "2024-03-01"
        ), "la plus récente est rendue : c'est elle que la réponse doit dater"

    def test_la_meteo_sur_une_page_de_dix_jours(self):
        from datetime import date, timedelta

        from diapason.server.actualite import sources_datees

        vieille = (date.today() - timedelta(days=10)).isoformat()
        recente = (date.today() - timedelta(days=2)).isoformat()
        assert (
            sources_datees(
                [{"date": vieille}], "Quel temps fait-il à Ottawa aujourd'hui ?"
            )
            == vieille
        )
        assert (
            sources_datees(
                [{"date": recente}], "Quel temps fait-il à Ottawa aujourd'hui ?"
            )
            == ""
        )

    def test_sans_date_on_ne_dit_rien(self):
        """§5 : une source sans date n'est pas une source vieille."""
        from diapason.server.actualite import sources_datees

        assert (
            sources_datees(
                [{"date": ""}, {"title": "x"}, {"date": "hier"}], PREMIER_MINISTRE
            )
            == ""
        )


class TestLaNoteAvantRedaction:
    def test_un_titulaire_designe_est_dit_avec_sa_source(self):
        from diapason.server.actualite import note_avant_redaction

        note, donnees = note_avant_redaction([], PAGE_DU_POSTE, PREMIER_MINISTRE)
        assert note.startswith(
            "Les sources désignent Mark Carney [2] (2026-08-14) comme titulaire actuel"
        )
        assert "prédécesseur" in note
        assert donnees == {}

    def test_deux_titulaires_font_un_desaccord_a_nommer(self):
        from diapason.server.actualite import note_avant_redaction

        note, _ = note_avant_redaction(
            [], PAGE_DU_POSTE + INFOBOX_ANGLAISE_PERIMEE, PREMIER_MINISTRE
        )
        assert note.startswith(
            "Les sources désignent plusieurs titulaires : Mark Carney [2] "
            "(2026-08-14) ; Justin Trudeau [1] (2024-01-01)."
        )
        assert "la plus récente" in note and "désaccord" in note

    def test_des_sources_vieilles_sont_dites_au_modele_et_a_l_interface(self):
        from diapason.server.actualite import note_avant_redaction

        note, donnees = note_avant_redaction(
            [{"date": "2024-03-01"}], "", PREMIER_MINISTRE
        )
        assert note.startswith("Les sources trouvées datent au plus du 2024-03-01")
        assert donnees == {"sourcesDatedAt": "2024-03-01"}

    def test_rien_a_dire_rien_de_dit(self):
        from diapason.server.actualite import note_avant_redaction

        assert note_avant_redaction(
            [], EXTRAIT_TRUDEAU, "Quel est le taux directeur ?"
        ) == ("", {})


class TestLeDesaccordSurLeTitulaire:
    def test_la_reponse_nomme_le_predecesseur(self):
        from diapason.server.actualite import desaccord_sur_le_titulaire

        assert desaccord_sur_le_titulaire(
            "Le premier ministre du Canada en 2026 est Justin Trudeau [3].",
            PAGE_DU_POSTE,
            PREMIER_MINISTRE,
        ) == {"answer": "Justin Trudeau", "sources": ["Mark Carney"]}

    def test_la_reponse_d_accord_avec_les_sources(self):
        from diapason.server.actualite import desaccord_sur_le_titulaire

        assert (
            desaccord_sur_le_titulaire(
                "C'est Mark Carney [2], depuis le 14 mars 2025.",
                PAGE_DU_POSTE,
                PREMIER_MINISTRE,
            )
            is None
        )
        assert (
            desaccord_sur_le_titulaire(
                "Actuellement Carney [2].", PAGE_DU_POSTE, PREMIER_MINISTRE
            )
            is None
        ), "un patronyme seul n'est pas un désaccord"

    def test_sans_nom_ni_titulaire_unique_rien_n_est_dit(self):
        from diapason.server.actualite import desaccord_sur_le_titulaire

        assert (
            desaccord_sur_le_titulaire(
                "Je n'ai pas pu vérifier.", PAGE_DU_POSTE, PREMIER_MINISTRE
            )
            is None
        )
        assert (
            desaccord_sur_le_titulaire(
                "Justin Trudeau [3].", EXTRAIT_TRUDEAU, PREMIER_MINISTRE
            )
            is None
        ), "sans titulaire désigné par les sources, pas de comparaison"
        deux = PAGE_DU_POSTE + INFOBOX_ANGLAISE_PERIMEE
        assert desaccord_sur_le_titulaire(
            "Justin Trudeau [1].", deux, PREMIER_MINISTRE
        ) == {"answer": "Justin Trudeau", "sources": ["Mark Carney"]}, (
            "deux titulaires, une source strictement plus récente : la réponse "
            "qui cite le périmé sans le récent est en désaccord (revue du 21/09)"
        )
        assert (
            desaccord_sur_le_titulaire("Mark Carney [2].", deux, PREMIER_MINISTRE)
            is None
        )
        meme_date = PAGE_DU_POSTE + INFOBOX_ANGLAISE_PERIMEE.replace(
            "2024-01-01", "2026-08-14"
        )
        assert (
            desaccord_sur_le_titulaire(
                "Justin Trudeau [1].", meme_date, PREMIER_MINISTRE
            )
            is None
        ), "sans date qui tranche, silence"
        assert (
            desaccord_sur_le_titulaire(
                "Justin Trudeau.", PAGE_DU_POSTE, "Quel est le taux directeur ?"
            )
            is None
        )


def resultat_de_recherche():
    return ToolResult(
        tool_name="web_search",
        content=(
            "[1] Mark Carney - Wikipedia — en.wikipedia.org · 2026-09-20\n"
            "Source: https://en.wikipedia.org/wiki/Mark_Carney\n"
            "Extrait: In 2025, Carney campaigned.\n\n"
            "[2] Premier ministre du Canada — Wikipédia — fr.wikipedia.org"
            " · 2026-08-14\n"
            "Source: https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada\n"
            "Extrait: « À propos », consulté le 11 janvier 2026\n\n"
            "[3] Justin Trudeau - Wikipedia — en.wikipedia.org · 2026-09-19\n"
            "Source: https://en.wikipedia.org/wiki/Justin_Trudeau\n"
            "Extrait: Trudeau announced a film company."
        ),
        success=True,
        metadata={
            "engine": "brave/text",
            "sources": [
                {
                    "ref": 1,
                    "title": "Mark Carney - Wikipedia",
                    "url": "https://en.wikipedia.org/wiki/Mark_Carney",
                    "date": "2026-09-20",
                    "sender": "en.wikipedia.org",
                },
                {
                    "ref": 2,
                    "title": "Premier ministre du Canada — Wikipédia",
                    "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
                    "date": "2026-08-14",
                    "sender": "fr.wikipedia.org",
                },
                {
                    "ref": 3,
                    "title": "Justin Trudeau - Wikipedia",
                    "url": "https://en.wikipedia.org/wiki/Justin_Trudeau",
                    "date": "2026-09-19",
                    "sender": "en.wikipedia.org",
                },
            ],
        },
    )


class Recherche(Outil):
    def execute(self, **params):
        self.executions.append(params)
        return resultat_de_recherche()


class Lecture(Outil):
    """Un web_read factice : la page du poste, numérotée [1] comme le vrai."""

    def __init__(self):
        super().__init__("web_read")

    @property
    def spec(self):
        return ToolSpec(
            name="web_read",
            description="Lit une page.",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}, "focus": {"type": "string"}},
            },
        )

    def execute(self, **params):
        self.executions.append(params)
        return ToolResult(
            tool_name="web_read",
            content=PAGE_DU_POSTE.replace("[2]", "[1]", 1),
            success=True,
            metadata={
                "url": params["url"],
                "title": "Premier ministre du Canada — Wikipédia",
                "modified": "2026-08-14",
                "sources": [
                    {
                        "ref": 1,
                        "title": "Premier ministre du Canada — Wikipédia",
                        "url": params["url"],
                        "date": "2026-08-14",
                        "sender": "fr.wikipedia.org",
                    }
                ],
            },
        )


def appel_lecture(url, ident="r1"):
    return {
        "index": 0,
        "id": ident,
        "type": "function",
        "function": {
            "name": "web_read",
            "arguments": json.dumps({"url": url, "focus": "premier ministre actuel"}),
        },
    }


class TestLaLectureDeLaPageDuPoste:
    """§100 : la phrase vient du récepteur — et le récepteur doit avoir LU la
    page qui répond, pas cinq extraits pris au hasard (21/09/2026)."""

    @pytest.mark.asyncio
    async def test_apres_la_recherche_le_code_lit_la_page_et_le_dit(self):
        lecture = Lecture()
        liste = [Recherche("web_search"), lecture]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [
                    StreamChunk(
                        content="Mark Carney [2], depuis le 14 mars 2025.",
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(moteur, liste, PREMIER_MINISTRE)
        assert lecture.executions == [
            {
                "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
                "focus": PREMIER_MINISTRE,
            }
        ], "la page de la FONCTION, pas la biographie ni la liste"
        debuts = [e.data for e in evts if e.kind == "tool_start"]
        assert [d["tool"] for d in debuts] == ["web_search", "web_read"]
        assert debuts[1]["auto"] is True, (
            "l'interface sait que le code a lu, pas le modèle"
        )
        fins = [e.data for e in evts if e.kind == "tool_end"]
        assert [f["tool"] for f in fins] == ["web_read", "web_search"], (
            "la lecture se termine avant que le résultat de la recherche parte"
        )
        outil = next(m for m in moteur.appels[1][0] if m.role == Role.TOOL)
        assert "Page lue (web_read) :\n[2] Premier ministre du Canada" in (
            outil.content or ""
        ), (
            "la page est jointe au résultat de la recherche, sous le numéro [2] "
            "qu'elle a déjà dans la recherche — pas [1]"
        )
        assert "Titulaire actuel | Mark Carney" in (outil.content or "")
        systeme = [m.content for m in moteur.appels[1][0] if m.role == Role.SYSTEM]
        assert any(
            "désignent Mark Carney [2] (2026-08-14) comme titulaire actuel" in s
            for s in systeme
        ), "le modèle est prévenu AVANT de rédiger"
        assert [e.data for e in evts if e.kind == "sources"] == [
            resultat_de_recherche().metadata["sources"]
        ], "la page lue ne fait pas une nouvelle pastille : elle a déjà la sienne"
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "verified", "searchTried": True}
        ], "la réponse cite le titulaire des sources : vérifiée, rien à signaler"

    @pytest.mark.asyncio
    async def test_la_reponse_qui_nomme_le_predecesseur_est_signalee(self):
        liste = [Recherche("web_search"), Lecture()]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [
                    StreamChunk(
                        content=(
                            "Le premier ministre du Canada en 2026 est "
                            "Justin Trudeau [3]."
                        ),
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(moteur, liste, PREMIER_MINISTRE)
        assert [e.data for e in evts if e.kind == "verification"] == [
            {
                "disagreement": {
                    "answer": "Justin Trudeau",
                    "sources": ["Mark Carney"],
                },
                "level": "partial",
                "searchTried": True,
            }
        ], (
            "Trudeau est dans les sources (donc pas « non retrouvé ») mais n'en "
            "est pas le titulaire"
        )
        assert (
            texte(evts)
            == "Le premier ministre du Canada en 2026 est Justin Trudeau [3]."
        ), "le signal ne réécrit pas la réponse : il la qualifie"

    @pytest.mark.asyncio
    async def test_une_question_de_valeur_ne_lit_aucune_page(self):
        lecture = Lecture()
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("prix du bitcoin")])],
                [StreamChunk(content="110 000 $ [1].", finish_reason="stop")],
            ]
        )
        evts = await collecter(
            moteur,
            [Recherche("web_search"), lecture],
            "Quel est le prix du bitcoin aujourd'hui ?",
        )
        assert lecture.executions == [], (
            "lire une page au hasard n'apporte rien à un prix"
        )
        assert [
            d["tool"] for d in (e.data for e in evts if e.kind == "tool_start")
        ] == ["web_search"]

    @pytest.mark.asyncio
    async def test_sans_web_read_dans_la_trousse_rien_n_est_lu(self):
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Mark Carney [1].", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, [Recherche("web_search")], PREMIER_MINISTRE)
        assert [
            d["tool"] for d in (e.data for e in evts if e.kind == "tool_start")
        ] == ["web_search"]

    @pytest.mark.asyncio
    async def test_une_page_illisible_n_arrete_pas_le_tour(self):
        class Panne(Lecture):
            def execute(self, **params):
                raise RuntimeError("réseau coupé")

        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Réponse [1].", finish_reason="stop")],
            ]
        )
        evts = await collecter(
            moteur, [Recherche("web_search"), Panne()], PREMIER_MINISTRE
        )
        fins = {f["tool"]: f for f in (e.data for e in evts if e.kind == "tool_end")}
        assert fins["web_read"]["success"] is False
        assert "réseau coupé" in fins["web_read"]["result"]
        assert texte(evts) == "Réponse [1]."
        outil = next(m for m in moteur.appels[1][0] if m.role == Role.TOOL)
        assert "Page lue" not in (outil.content or ""), (
            "une lecture ratée ne joint rien"
        )

    @pytest.mark.asyncio
    async def test_la_page_que_le_modele_lit_lui_meme_rejoint_les_sources(self):
        """§82 : web_read est un outil du modèle, pas seulement du code. Une
        question de prix n'est pas lue d'office ; le modèle peut lire."""
        lecture = Lecture()
        url = "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("prix du bitcoin")])],
                [StreamChunk(tool_calls=[appel_lecture(url)])],
                [StreamChunk(content="Réponse [2].", finish_reason="stop")],
            ]
        )
        evts = await collecter(
            moteur,
            [Recherche("web_search"), lecture],
            "Quel est le prix du bitcoin aujourd'hui ?",
        )
        assert lecture.executions and lecture.executions[0]["url"] == url
        lu = [m for m in moteur.appels[2][0] if m.role == Role.TOOL][-1]
        assert (lu.content or "").startswith("[2] Premier ministre du Canada"), (
            "la page lue porte le numéro de sa pastille, pas [1]"
        )
        assert [e.data for e in evts if e.kind == "sources"] == [
            resultat_de_recherche().metadata["sources"]
        ]


class TestLaPageLaPlusProcheDeLaQuestion:
    def test_le_titre_qui_reprend_le_plus_de_mots_de_la_question(self):
        """« Premier ministre du Québec » sortait avant « Premier ministre du
        Canada » et aurait été lue pour une question sur le Canada."""
        from diapason.server.actualite import page_de_reference

        sources = [
            {
                "ref": 1,
                "title": "Premier ministre du Québec — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Quebec",
            },
            {
                "ref": 2,
                "title": "Premier ministre du Canada — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
            },
        ]
        assert page_de_reference(sources, PREMIER_MINISTRE).endswith("du_Canada")
        assert page_de_reference(
            sources, "Qui est le premier ministre du Québec ?"
        ).endswith("du_Quebec")
        assert page_de_reference(sources, "Qui est le premier ministre ?").endswith(
            "du_Quebec"
        ), "à égalité, l'ordre du moteur décide"


class TestUnePageLueVautVerification:
    @pytest.mark.asyncio
    async def test_le_modele_qui_lit_une_page_n_est_pas_relance(self):
        """Une page lue est une source : la retenue de la réponse de mémoire
        ne se déclenche pas après un web_read réussi."""
        lecture = Lecture()
        url = "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_lecture(url)])],
                [StreamChunk(content="Mark Carney [1].", finish_reason="stop")],
            ]
        )
        evts = await collecter(
            moteur, [Recherche("web_search"), lecture], PREMIER_MINISTRE
        )
        assert texte(evts) == "Mark Carney [1].", "ni relance ferme, ni avertissement"
        assert len(moteur.appels) == 2


# ---------------------------------------------------------------------------
# Revue du 21/09/2026 : les VRAIES pages de postes (président de la France,
# maire de Montréal, pape, gouverneure générale…) désignaient un ancien
# titulaire sur neuf pages sur dix — « Premier titulaire | Vicomte Monck »,
# « fut en poste de 1946 à 1952 », « since the first president, George
# Washington » — et « Le premier ministre actuel doit rencontrer Donald
# Trump » désignait Trump. Ce que l'extraction refuse désormais.
# ---------------------------------------------------------------------------

PAGE_GOUVERNEUR = (
    "[1] Gouverneur général du Canada — Wikipédia — fr.wikipedia.org · 2026-07-22\n"
    "Source: https://fr.wikipedia.org/wiki/Gouverneur_general_du_Canada\n"
    "Début : Gouverneur général du Canada\n"
    "Titulaire actuelle | Louise Arbour | depuis le 22 juillet 2026\n"
    "Premier titulaire | Vicomte Monck\n"
    "Harold Alexander, qui fut en poste de 1946 à 1952, fut le dernier "
    "gouverneur général britannique.\n"
    "Il est de tradition que la personne désignée reste en poste pour un "
    "minimum de cinq ans, selon le bon vouloir de Sa Majesté.\n"
)
PAGE_POTUS = (
    "[1] President of the United States - Wikipedia — en.wikipedia.org · 2026-09-17\n"
    "Source: https://en.wikipedia.org/wiki/President_of_the_United_States\n"
    "Début : President of the United States\n"
    "Incumbent | Donald Trump | since January 20, 2025\n"
    "The power of the presidency has grown since the first president, George "
    "Washington, took office in 1789.\n"
)
PAGE_PAPE = (
    "[1] Pape — Wikipédia — fr.wikipedia.org · 2026-09-10\n"
    "Source: https://fr.wikipedia.org/wiki/Pape\n"
    "Début : Pape\n"
    "Titulaire actuel | Léon XIV | depuis le 8 mai 2025\n"
    "Premier titulaire | Apôtre Pierre\n"
    "Robert Francis Prevost, élu le 8 mai 2025 sous le nom de Léon XIV, est le "
    "pape actuel.\n"
)
PAGE_QUEBEC = (
    "[3] Premier ministre du Québec — Wikipédia — fr.wikipedia.org · 2026-09-19\n"
    "Source: https://fr.wikipedia.org/wiki/Premier_ministre_du_Quebec\n"
    "Début : Premier ministre du Québec\n"
    "Titulaire actuelle | Christine Fréchette | depuis le 15 avril 2026\n"
)


class TestCeQueLExtractionRefuse:
    def test_les_anciens_titulaires_du_recit_historique(self):
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(
            PAGE_GOUVERNEUR, "Qui est la gouverneure générale du Canada ?"
        ) == [{"nom": "Louise Arbour", "ref": 1, "date": "2026-07-22"}], (
            "ni le premier titulaire, ni « fut en poste de 1946 à 1952 », ni "
            "« reste en poste … Sa Majesté »"
        )
        assert titulaires_selon_sources(
            PAGE_POTUS, "Qui est le président des États-Unis ?"
        ) == [{"nom": "Donald Trump", "ref": 1, "date": "2026-09-17"}], (
            "« since the first president, George Washington » parle du passé"
        )

    def test_l_infobox_l_emporte_sur_les_phrases(self):
        """Léon XIV (infobox) et Robert Francis Prevost (phrase) sont le même
        homme : deux « titulaires » auraient fait annoncer un désaccord."""
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(PAGE_PAPE, "Qui est le pape ?") == [
            {"nom": "Léon XIV", "ref": 1, "date": "2026-09-10"}
        ]

    def test_le_nom_le_plus_proche_n_est_pas_le_sujet(self):
        from diapason.server.actualite import titulaires_selon_sources

        # L'en-tête situe la fonction (« du Canada ») : sans cela, la source
        # ne compte pas — un extrait de presse sans ressort ne désigne personne.
        presse = (
            "[1] Le premier ministre du Canada à Washington — lapresse.ca"
            " · 2026-09-20\n"
            "Source: https://lapresse.ca/sommet\n"
            "Extrait: Le premier ministre actuel du Canada doit rencontrer Donald "
            "Trump mardi.\n"
        )
        assert titulaires_selon_sources(presse, PREMIER_MINISTRE) == [], (
            "« doit rencontrer » n'est pas « est » : Trump n'est pas désigné"
        )
        assert titulaires_selon_sources(
            presse.replace("doit rencontrer Donald Trump mardi", "est Mark Carney"),
            PREMIER_MINISTRE,
        ) == [{"nom": "Mark Carney", "ref": 1, "date": "2026-09-20"}]

    def test_le_quebec_ne_repond_pas_pour_le_canada(self):
        from diapason.server.actualite import titulaires_selon_sources

        assert titulaires_selon_sources(PAGE_QUEBEC, PREMIER_MINISTRE) == []
        assert titulaires_selon_sources(
            PAGE_DU_POSTE + PAGE_QUEBEC, PREMIER_MINISTRE
        ) == [{"nom": "Mark Carney", "ref": 2, "date": "2026-08-14"}]
        assert titulaires_selon_sources(
            PAGE_DU_POSTE + PAGE_QUEBEC, "Qui est le premier ministre du Québec ?"
        ) == [{"nom": "Christine Fréchette", "ref": 3, "date": "2026-09-19"}]

    def test_le_titre_colle_au_nom_ne_fait_pas_un_second_titulaire(self):
        from diapason.server.actualite import titulaires_selon_sources

        presse = (
            "[1] Ottawa — radio-canada.ca · 2026-09-20\n"
            "Source: https://ici.radio-canada.ca/ottawa\n"
            "Extrait: Le premier ministre actuel du Canada est Prime Minister "
            "Mark Carney.\n"
        )
        # « radio-canada.ca » situe la source au Canada : elle compte.
        assert titulaires_selon_sources(PAGE_DU_POSTE + presse, PREMIER_MINISTRE) == [
            {"nom": "Mark Carney", "ref": 1, "date": "2026-09-20"}
        ]
        assert titulaires_selon_sources(
            "[1] Pope - Wikipedia — en.wikipedia.org · 2026-08-23\n"
            "Source: https://en.wikipedia.org/wiki/Pope\n"
            "Incumbent | Pope Leo XIV | since 8 May 2025\n",
            "Qui est le pape ?",
        ) == [{"nom": "Leo XIV", "ref": 1, "date": "2026-08-23"}]

    def test_une_question_qui_ne_demande_pas_un_nom(self):
        """« Quel est le salaire du premier ministre ? » nomme la fonction sans
        chercher son titulaire : ni lecture d'office, ni « réponds avec ce nom »."""
        from diapason.server.actualite import question_de_titulaire

        assert not question_de_titulaire("Quel est le salaire du premier ministre ?")
        assert not question_de_titulaire("Quel est le taux directeur ?")
        assert question_de_titulaire("Qui est la mairesse de Montréal ?")
        assert question_de_titulaire("Comment s'appelle le maire d'Ottawa ?")
        assert question_de_titulaire("Qui dirige le Canada ?")

    def test_le_desaccord_exige_un_predecesseur_avere(self):
        """Le signal « la réponse nomme un prédécesseur » ne repose pas sur la
        seule extraction : le nom de la réponse doit être donné comme
        prédécesseur quelque part dans les sources."""
        from diapason.server.actualite import desaccord_sur_le_titulaire

        sans_demission = PAGE_DU_POSTE.replace(
            "après la démission de Justin Trudeau", "à Ottawa"
        )
        assert (
            desaccord_sur_le_titulaire(
                "Justin Trudeau [2].", sans_demission, PREMIER_MINISTRE
            )
            is None
        ), "rien dans les sources ne dit que Trudeau est un ancien : silence"
        assert desaccord_sur_le_titulaire(
            "Justin Trudeau [2].", PAGE_DU_POSTE, PREMIER_MINISTRE
        ) == {"answer": "Justin Trudeau", "sources": ["Mark Carney"]}


class TestLAgeDesSourcesMelangees:
    def test_une_source_non_datee_eteint_le_constat(self):
        from diapason.server.actualite import sources_datees

        assert (
            sources_datees([{"date": "2024-03-01"}, {"date": ""}], PREMIER_MINISTRE)
            == ""
        ), "la source non datée est souvent la bonne : on ne dit rien"

    def test_un_an_jour_pour_jour_est_vieux(self):
        from datetime import date, timedelta

        from diapason.server.actualite import sources_datees

        il_y_a_un_an = (date.today() - timedelta(days=365)).isoformat()
        assert (
            sources_datees([{"date": il_y_a_un_an}], PREMIER_MINISTRE) == il_y_a_un_an
        ), "brave écrit « 1 year ago » pour 365 jours"


class TestLaNoteEstRemplaceeEtLaPageGardeSaPastille:
    """Revue du 21/09 : la note SYSTEM s'ajoutait à chaque passage (deux
    consignes contradictoires empilées) ; après une redirection http → https,
    la page lue par le modèle recevait une quatrième pastille."""

    @pytest.mark.asyncio
    async def test_une_seule_note_dans_le_fil_apres_deux_passages(self):
        class LecturePerimee(Lecture):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_read",
                    content=INFOBOX_ANGLAISE_PERIMEE,
                    success=True,
                    metadata={
                        "sources": [
                            {
                                "ref": 1,
                                "title": "Prime Minister of Canada - Wikipedia",
                                "url": params["url"],
                                "date": "2024-01-01",
                            }
                        ]
                    },
                )

        url_en = "https://en.wikipedia.org/wiki/Prime_Minister_of_Canada"
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(tool_calls=[appel_lecture(url_en)])],
                [StreamChunk(content="Mark Carney [2].", finish_reason="stop")],
            ]
        )
        # La lecture automatique lit la page française (Carney) ; le modèle
        # lit ensuite la page anglaise périmée (Trudeau, 2024).
        lecture_modele = LecturePerimee()

        class Aiguilleur(Lecture):
            def execute(self, **params):
                if params["url"] == url_en:
                    return lecture_modele.execute(**params)
                return Lecture.execute(self, **params)

        liste = [Recherche("web_search"), Aiguilleur()]
        await collecter(moteur, liste, PREMIER_MINISTRE)
        notes = [
            m.content
            for m in moteur.appels[2][0]
            if m.role == Role.SYSTEM and "titulaire" in (m.content or "")
        ]
        assert len(notes) == 1, "une note, la dernière — jamais empilées"
        assert notes[0].startswith("Les sources désignent plusieurs titulaires"), (
            "la seconde lecture a changé le constat : la note dit le désaccord"
        )
        assert (
            "Mark Carney [2] (2026-08-14) ; Justin Trudeau [4] (2024-01-01)" in notes[0]
        )

    @pytest.mark.asyncio
    async def test_une_redirection_ne_fait_pas_une_nouvelle_pastille(self):
        class LectureRedirigee(Lecture):
            def execute(self, **params):
                resultat = Lecture.execute(self, **params)
                finale = params["url"].replace("https://fr.", "https://www.fr.")
                resultat.metadata["sources"][0]["url"] = finale
                resultat.metadata["url"] = finale
                return resultat

        url = "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Mark Carney [2].", finish_reason="stop")],
            ]
        )
        evts = await collecter(
            moteur, [Recherche("web_search"), LectureRedirigee()], PREMIER_MINISTRE
        )
        refs = [
            s["ref"]
            for lot in (e.data for e in evts if e.kind == "sources")
            for s in lot
        ]
        assert refs == [1, 2, 3], "la page lue garde la pastille [2] de la recherche"
        outil = next(m for m in moteur.appels[1][0] if m.role == Role.TOOL)
        assert "Page lue (web_read) :\n[2] " in (outil.content or "")
        assert url in (outil.content or "") or "www.fr.wikipedia.org" in (
            outil.content or ""
        )


# ---------------------------------------------------------------------------
# P1/P2 du jury (21/09/2026) : le niveau de vérification vient du code, et la
# vérification se force à la main — bouton, « Vérifie ça » tapé ou dicté.
# ---------------------------------------------------------------------------


class TestLeNiveauDeVerification:
    SOURCES = [{"ref": 1, "url": "https://a"}, {"ref": 2, "url": "https://b"}]

    def test_de_memoire_tant_que_rien_n_a_ete_trouve(self):
        from diapason.server.actualite import niveau_de_verification

        assert (
            niveau_de_verification("Mark Carney [1].", self.SOURCES, False) == "memory"
        )
        assert niveau_de_verification("Mark Carney.", [], False) == "memory"

    def test_partiel_sans_citation_ou_avec_un_numero_inconnu(self):
        from diapason.server.actualite import niveau_de_verification

        assert (
            niveau_de_verification("Mark Carney.", self.SOURCES, True) == "partial"
        ), "des sources, mais la réponse n'en cite aucune"
        assert (
            niveau_de_verification("Mark Carney [7].", self.SOURCES, True) == "partial"
        ), "un numéro que la carte ne connaît pas"

    def test_partiel_quand_le_controle_a_releve_quelque_chose(self):
        from diapason.server.actualite import niveau_de_verification

        assert (
            niveau_de_verification(
                "Mark Carney [1].", self.SOURCES, True, {"notFound": ["2015"]}
            )
            == "partial"
        )
        assert (
            niveau_de_verification(
                "Justin Trudeau [1].",
                self.SOURCES,
                True,
                {
                    "disagreement": {
                        "answer": "Justin Trudeau",
                        "sources": ["Mark Carney"],
                    }
                },
            )
            == "partial"
        )

    def test_verifie_quand_tout_tient(self):
        from diapason.server.actualite import niveau_de_verification

        assert niveau_de_verification(
            "Mark Carney [1][2].", self.SOURCES, True, {}
        ) == ("verified")


class TestLaDemandeDeVerification:
    @pytest.mark.parametrize(
        "texte",
        [
            "Vérifie ça",
            "Vérifie ça en ligne.",
            "vérifie-le",
            "confirme-moi ça",
            "c'est sûr ?",
            "t'es sûr de ça ?",
            "verifie sa",
            "Vérifie ça svp",
            "est-ce que c'est vrai ?",
            "ah bon ?",
            "checke ça",
            "C'est vrai ?",
            "Est-ce vrai ?",
            "Check this online",
            "Verify this online.",
            "Peux-tu vérifier ça ?",
            "Tu es sûr ?",
            "Vraiment ?",
            "Vérifie cette information sur le web, stp.",
        ],
    )
    def test_ce_qui_est_une_demande(self, texte):
        from diapason.server.actualite import est_une_demande_de_verification

        assert est_une_demande_de_verification(texte), texte

    @pytest.mark.parametrize(
        "texte",
        [
            "Vérifie que mon script compile",
            "Vérifie mes tâches",
            "Confirme la réunion de demain",
            "Qui est le premier ministre du Canada ?",
            "",
            # Revue du 21/09 : un verbe nu est un acquiescement — « Confirme »
            # à « je crée la tâche ? » créait la tâche puis « n'a pas pu vérifier ».
            "Vérifie",
            "Confirme",
            "Confirmé.",
            "Check",
            "Sure",
            "Vraiment",
            "vérifie ça dans mes notes",
        ],
    )
    def test_ce_qui_n_en_est_pas(self, texte):
        """« Vérifie que mon script compile » n'envoie personne sur le web."""
        from diapason.server.actualite import est_une_demande_de_verification

        assert not est_une_demande_de_verification(texte), texte

    def test_la_question_a_verifier_est_celle_qui_precede(self):
        from diapason.server.actualite import question_a_verifier

        fil = [
            Message(role=Role.USER, content=PREMIER_MINISTRE),
            Message(role=Role.ASSISTANT, content="Justin Trudeau."),
            Message(role=Role.USER, content="Vérifie ça."),
        ]
        assert question_a_verifier(fil) == PREMIER_MINISTRE
        assert question_a_verifier(fil[:1]) == PREMIER_MINISTRE
        assert (
            question_a_verifier([Message(role=Role.USER, content="Vérifie ça.")]) == ""
        ), "sans question avant, une demande nue n'a rien à vérifier"
        # Revue du 21/09 : une seconde pression vérifiait « Vérifie ça en ligne. ».
        deux = fil + [
            Message(role=Role.ASSISTANT, content="Mark Carney [2]."),
            Message(role=Role.USER, content="Vérifie ça en ligne."),
        ]
        assert question_a_verifier(deux) == PREMIER_MINISTRE
        assert question_a_verifier(deux, forcee=True) == PREMIER_MINISTRE
        # Le bouton avec un libellé traduit : le dernier message est la demande.
        traduit = fil[:2] + [Message(role=Role.USER, content="Verify this online.")]
        assert question_a_verifier(traduit, forcee=True) == PREMIER_MINISTRE
        assert (
            question_a_verifier(
                [
                    Message(
                        role=Role.USER,
                        content="Le Canada compte 40 millions d'habitants.",
                    )
                ],
                forcee=True,
            )
            == "Le Canada compte 40 millions d'habitants."
        ), "une affirmation seule, envoyée avec le bouton, se vérifie elle-même"


class TestLaVerificationForcee:
    """§82 : la reconnaissance lexicale ne couvrira jamais tout ; le bouton
    (verifyOnline) et « Vérifie ça » forcent la recherche."""

    @pytest.mark.asyncio
    async def test_le_bouton_force_la_recherche_sur_une_affirmation_quelconque(self):
        liste = [Recherche("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(content="Oui, c'est exact.", finish_reason="stop")],
                [StreamChunk(tool_calls=[appel_web("population du Canada 2026")])],
                [StreamChunk(content="Environ 41 millions [1].", finish_reason="stop")],
            ]
        )
        evts = await collecter(
            moteur,
            liste,
            "Le Canada compte 40 millions d'habitants.",
            verifier_en_ligne=True,
        )
        premier = [m.content for m in moteur.appels[0][0] if m.role == Role.SYSTEM]
        assert any(
            "Une vérification en ligne est demandée pour : « Le Canada compte 40 "
            "millions d'habitants. »" in c
            for c in premier
        ), "la consigne nomme ce qu'il faut vérifier"
        assert "Oui, c'est exact." not in texte(evts), (
            "la confirmation de mémoire est retenue, la relance ferme suit"
        )
        assert texte(evts) == "Environ 41 millions [1]."
        assert liste[0].executions, "la recherche a bien tourné"

    @pytest.mark.asyncio
    async def test_verifie_ca_tape_ou_dicte_porte_sur_la_question_d_avant(self):
        liste = [Recherche("web_search"), Lecture()]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [StreamChunk(content="Mark Carney [2].", finish_reason="stop")],
            ]
        )
        politique = CapabilityPolicy(default_deny=False)
        executeur = ToolExecutor(
            liste, autoload_capability_policy=False, capability_policy=politique
        )
        evts = [
            e
            async for e in stream_with_tools(
                moteur,
                "local",
                [
                    Message(role=Role.USER, content=PREMIER_MINISTRE),
                    Message(role=Role.ASSISTANT, content="Justin Trudeau."),
                    Message(role=Role.USER, content="Vérifie ça."),
                ],
                tools=liste,
                executor=executeur,
            )
        ]
        systeme = [m.content for m in moteur.appels[0][0] if m.role == Role.SYSTEM]
        assert any(f"demandée pour : « {PREMIER_MINISTRE} »" in c for c in systeme)
        assert liste[1].executions, (
            "la page du poste est lue : la question à vérifier est bien celle "
            "du premier ministre, pas « Vérifie ça »"
        )
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "verified", "searchTried": True}
        ]


class TestLesUnitesSansPluriel:
    def test_une_source_anglaise_au_singulier(self):
        """Essai du 21/09 : « 40,5 millions » signalé non retrouvé alors que la
        source disait « 40.5 million »."""
        from diapason.server.actualite import elements_hors_sources

        sources = "[5] Canada population — statcan.gc.ca\nExtrait: 40.5 million people."
        assert elements_hors_sources("Environ 40,5 millions [5].", sources, "") == []
        assert elements_hors_sources("Environ 42,5 millions [5].", sources, "") == [
            "42,5 millions"
        ], "un autre nombre reste non retrouvé"


class TestLeSigneTextuelPourLApiStandard:
    @pytest.mark.asyncio
    async def test_un_client_qui_ne_lit_pas_les_evenements_garde_le_prefixe(self):
        """Revue du 21/09 : sans le préfixe, curl ou un SDK OpenAI recevaient
        une réponse de mémoire sans aucun signe (§100). Le client de bureau,
        lui, lit le niveau et n'en veut pas dans le texte."""
        from diapason.server.actualite import AVERTISSEMENT

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
        evts = await collecter(moteur, liste, QUESTION, signal_textuel=True)
        assert texte(evts) == AVERTISSEMENT + "Justin Trudeau, depuis 2015."
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "memory", "searchTried": False}
        ], "l'événement part aussi : un client qui le lit l'a"


class TestCeQueLaBulleAffiche:
    @pytest.mark.asyncio
    async def test_la_prose_ecrite_avant_un_second_outil_est_jugee_aussi(self):
        """Revue du 21/09 : « Justin Trudeau [3], depuis 2015 » écrit avant un
        second outil restait affiché sous un badge vert."""
        liste = [Recherche("web_search"), Lecture()]
        url = "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web()])],
                [
                    StreamChunk(content="Justin Trudeau [3], depuis 2015. "),
                    StreamChunk(tool_calls=[appel_lecture(url)]),
                ],
                [StreamChunk(content="Voilà.", finish_reason="stop")],
            ]
        )
        evts = await collecter(moteur, liste, PREMIER_MINISTRE)
        assert texte(evts).startswith("Justin Trudeau [3], depuis 2015.")
        signal = [e.data for e in evts if e.kind == "verification"]
        assert signal and signal[0]["level"] == "partial"
        assert signal[0]["disagreement"] == {
            "answer": "Justin Trudeau",
            "sources": ["Mark Carney"],
        }, "ce que la bulle affiche est jugé en entier, pas le dernier passage"

    @pytest.mark.asyncio
    async def test_une_recherche_faite_d_elle_meme_recoit_son_badge(self):
        """Hors actualité, le modèle a cherché : les pastilles [N] sont là, le
        badge aussi — sans le contrôle lexical réservé aux questions d'actualité."""
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("recette de tarte")])],
                [
                    StreamChunk(
                        content="Ricardo Larrivée propose une pâte [1].",
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(
            moteur, [Recherche("web_search")], "Donne-moi une recette de tarte."
        )
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "verified", "searchTried": True}
        ], "vérifié, et « Ricardo Larrivée » n'est pas signalé (revue du 20/09)"

    @pytest.mark.asyncio
    async def test_une_demande_sur_des_donnees_personnelles_reste_locale(self):
        """Revue du 21/09 : « Vérifie ça » après « quelles sont mes tâches ? »
        forçait une recherche web sur des données personnelles."""
        liste = [Recherche("web_search")]
        moteur = Moteur(
            [[StreamChunk(content="Tu as trois tâches.", finish_reason="stop")]]
        )
        politique = CapabilityPolicy(default_deny=False)
        executeur = ToolExecutor(
            liste, autoload_capability_policy=False, capability_policy=politique
        )
        evts = [
            e
            async for e in stream_with_tools(
                moteur,
                "local",
                [
                    Message(role=Role.USER, content="Quelles sont mes tâches ?"),
                    Message(role=Role.ASSISTANT, content="Tu as trois tâches."),
                    Message(role=Role.USER, content="Vérifie ça."),
                ],
                tools=liste,
                executor=executeur,
                verifier_en_ligne=True,
                signal_textuel=False,
            )
        ]
        assert texte(evts) == "Tu as trois tâches."
        assert not liste[0].executions, "aucune recherche web sur les tâches"
        assert not [e for e in evts if e.kind == "verification"]
        assert len(moteur.appels) == 1, "ni retenue, ni relance"


@pytest.mark.asyncio
async def test_sur_un_modele_distant_le_bouton_dit_qu_il_n_a_rien_verifie(monkeypatch):
    """Revue du 21/09 : verifyOnline sur un modèle distant était ignoré en
    silence — la réponse arrivait sans recherche ni badge et se lisait comme
    une vérification. Le chemin non outillé émet le niveau « memory »."""
    from unittest.mock import MagicMock

    from diapason.server.models import ChatCompletionRequest
    from diapason.server.routes import _handle_stream

    async def flux_cloud(model, messages, temperature, max_tokens):
        yield "Oui, c'est vrai."

    monkeypatch.setattr("diapason.server.cloud_router.stream_cloud", flux_cloud)
    requete = ChatCompletionRequest(
        model="gpt-test",
        stream=True,
        interactiveQuestions=True,
        verifyOnline=True,
        messages=[{"role": "user", "content": "Vérifie ça en ligne."}],
    )
    response = await _handle_stream(MagicMock(), requete.model, requete)
    corps = "".join([part async for part in response.body_iterator])
    assert (
        'event: verification\ndata: {"level": "memory", "searchTried": false}' in corps
    )
    assert "[DONE]" in corps


class TestLaPageOfficielle:
    """P6 (21/09/2026) : « Quel temps fait-il ce soir ? » recevait cinq
    articles sans une donnée météo ; Environnement Canada publie la
    prévision de chaque ville sur une page que web_read lit d'un coup."""

    @staticmethod
    def lecture_meteo():
        class Meteo(Lecture):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_read",
                    content=(
                        "[1] Ottawa, ON - Prévision 7 jours - Environnement Canada"
                        " — meteo.gc.ca · modifié 2026-09-03\n"
                        f"Source: {params['url']}\n"
                        "Début : Ottawa, ON\nCe soir et cette nuit\n3°C\n"
                        "Partiellement nuageux\nmar 22 sep\n17°C\nEnsoleillé\n"
                    ),
                    success=True,
                    metadata={
                        "url": params["url"],
                        "modified": "2026-09-03",
                        "sources": [
                            {
                                "ref": 1,
                                "title": "Ottawa, ON - Prévision 7 jours",
                                "url": params["url"],
                                "date": "2026-09-03",
                                "sender": "meteo.gc.ca",
                            }
                        ],
                    },
                )

        return Meteo()

    @pytest.mark.asyncio
    async def test_la_prevision_officielle_est_lue_meme_quand_la_recherche_est_vide(
        self,
    ):
        from datetime import date

        lecture = self.lecture_meteo()
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("météo Ottawa ce soir")])],
                [
                    StreamChunk(
                        content="Ce soir, 3 °C et partiellement nuageux [1].",
                        finish_reason="stop",
                    )
                ],
            ]
        )
        vide = Outil("web_search", reponse="No results found.")
        evts = await collecter(
            moteur, [vide, lecture], "Quel temps fait-il ce soir ?", ville="Ottawa"
        )
        assert lecture.executions and lecture.executions[0]["url"] == (
            "https://meteo.gc.ca/fr/location/index.html?coords=45.421,-75.697"
        ), "la ville vient de la config quand la question n'en nomme pas"
        assert "ce soir cette nuit demain" in lecture.executions[0]["focus"]
        sources = [
            s for lot in (e.data for e in evts if e.kind == "sources") for s in lot
        ]
        assert sources == [
            {
                "ref": 1,
                "title": "Ottawa — Prévision 7 jours, Environnement Canada",
                "url": "https://meteo.gc.ca/fr/location/index.html?coords=45.421,-75.697",
                "date": date.today().isoformat(),
                "sender": "meteo.gc.ca",
                "official": True,
            }
        ], "une page vivante est datée du jour de sa lecture, et dite officielle"
        outil = next(m for m in moteur.appels[1][0] if m.role == Role.TOOL)
        assert "Source officielle, lue par le code — réponds d'après elle :" in (
            outil.content or ""
        )
        assert "[1] Ottawa — Prévision 7 jours, Environnement Canada — meteo.gc.ca" in (
            outil.content or ""
        )
        assert "source officielle · consultée le" in (outil.content or "")
        assert "Ce soir et cette nuit" in (outil.content or "")
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "verified", "searchTried": True}
        ], "la recherche était vide, la page officielle vaut vérification"
        assert texte(evts) == "Ce soir, 3 °C et partiellement nuageux [1]."

    @pytest.mark.asyncio
    async def test_sans_ville_connue_aucune_page_n_est_lue(self):
        lecture = self.lecture_meteo()
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("météo ce soir")])],
                [StreamChunk(content="Je n'ai pas de données.", finish_reason="stop")],
            ]
        )
        await collecter(
            moteur, [Recherche("web_search"), lecture], "Quel temps fait-il ce soir ?"
        )
        assert lecture.executions == [], "on ne devine pas une ville (§34)"
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("météo Tombouctou")])],
                [StreamChunk(content="Je n'ai pas de données.", finish_reason="stop")],
            ]
        )
        await collecter(
            moteur,
            [Recherche("web_search"), lecture],
            "Quel temps fait-il ce soir à Tombouctou ?",
            ville="Ottawa",
        )
        assert lecture.executions == [], (
            "une ville hors de la table n'a pas de page officielle : la config "
            "ne prend pas sa place"
        )


class TestDemainEtLeFutur:
    """Essai du 21/09 : « Va-t-il pleuvoir demain à Montréal ? » passait sans
    consigne ni page officielle — « demain » n'était pas un marqueur, et
    « va-t-il » pas une forme de question de fait."""

    @pytest.mark.parametrize(
        "question",
        [
            "Va-t-il pleuvoir demain à Montréal ?",
            "Est-ce qu'il va neiger demain ?",
            "Y aura-t-il du soleil ce week-end ?",
            "Quel temps fera-t-il demain ?",
            "Will it rain tomorrow in Ottawa?",
        ],
    )
    def test_le_futur_proche_est_une_question_d_actualite(self, question):
        from diapason.server.actualite import (
            parametres_de_recherche,
            question_d_actualite,
        )

        assert question_d_actualite(question), question
        assert parametres_de_recherche(question)["recency"] == "week", (
            "demain se périme en jours"
        )

    def test_une_production_pour_demain_reste_de_tete(self):
        from diapason.server.actualite import question_d_actualite

        assert not question_d_actualite("Écris un poème pour demain")

    def test_une_valeur_a_decimales_se_retrouve_sans_son_unite(self):
        """« 2,25 % » signalé hors sources quand la table de la Banque du
        Canada écrit « 2,25 » dans une colonne de taux (essai du 21/09)."""
        from diapason.server.actualite import elements_hors_sources

        table = (
            "[1] Taux — banqueducanada.ca\nDate | Taux cible\n"
            "2 septembre 2026 | 2,25 | ---"
        )
        assert elements_hors_sources("Le taux est de 2,25 % [1].", table, "") == []
        assert elements_hors_sources(
            "Le taux est de 5 % [1].", "[1] x\n2026 | 5 | ---", ""
        ) == ["5 %"], (
            "un chiffre seul n'est pas assez précis pour valoir sans son unité"
        )


class TestLaPageDuPosteEstUnePageDeReference:
    def test_un_article_de_presse_n_est_pas_la_page_du_poste(self):
        """Essai du 21/09 : « Le premier ministre Carney rencontre… » d'un
        journal était lu comme la page du poste."""
        from diapason.server.actualite import page_de_reference

        sources = [
            {
                "ref": 1,
                "title": (
                    "Le premier ministre Carney rencontre le premier ministre du Québec"
                ),
                "url": "https://www.lesaffaires.com/x",
            },
            {
                "ref": 2,
                "title": (
                    "Mark Carney - Premier ministre du Canada | "
                    "Premier ministre du Canada"
                ),
                "url": "https://www.pm.gc.ca/fr/premier-ministre",
            },
        ]
        assert page_de_reference(sources, PREMIER_MINISTRE) == (
            "https://www.pm.gc.ca/fr/premier-ministre"
        ), "un site de référence qui porte la fonction, avant un journal"
        assert page_de_reference(sources[:1], PREMIER_MINISTRE) == "", (
            "sans page de référence, rien : la presse n'est pas la page du poste"
        )


class TestLaNonReponse:
    """Banc du 21/09 : « Les résultats ne mentionnent pas le vainqueur de la
    Coupe Stanley 2026 … il faudrait attendre » sous un badge vert, avec
    trois [N] ; « Je vais relancer la recherche » — puis rien."""

    @pytest.mark.parametrize(
        "texte",
        [
            "Les résultats de la recherche ne mentionnent pas le vainqueur [1][4].",
            "Je n'ai pas trouvé le chiffre exact dans les sources [2].",
            "Aucune source ne donne le taux pour septembre [1].",
            "Je vais relancer la recherche avec une requête ciblée.",
            "The results do not mention the winner [1].",
        ],
    )
    def test_ce_qui_est_une_non_reponse(self, texte):
        from diapason.server.actualite import (
            est_une_non_reponse,
            niveau_de_verification,
        )

        assert est_une_non_reponse(texte)
        assert niveau_de_verification(
            texte, [{"ref": 1}, {"ref": 2}, {"ref": 4}], True
        ) == ("partial"), (
            "une réponse qui dit n'avoir pas trouvé n'est pas vérifiée, même citée"
        )

    def test_une_reponse_qui_repond_n_en_est_pas_une(self):
        from diapason.server.actualite import est_une_non_reponse

        assert not est_une_non_reponse("Les Panthers de la Floride ont gagné [1].")
        assert not est_une_non_reponse("Mark Carney [2], depuis le 14 mars 2025.")

    @pytest.mark.asyncio
    async def test_une_seconde_recherche_avec_une_autre_requete_une_fois(self):
        from diapason.server.actualite import CONSIGNE_AUTRE_REQUETE

        liste = [Recherche("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("gagnant Coupe Stanley 2026")])],
                [
                    StreamChunk(
                        content="Les résultats ne mentionnent pas le vainqueur [1].",
                        finish_reason="stop",
                    )
                ],
                [
                    StreamChunk(
                        tool_calls=[appel_web("Stanley Cup 2026 champion", "w2")]
                    )
                ],
                [
                    StreamChunk(
                        content=(
                            "Les résultats ne mentionnent toujours pas "
                            "le vainqueur [2]."
                        ),
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(moteur, liste, "Qui a gagné la Coupe Stanley en 2026 ?")
        assert [p.get("query") for p in liste[0].executions] == [
            "gagnant Coupe Stanley 2026",
            "Stanley Cup 2026 champion",
        ], "une seconde recherche, avec une autre requête"
        relance = [m.content for m in moteur.appels[2][0] if m.role == Role.SYSTEM]
        assert CONSIGNE_AUTRE_REQUETE in relance
        assert moteur.appels[2][0][-2].role == Role.ASSISTANT, (
            "ce qui est déjà affiché reste dans le fil"
        )
        assert len(moteur.appels) == 4, "une seule relance, jamais une boucle"
        assert texte(evts) == (
            "Les résultats ne mentionnent pas le vainqueur [1].\n\n"
            "Les résultats ne mentionnent toujours pas le vainqueur [2]."
        )
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "partial", "searchTried": True}
        ], "deux aveux, pas de vérification"


class TestLaPageDuPosteRefuseLaPresse:
    def test_un_titre_qui_commence_par_la_fonction_ne_suffit_pas(self):
        """Banc du 21/09 : « Pape à Paris : où voir Léon XIV… » (sortiraparis)
        était lu comme la page du poste."""
        from diapason.server.actualite import page_de_reference

        sources = [
            {
                "ref": 3,
                "title": "Pape à Paris : où voir Léon XIV en papamobile",
                "url": "https://www.sortiraparis.com/x",
            }
        ]
        assert page_de_reference(sources, "Qui est le pape ?") == ""
        sources.append(
            {
                "ref": 4,
                "title": "Pape — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/Pape",
            }
        )
        assert page_de_reference(sources, "Qui est le pape ?").endswith("/wiki/Pape")


class TestLaNonReponseSeJugeSurLeDernierPassage:
    @pytest.mark.asyncio
    async def test_je_dois_lire_la_page_puis_le_chiffre_est_une_reponse(self):
        """Banc du 21/09 : « les extraits ne donnent pas le chiffre exact. Je
        dois lire la page… » puis « 3,0 % en août 2026 [10] » — partiel, alors
        que la bulle finit par répondre."""
        liste = [Recherche("web_search")]
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("inflation Canada 2026")])],
                [
                    StreamChunk(
                        content="Les extraits ne donnent pas le chiffre exact [1]."
                    ),
                    StreamChunk(
                        tool_calls=[appel_web("inflation Canada août 2026", "w2")]
                    ),
                ],
                [
                    StreamChunk(
                        content="Le taux d'inflation était de 3,0 % en août 2026 [2].",
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(
            moteur, liste, "Quel est le taux d'inflation au Canada ?"
        )
        signal = [e.data for e in evts if e.kind == "verification"]
        assert signal and signal[0]["level"] != "memory"
        assert signal[0].get("notFound") == ["3,0 %"], (
            "le chiffre n'est pas dans les sources factices : signalé"
        )
        assert signal[0]["level"] == "partial", (
            "signalé, donc partiel — pas la non-réponse"
        )
        # Sans l'élément hors sources, la bulle vaut vérifiée : le dernier
        # passage répond.
        from diapason.server.actualite import niveau_de_verification

        assert (
            niveau_de_verification(
                texte(evts),
                [{"ref": 1}, {"ref": 2}],
                True,
                {},
                dernier_passage="Le taux d'inflation était de 3,0 % en août 2026 [2].",
            )
            == "verified"
        )
        assert (
            niveau_de_verification(
                texte(evts),
                [{"ref": 1}, {"ref": 2}],
                True,
                {},
                dernier_passage="Les extraits ne donnent toujours pas le chiffre [2].",
            )
            == "partial"
        )


class TestLaSourceLaPlusPrometteuse:
    """Banc du 21/09 : nhl.com « 2026 Stanley Cup Final » était dans les
    résultats et le 9b n'y allait pas."""

    SOURCES = [
        {
            "ref": 1,
            "title": "Le Devoir : contrats prolongés",
            "url": "https://ledevoir.com/a",
            "date": "2026-09-19",
        },
        {
            "ref": 2,
            "title": "Coupe Stanley 2025 : les Panthers",
            "url": "https://journaldequebec.com/b",
            "date": "2025-10-12",
        },
        {
            "ref": 3,
            "title": "2026 Stanley Cup Final: Game 6 recap",
            "url": "https://www.nhl.com/news/x",
            "date": "2026-06-20",
        },
        {
            "ref": 4,
            "title": "Finale de la Coupe Stanley 2026 — Wikipédia",
            "url": "https://fr.wikipedia.org/wiki/Finale_2026",
            "date": "",
        },
    ]

    def test_le_titre_qui_reprend_la_question_de_reference_de_preference(self):
        from diapason.server.actualite import source_la_plus_prometteuse

        choisie = source_la_plus_prometteuse(
            self.SOURCES, "Qui a gagné la Coupe Stanley en 2026 ?"
        )
        assert choisie is not None and choisie["ref"] == 4, (
            "coupe, stanley, 2026 (double) + référence : Wikipédia avant nhl.com"
        )
        sans_wiki = source_la_plus_prometteuse(
            self.SOURCES[:3], "Qui a gagné la Coupe Stanley en 2026 ?"
        )
        assert sans_wiki is not None and sans_wiki["ref"] == 3, (
            "stanley + 2026 : nhl.com"
        )

    def test_une_page_deja_lue_ne_compte_plus_et_sans_mot_commun_rien(self):
        from diapason.server.actualite import source_la_plus_prometteuse

        choisie = source_la_plus_prometteuse(
            self.SOURCES,
            "Qui a gagné la Coupe Stanley en 2026 ?",
            deja_lues=["https://fr.wikipedia.org/wiki/Finale_2026"],
        )
        assert choisie is not None and choisie["ref"] == 3
        assert (
            source_la_plus_prometteuse(self.SOURCES, "Quel est le taux directeur ?")
            is None
        ), "aucun mot de la question dans les titres : on ne lit pas au hasard"
        assert source_la_plus_prometteuse([], "Coupe Stanley 2026") is None

    @pytest.mark.asyncio
    async def test_sur_une_non_reponse_le_code_lit_la_source_puis_le_modele_repond(
        self,
    ):
        from diapason.server.actualite import CONSIGNE_PAGE_LUE

        class RechercheHockey(Outil):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_search",
                    content=(
                        "[1] Le Devoir : contrats prolongés — ledevoir.com"
                        " · 2026-09-19\n"
                        "Source: https://ledevoir.com/a\nExtrait: …\n\n"
                        "[2] 2026 Stanley Cup Final: Game 6 recap — nhl.com"
                        " · 2026-06-20\n"
                        "Source: https://www.nhl.com/news/x\nExtrait: …"
                    ),
                    success=True,
                    metadata={
                        "sources": [
                            {
                                "ref": 1,
                                "title": "Le Devoir : contrats prolongés",
                                "url": "https://ledevoir.com/a",
                                "date": "2026-09-19",
                            },
                            {
                                "ref": 2,
                                "title": "2026 Stanley Cup Final: Game 6 recap",
                                "url": "https://www.nhl.com/news/x",
                                "date": "2026-06-20",
                            },
                        ]
                    },
                )

        class LectureNhl(Lecture):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_read",
                    content=(
                        "[1] 2026 Stanley Cup Final: Game 6 recap — nhl.com"
                        " · publié 2026-06-20\n"
                        f"Source: {params['url']}\n"
                        "Début : The Florida Panthers won the 2026 Stanley Cup, "
                        "beating Edmonton in six games.\n"
                    ),
                    success=True,
                    metadata={
                        "url": params["url"],
                        "sources": [
                            {
                                "ref": 1,
                                "title": "2026 Stanley Cup Final",
                                "url": params["url"],
                                "date": "2026-06-20",
                            }
                        ],
                    },
                )

        lecture = LectureNhl()
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("gagnant Coupe Stanley 2026")])],
                [
                    StreamChunk(
                        content="Les résultats ne mentionnent pas le vainqueur [1].",
                        finish_reason="stop",
                    )
                ],
                [
                    StreamChunk(
                        content=(
                            "Les Panthers de la Floride ont gagné la Coupe "
                            "Stanley 2026 [2]."
                        ),
                        finish_reason="stop",
                    )
                ],
            ]
        )
        evts = await collecter(
            moteur,
            [RechercheHockey("web_search"), lecture],
            "Qui a gagné la Coupe Stanley en 2026 ?",
        )
        assert lecture.executions == [
            {
                "url": "https://www.nhl.com/news/x",
                "focus": "Qui a gagné la Coupe Stanley en 2026 ?",
            }
        ], "la source la plus prometteuse est lue par le code, pas par le modèle"
        debuts = [
            d
            for d in (e.data for e in evts if e.kind == "tool_start")
            if d["tool"] == "web_read"
        ]
        assert debuts and debuts[0]["auto"] is True
        troisieme = moteur.appels[2][0]
        outil = next(
            m for m in troisieme if m.role == Role.TOOL and m.name == "web_search"
        )
        assert "Page lue" not in (outil.content or ""), (
            "le résultat déjà envoyé n'est pas modifié : le préfixe en cache survit"
        )
        assert troisieme[-1].role == Role.SYSTEM
        assert troisieme[-1].content.startswith(
            "Page lue (web_read) :\n[2] 2026 Stanley Cup Final"
        ), "la page suit l'aveu, sous son numéro [2]"
        assert "Florida Panthers won the 2026 Stanley Cup" in troisieme[-1].content
        assert troisieme[-1].content.endswith(CONSIGNE_PAGE_LUE.format(ref=2))
        assert texte(evts) == (
            "Les résultats ne mentionnent pas le vainqueur [1].\n\n"
            "Les Panthers de la Floride ont gagné la Coupe Stanley 2026 [2]."
        )
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "verified", "searchTried": True}
        ], "le dernier passage répond, cité : vérifié"
        assert len(moteur.appels) == 3, "une lecture, une reprise, pas de boucle"


class TestDeuxEssaisDeLecture:
    @pytest.mark.asyncio
    async def test_la_premiere_page_refuse_la_seconde_lit(self):
        """Essai du 21/09 : Le Devoir (frais, « Coupe Stanley cette année »)
        refusait la lecture, nhl.com juste derrière lisait — et le code
        renvoyait déjà le modèle chercher autrement."""

        class Recherche2(Outil):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_search",
                    content=(
                        "[1] Coupe Stanley 2026 : le bilan — ledevoir.com"
                        " · 2026-09-19\n"
                        "Source: https://ledevoir.com/a\nExtrait: …\n\n"
                        "[2] 2026 Stanley Cup Final — nhl.com · 2026-06-20\n"
                        "Source: https://www.nhl.com/news/x\nExtrait: …"
                    ),
                    success=True,
                    metadata={
                        "sources": [
                            {
                                "ref": 1,
                                "title": "Coupe Stanley 2026 : le bilan",
                                "url": "https://ledevoir.com/a",
                                "date": "2026-09-19",
                            },
                            {
                                "ref": 2,
                                "title": "2026 Stanley Cup Final",
                                "url": "https://www.nhl.com/news/x",
                                "date": "2026-06-20",
                            },
                        ]
                    },
                )

        class LectureCapricieuse(Lecture):
            def execute(self, **params):
                self.executions.append(params)
                if "ledevoir" in params["url"]:
                    return ToolResult(
                        tool_name="web_read",
                        content="Lecture impossible : HTTP 403",
                        success=False,
                    )
                return ToolResult(
                    tool_name="web_read",
                    content=(
                        "[1] 2026 Stanley Cup Final — nhl.com\n"
                        f"Source: {params['url']}\n"
                        "Début : The Florida Panthers won the 2026 Stanley Cup.\n"
                    ),
                    success=True,
                    metadata={
                        "sources": [
                            {
                                "ref": 1,
                                "title": "2026 Stanley Cup Final",
                                "url": params["url"],
                            }
                        ]
                    },
                )

        lecture = LectureCapricieuse()
        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("gagnant Coupe Stanley 2026")])],
                [
                    StreamChunk(
                        content="Les résultats ne confirment pas le vainqueur [1].",
                        finish_reason="stop",
                    )
                ],
                [
                    StreamChunk(
                        content="Les Panthers ont gagné [2].", finish_reason="stop"
                    )
                ],
            ]
        )
        evts = await collecter(
            moteur,
            [Recherche2("web_search"), lecture],
            "Qui a gagné la Coupe Stanley en 2026 ?",
        )
        assert [p["url"] for p in lecture.executions] == [
            "https://ledevoir.com/a",
            "https://www.nhl.com/news/x",
        ], "la plus prometteuse d'abord (trois points), puis la suivante"
        fins = [
            d
            for d in (e.data for e in evts if e.kind == "tool_end")
            if d["tool"] == "web_read"
        ]
        assert [f["success"] for f in fins] == [False, True]
        troisieme = moteur.appels[2][0]
        assert troisieme[-1].role == Role.SYSTEM
        assert "Florida Panthers won" in troisieme[-1].content
        assert texte(evts).endswith("Les Panthers ont gagné [2].")
        assert [e.data for e in evts if e.kind == "verification"] == [
            {"level": "verified", "searchTried": True}
        ]


class TestCeQueLaRevueDuSoirAFaitCorriger:
    """Revue du 21/09 sur la lecture après non-réponse."""

    def test_une_question_sans_mot_de_quatre_lettres_ne_plante_pas(self):
        """sources_prometteuses rendait None au lieu d'une liste : le flux
        mourait d'un TypeError après avoir affiché l'aveu."""
        from diapason.server.actualite import sources_prometteuses

        assert (
            sources_prometteuses(
                [{"ref": 1, "title": "x", "url": "https://a"}], "Qui est le roi ?"
            )
            == []
        )

    def test_une_vraie_reponse_avec_une_reserve_n_est_pas_relancee(self):
        from diapason.server.actualite import (
            est_une_non_reponse,
            niveau_de_verification,
        )

        reponse = (
            "Les Hurricanes ont gagné [7], mais les sources ne précisent pas le score."
        )
        assert not est_une_non_reponse(reponse)
        assert niveau_de_verification(reponse, [{"ref": 7}], True, {}) == "verified"

    def test_le_singulier_et_le_numero_entre_sujet_et_verbe(self):
        from diapason.server.actualite import est_une_non_reponse

        for texte in (
            "La source [2] ne mentionne pas le vainqueur.",
            "L'article n'indique pas la date.",
            "Aucun des articles ne mentionne le score.",
            "Il semble que les finales n'aient pas encore eu lieu.",
        ):
            assert est_une_non_reponse(texte), texte

    def test_la_reprise_doit_citer_pour_etre_verifiee(self):
        from diapason.server.actualite import niveau_de_verification

        tout = "Je n'ai pas trouvé [1].\n\nLes Hurricanes ont gagné."
        assert niveau_de_verification(
            tout, [{"ref": 1}], True, {}, "Les Hurricanes ont gagné."
        ) == ("partial"), "le [1] de l'aveu ne couvre pas la reprise sans citation"

    def test_sans_annee_dans_la_question_l_annee_en_cours_est_implicite(self):
        from datetime import date

        from diapason.server.actualite import sources_prometteuses

        annee = date.today().year
        sources = [
            {
                "ref": 1,
                "title": f"Coupe Stanley {annee - 1} : le bilan",
                "url": "https://a.ca/x",
            },
            {"ref": 2, "title": f"Coupe Stanley {annee}", "url": "https://b.ca/y"},
            {
                "ref": 3,
                "title": f"Coupe Stanley {annee - 2} : les Panthers",
                "url": "https://c.ca/z",
            },
        ]
        assert [
            s["ref"]
            for s in sources_prometteuses(sources, "Qui a gagné la Coupe Stanley ?")
        ] == [2, 1], (
            "l'année en cours d'abord ; l'année passée reste candidate (en janvier "
            "c'est encore la dernière édition, revue du 21/09) ; celle d'avant tombe"
        )

    def test_un_mot_qui_se_traduit_par_lui_meme_ne_compte_qu_une_fois(self):
        """« président » → (« president »,) : le même jeton du titre comptait
        pour le mot ET pour sa traduction, et « Le président Macron en visite »
        franchissait le seuil sous « Qui est le président du Sénat ? »."""
        from diapason.server.actualite import sources_prometteuses

        sources = [
            {
                "ref": 1,
                "title": "Le président Macron en visite",
                "url": "https://a.fr/x",
            },
            {
                "ref": 2,
                "title": "Président du Sénat : élection",
                "url": "https://b.fr/y",
            },
        ]
        assert [
            s["ref"]
            for s in sources_prometteuses(sources, "Qui est le président du Sénat ?")
        ] == [2]

    def test_une_date_qui_n_est_pas_iso_ne_vaut_pas_fraicheur(self):
        from datetime import date

        from diapason.server.actualite import sources_prometteuses

        aujourd_hui = date.today().isoformat()
        sources = [
            {
                "ref": 1,
                "title": "Coupe Stanley 2026",
                "url": "https://a.ca/x",
                "date": "il y a 3 h",
            },
            {
                "ref": 2,
                "title": "Coupe Stanley 2026",
                "url": "https://b.ca/y",
                "date": aujourd_hui,
            },
        ]
        assert [
            s["ref"] for s in sources_prometteuses(sources, "Coupe Stanley 2026 ?")
        ] == [2, 1]

    def test_le_lexique_traverse_la_langue_et_un_seul_mot_ne_suffit_pas(self):
        from diapason.server.actualite import sources_prometteuses

        sources = [
            {"ref": 1, "title": "Canada Day celebrations", "url": "https://a.ca/x"},
            {
                "ref": 2,
                "title": "Mark Carney sworn in as Prime Minister",
                "url": "https://b.ca/y",
            },
        ]
        assert [s["ref"] for s in sources_prometteuses(sources, PREMIER_MINISTRE)] == [
            2
        ]

    def test_les_mots_entiers_seulement(self):
        from diapason.server.actualite import sources_prometteuses

        sources = [
            {
                "ref": 1,
                "title": "Printemps 2026 : procès-verbal",
                "url": "https://a.ca/x",
            },
            {
                "ref": 2,
                "title": "Quel temps fera-t-il ce soir à Ottawa",
                "url": "https://b.ca/y",
            },
        ]
        assert [
            s["ref"]
            for s in sources_prometteuses(sources, "Quel temps fera-t-il ce soir ?")
        ] == [2]

    @pytest.mark.asyncio
    async def test_sans_tour_d_outil_restant_la_page_lue_ne_promet_pas_de_recherche(
        self,
    ):
        """Le modèle a brûlé ses tours d'outil et avoue : la lecture par le
        code reste possible (elle ne coûte aucun tour), mais la consigne ne
        promet plus de recherche — le passage suivant est sans outils."""
        from diapason.server.actualite import CONSIGNE_PAGE_LUE_SANS_OUTIL

        class Recherche2(Outil):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_search",
                    content=(
                        "[1] 2026 Stanley Cup Final — nhl.com · 2026-06-20\n"
                        "Source: https://www.nhl.com/news/x\nExtrait: …"
                    ),
                    success=True,
                    metadata={
                        "sources": [
                            {
                                "ref": 1,
                                "title": "2026 Stanley Cup Final",
                                "url": "https://www.nhl.com/news/x",
                                "date": "2026-06-20",
                            }
                        ]
                    },
                )

        class LectureNhl(Lecture):
            def execute(self, **params):
                self.executions.append(params)
                return ToolResult(
                    tool_name="web_read",
                    content=(
                        "[1] 2026 Stanley Cup Final — nhl.com\n"
                        f"Source: {params['url']}\nDébut : The Hurricanes won.\n"
                    ),
                    success=True,
                    metadata={"sources": [{"ref": 1, "url": params["url"]}]},
                )

        moteur = Moteur(
            [
                [StreamChunk(tool_calls=[appel_web("gagnant Coupe Stanley 2026")])],
                [
                    StreamChunk(
                        content="Je n'ai pas trouvé le vainqueur [1].",
                        finish_reason="stop",
                    )
                ],
                [
                    StreamChunk(
                        content="Les Hurricanes ont gagné [1].", finish_reason="stop"
                    )
                ],
            ]
        )
        evts = await collecter(
            moteur,
            [Recherche2("web_search"), LectureNhl()],
            "Qui a gagné la Coupe Stanley en 2026 ?",
            max_tool_turns=1,
        )
        assert moteur.appels[2][0][-1].content.endswith(
            CONSIGNE_PAGE_LUE_SANS_OUTIL.format(ref=1)
        ), "le passage suivant est sans outils : la consigne n'annonce aucune recherche"
        assert moteur.appels[2][1].get("tools") is None or not moteur.appels[2][1].get(
            "tools"
        )
        assert texte(evts).endswith("Les Hurricanes ont gagné [1].")


class TestLAveuQuiPorteSurLaQuestion:
    """Banc du 21/09 à 22 h : « Quel a été le score du dernier match … ? » →
    « … victoire … par 4 matchs à 2 [6]. Le score exact … n'est pas spécifié
    dans les résultats trouvés. » — badge vert, et en.wikipedia « 2026
    Stanley Cup Final » dans les résultats, jamais lue."""

    SCORE = (
        "Quel a été le score du dernier match de la finale de la Coupe Stanley 2026 ?"
    )
    REPONSE = (
        "Le dernier match de la finale de la Coupe Stanley 2026 s'est terminé le "
        "14 juin 2026, avec une victoire des Carolina Hurricanes par 4 matchs à 2 "
        "[6]. Le score exact du septième et dernier match n'est pas spécifié dans "
        "les résultats trouvés."
    )

    def test_l_aveu_sur_le_fait_demande_est_une_non_reponse_malgre_la_citation(self):
        from diapason.server.actualite import est_une_non_reponse

        assert est_une_non_reponse(self.REPONSE, question=self.SCORE), (
            "« score » est dans la question et dans l'aveu, pas dans la phrase citée"
        )

    def test_sans_la_question_la_citation_suffit(self):
        from diapason.server.actualite import est_une_non_reponse

        assert not est_une_non_reponse(self.REPONSE)

    def test_le_badge_devient_partiel(self):
        from diapason.server.actualite import niveau_de_verification

        assert (
            niveau_de_verification(
                self.REPONSE, [{"ref": 6}], True, {}, None, self.SCORE
            )
            == "partial"
        )

    def test_une_reserve_sur_autre_chose_reste_une_reponse(self):
        from diapason.server.actualite import est_une_non_reponse

        for reponse in (
            "Les Hurricanes ont gagné la Coupe Stanley [7], mais les sources ne "
            "précisent pas le score de la finale de la Coupe Stanley.",
            "Les Hurricanes ont gagné [7] ; les sources ne précisent pas le score.",
        ):
            assert not est_une_non_reponse(
                reponse, question="Qui a gagné la Coupe Stanley en 2026 ?"
            ), reponse

    def test_le_mot_repris_dans_la_phrase_citee_ne_compte_pas(self):
        """« premier ministre » est dans la question, dans l'aveu ET dans la
        phrase citée : seul « Canada », absent de la phrase citée, tranche."""
        from diapason.server.actualite import est_une_non_reponse

        question = "Qui est le premier ministre du Canada ?"
        assert not est_une_non_reponse(
            "Mark Carney est premier ministre depuis mars 2025 [2]. Les sources ne "
            "précisent pas la date exacte de son assermentation.",
            question=question,
        )
        assert est_une_non_reponse(
            "Les sources parlent du premier ministre du Québec [2]. Le premier "
            "ministre du Canada n'est pas nommé dans les résultats.",
            question=question,
        )


class TestLaPromesseEnDerniereLigne:
    """Banc du 21/09 à 22 h : « Le but gagnant a été marqué par Hertl … [4].
    Cependant, il semble que ce soit un résumé partiel … je vais lire
    l'article complet. » — et rien ne le lit : la promesse sans l'acte."""

    def test_je_vais_lire_en_fin_de_reponse_declenche_la_lecture(self):
        from diapason.server.actualite import est_une_non_reponse

        reponse = (
            "Le but gagnant a été marqué par Hertl à 16:36 du match numéro 1 [4]. "
            "Pour obtenir une information plus précise sur le but gagnant de la "
            "finale, je vais lire l'article complet."
        )
        assert est_une_non_reponse(reponse, question="Qui a marqué le but gagnant ?")
        assert est_une_non_reponse(reponse), "la promesse compte même sans la question"

    def test_la_promesse_au_milieu_suivie_du_chiffre_est_une_reponse(self):
        """Banc du 21/09 : « je dois affiner ma recherche : … Selon [10],
        l'inflation se maintient à 3 % » — la suite a tenu la promesse."""
        from diapason.server.actualite import est_une_non_reponse

        assert not est_une_non_reponse(
            "Les résultats parlent du taux directeur (2,25 %) [3]. Pour trouver le "
            "taux d'inflation, je dois affiner ma recherche :\n\nSelon [10], "
            "l'inflation se maintient à 3 % en septembre 2026.",
            question="Quel est le taux d'inflation au Canada ?",
        )

    def test_les_formes_de_la_promesse(self):
        from diapason.server.actualite import est_une_non_reponse

        for fin in (
            "Je vais vérifier si d'autres sources confirment.",
            "Je dois donc relancer la recherche.",
            "Laissez-moi consulter la page officielle.",
            "Let me check the official page.",
        ):
            assert est_une_non_reponse(f"Les Hurricanes ont gagné [7]. {fin}"), fin

    def test_a_l_oral_aussi(self):
        from diapason.server.actualite import est_une_non_reponse

        assert est_une_non_reponse(
            "Les Hurricanes ont gagné. Je vais lire l'article complet.", orale=True
        )
