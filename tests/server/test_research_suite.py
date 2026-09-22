"""La recherche approfondie reçoit les tours d'avant, les indices et le web.

22/09/2026 : « Fais-moi une recherche [sur] des sites web qui proposent des
jeux de programmation » sous la recherche approfondie recevait « votre corpus
personnel n'a rien », puis une liste de mémoire (« Sweatco », Codewars deux
fois) ; « Donne-moi les liens de ces sites web » partait seul et rendait les
liens des courriels (Banque Nationale, Mobbin…).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from diapason.core.types import Role
from diapason.server.research_router import (
    CONSIGNE_WEB,
    EXTRAIT_DE_PAGE,
    HISTORY_CHARS,
    HISTORY_TURNS,
    HistoryMessage,
    ResearchRequest,
    _extraits_par_numero,
    _hints,
    _history_messages,
    _web_searcher,
)
from diapason.tools._stubs import ToolResult

SITES = "Fait moi un recherche en des site web qui propose des jeux de programmation"
LIENS = "Donne moi les lien de ces sites web"
REPONSE = "CodinGame, HackerRank, LeetCode, Exercism, Codewars."


class TestLaRequete:
    def test_l_historique_est_facultatif_et_en_camelcase_anglais(self):
        assert ResearchRequest(query="q").history == []
        req = ResearchRequest(query=LIENS, history=[{"role": "user", "content": SITES}])
        assert req.history[0].role == "user"


class TestLesToursDAvant:
    def test_les_six_derniers_tours_user_assistant_non_vides(self):
        tours = [HistoryMessage(role="system", content="x")]
        for i in range(10):
            tours.append(
                HistoryMessage(
                    role="user" if i % 2 == 0 else "assistant", content=f"m{i}"
                )
            )
        tours.append(HistoryMessage(role="assistant", content="   "))
        messages = _history_messages(tours)
        assert len(messages) == HISTORY_TURNS
        assert [m.content for m in messages] == ["m4", "m5", "m6", "m7", "m8", "m9"], (
            "le vide et le système sont écartés avant la coupe"
        )
        assert messages[0].role == Role.USER

    def test_un_tour_trop_long_est_coupe(self):
        long = "mot " * 1000
        (m,) = _history_messages([HistoryMessage(role="user", content=long)])
        assert len(m.content) <= HISTORY_CHARS + 1 and m.content.endswith("…")


class TestLesIndices:
    def test_ces_sites_recoit_le_rappel_et_la_consigne_web(self):
        indices = _hints(
            LIENS,
            [
                HistoryMessage(role="user", content=SITES),
                HistoryMessage(role="assistant", content=REPONSE),
            ],
        )
        assert len(indices) == 2
        assert indices[0].startswith(
            "La demande renvoie à ce qui précède (« ces sites »)"
        )
        assert "CodinGame" in indices[0], "le référent est dans la réponse citée"
        assert indices[1] == CONSIGNE_WEB

    @pytest.mark.parametrize(
        "question",
        [
            "Quelles réunions avec Alice la semaine passée ?",
            "Quels sont les liens entre Alice et Bob dans mes courriels ?",
            "Prends ça en ligne de compte",
            "Cherche mes fichiers sur Google Drive",
            "Quelle URL de réunion Alice m'a envoyée ?",
        ],
    )
    def test_une_question_sur_le_corpus_n_a_aucun_indice(self, question):
        """Revue du 22/09 : « les liens », « en ligne », « sur Google », « URL »
        nus posaient la consigne web sur des questions du corpus."""
        assert _hints(question, []) == []

    @pytest.mark.parametrize(
        "question",
        [
            "Fais une recherche web sur les jeux de programmation",
            "Trouve des sites internet de jeux",
            "Cherche sur le net des jeux",
            "Cherche en ligne des jeux de programmation",
            "Envoie-moi les liens",
        ],
    )
    def test_ce_qui_nomme_le_web(self, question):
        assert _hints(question, []) == [CONSIGNE_WEB]

    def test_sites_web_sans_tour_d_avant_n_a_que_la_consigne_web(self):
        assert _hints(SITES, []) == [CONSIGNE_WEB]


class TestLeChercheurWeb:
    def test_les_resultats_de_web_search_deviennent_des_pages(self):
        resultat = ToolResult(
            tool_name="web_search",
            content=(
                "[1] CodinGame — codingame.com · 2026-09-01\n"
                "Source: https://www.codingame.com/\nExtrait: Learn by\nplaying.\n\n"
                "[2] Codewars — codewars.com\nSource: https://www.codewars.com/\n"
                "Extrait: Kata."
            ),
            success=True,
            metadata={
                "sources": [
                    {
                        "ref": 1,
                        "title": "CodinGame",
                        "url": "https://www.codingame.com/",
                        "date": "2026-09-01",
                        "sender": "codingame.com",
                    },
                    {
                        "ref": 2,
                        "title": "Codewars",
                        "url": "https://www.codewars.com/",
                        "date": "",
                        "sender": "codewars.com",
                    },
                ]
            },
        )
        with patch("diapason.tools.web_search.WebSearchTool.execute") as execute:
            execute.return_value = resultat
            chercher = _web_searcher()
            assert chercher is not None
            pages = chercher("programming games", "year", False)
        assert execute.call_args.kwargs == {
            "query": "programming games",
            "news": False,
            "recency": "year",
        }
        assert [(p.title, p.url, p.site, p.date, p.snippet) for p in pages] == [
            (
                "CodinGame",
                "https://www.codingame.com/",
                "codingame.com",
                "2026-09-01",
                "Learn by playing.",
            ),
            ("Codewars", "https://www.codewars.com/", "codewars.com", "", "Kata."),
        ]

    def test_une_panne_remonte_au_lieu_de_devenir_zero_resultat(self):
        """Revue du 22/09 : « Search error: aucun moteur n'a répondu » devenait
        [] — identique à un vide — et le modèle disait « rien sur le web »."""
        with patch("diapason.tools.web_search.WebSearchTool.execute") as execute:
            execute.return_value = ToolResult(
                tool_name="web_search",
                content="Search error: aucun moteur n'a répondu (réseau ?).",
                success=False,
            )
            with pytest.raises(RuntimeError, match="aucun moteur"):
                _web_searcher()("x", None, True)

    def test_une_url_dans_la_requete_rend_le_debut_de_la_page_en_extrait(self):
        """Revue du 22/09 : web_search lit la page (mode fetch, pas de ligne
        « Extrait: ») et l'agent recevait un résultat sans un mot de contenu."""
        with patch("diapason.tools.web_search.WebSearchTool.execute") as execute:
            execute.return_value = ToolResult(
                tool_name="web_search",
                content=(
                    "[1] CodinGame — codingame.com\nSource: https://www.codingame.com/\n"
                    "Début : Learn to code by playing games. " + "Texte " * 400
                ),
                success=True,
                metadata={
                    "mode": "fetch",
                    "sources": [
                        {
                            "ref": 1,
                            "title": "CodinGame",
                            "url": "https://www.codingame.com/",
                        }
                    ],
                },
            )
            (page,) = _web_searcher()("https://www.codingame.com/ jeux", None, False)
        assert page.snippet.startswith("Début : Learn to code by playing games.")
        assert len(page.snippet) <= EXTRAIT_DE_PAGE + 1 and page.snippet.endswith("…")

    def test_les_extraits_par_numero(self):
        assert _extraits_par_numero("") == {}
        assert _extraits_par_numero("[3] T — s\nSource: u\nExtrait: a\nb") == {3: "a b"}
