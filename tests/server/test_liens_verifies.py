"""§100 — les liens et la destination d'une action ont une preuve réelle."""

import pytest

from diapason.core.types import Message, Role, ToolResult
from diapason.engine._stubs import StreamChunk
from diapason.server.agentic_stream import stream_with_tools
from diapason.server.liens_verifies import (
    adresses,
    demande_de_liens,
    erreur_destination,
    liens_sans_preuve,
    page_a_verifier,
    repli_liens,
)
from tests.server.test_agentic_stream import MoteurFactice, OutilFactice, _appel


def test_le_repli_retient_la_page_recue_du_domaine_demande():
    sources = [
        "https://example.org/article-code.org",
        "https://Code.org/en-US",
        "https://Code.org",
    ]
    reponse = repli_liens(sources, "Vérifie Code.org et donne son adresse exacte")
    assert reponse == "Adresse reçue pour le site demandé : https://Code.org/en-US", (
        "la redirection réellement reçue suffit, sans noyer le lien parmi les tiers"
    )
    assert "pertinence reste à confirmer" in repli_liens(
        sources[:1], "Vérifie Code.org et donne son adresse exacte"
    ), "la mention d'un domaine dans le chemin d'un site tiers n'est pas sa page"


@pytest.mark.parametrize(
    "texte",
    [
        "Explique le lien social",
        "Crée un lien entre mes tâches",
        "Bonjour",
    ],
)
def test_une_conversation_ordinaire_ne_declenche_pas_le_controle_des_url(texte):
    assert not demande_de_liens(texte), "ne pas bloquer les réponses sans URL"


@pytest.mark.parametrize(
    "texte",
    [
        "Donne-moi son lien exact",
        "Recherche le site et donne le lien",
        "Quelle est son adresse officielle ?",
        "Je voudrais deux liens officiels",
    ],
)
def test_les_demandes_d_adresse_declenchent_le_controle(texte):
    assert demande_de_liens(texte), "vérifier avant d'afficher le chemin"


def test_les_chemins_inventes_ne_valent_pas_le_domaine_retrouve():
    sources = ["https://code.org/learn"]
    assert not liens_sans_preuve("Voici https://code.org/learn.", sources)
    assert liens_sans_preuve("code.org/learn/programming", sources), "le chemin compte"
    assert liens_sans_preuve("(remplace par le vrai lien)", sources)
    assert adresses("https://exemple.org/a_b?x=1&y=2.") == [
        "https://exemple.org/a_b?x=1&y=2"
    ]
    assert (
        page_a_verifier("https://code.org/inventee", "Donne le lien de Code.org", [])
        == "https://Code.org"
    ), "consulter le domaine demandé avant un chemin improvisé"


@pytest.mark.asyncio
async def test_une_adresse_candidate_est_lue_par_le_meme_executeur():
    from tests.server.test_agentic_stream import ExecuteurFactice

    moteur = MoteurFactice(
        [
            [StreamChunk(content="https://code.org", finish_reason="stop")],
            [StreamChunk(content="https://code.org", finish_reason="stop")],
        ]
    )
    executeur = ExecuteurFactice("Page Code.org reçue")
    events = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [Message(role=Role.USER, content="Donne le lien Code.org")],
            tools=[OutilFactice("web_read")],
            executor=executeur,
        )
    ]
    assert len(executeur.recus) == 1, "une lecture réelle avant le texte"
    assert executeur.recus[0].name == "web_read", (
        "permissions de l'exécuteur conservées"
    )
    assert "".join(e.data for e in events if e.kind == "token") == "https://code.org"
    assert [e.kind for e in events].index("tool_end") < [e.kind for e in events].index(
        "token"
    )


def test_les_notes_diapason_ne_partent_pas_dans_apple_notes():
    assert erreur_destination("notes_write", "Crée une note Diapason appelée Test")
    assert erreur_destination("notes_write", "Ajoute cette note dans Diapason")
    assert (
        erreur_destination("notes_write", "Diapason, crée une note dans Apple Notes")
        is None
    )
    assert erreur_destination("vie_workspace", "Crée une note Diapason") is None


@pytest.mark.asyncio
async def test_une_lecture_en_echec_ne_livre_pas_une_adresse_inventee():
    moteur = MoteurFactice(
        [
            [
                StreamChunk(
                    tool_calls=[_appel("web_read", '{"url":"https://code.org/perdue"}')]
                )
            ],
            [
                StreamChunk(
                    content="Adresse officielle : code.org/inventee",
                    finish_reason="stop",
                )
            ],
            [
                StreamChunk(
                    tool_calls=[_appel("web_search", '{"query":"Code.org officiel"}')]
                )
            ],
            [StreamChunk(content="Voici https://code.org/learn", finish_reason="stop")],
        ]
    )

    class Executeur:
        def execute(self, appel):
            if appel.name == "web_read":
                return ToolResult(
                    tool_name=appel.name, content="HTTP 404", success=False
                )
            return ToolResult(
                tool_name=appel.name,
                content="Source: https://code.org/learn",
                success=True,
                metadata={
                    "sources": [{"url": "https://code.org/learn", "title": "Code.org"}]
                },
            )

    evenements = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [Message(role=Role.USER, content="Donne le lien officiel de Code.org")],
            tools=[OutilFactice("web_search"), OutilFactice("web_read")],
            executor=Executeur(),
        )
    ]
    texte = "".join(e.data for e in evenements if e.kind == "token")
    assert texte == "Voici https://code.org/learn", (
        "la correction précède toute diffusion"
    )
    assert len(moteur.appels) == 4, "une seule reprise puis la vraie recherche"


@pytest.mark.asyncio
async def test_un_modele_qui_persiste_ne_livre_que_les_sources_recues():
    moteur = MoteurFactice(
        [[StreamChunk(content="https://faux.example.com", finish_reason="stop")]]
    )

    class Executeur:
        def execute(self, _):
            raise AssertionError("aucun appel émis")

    evenements = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [Message(role=Role.USER, content="Donne un lien")],
            tools=[],
            executor=Executeur(),
        )
    ]
    texte = "".join(e.data for e in evenements if e.kind == "token")
    assert "faux.example.com" not in texte
    assert "pas pu obtenir" in texte
    assert len(moteur.appels) == 2, "pas de boucle infinie"
