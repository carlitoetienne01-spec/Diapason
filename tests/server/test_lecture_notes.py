"""§100 — retenir un contenu de note inventé avant de le présenter comme relu."""

import pytest

from diapason.core.types import Message, Role
from diapason.engine._stubs import StreamChunk
from diapason.server.agentic_stream import stream_with_tools
from diapason.server.lecture_notes import cibler_recherche_note, relecture_note_demandee
from tests.server.test_agentic_stream import (
    ExecuteurFactice,
    MoteurFactice,
    OutilFactice,
    _appel,
)


class TestAccordDeLecture:
    @pytest.mark.asyncio
    async def test_la_liste_demandee_sans_filtre_recoit_le_titre_accepte(self):
        """§100 : une liste générale tronquée ne prouve pas l'absence de la note."""
        import json

        moteur = MoteurFactice(
            [
                [
                    StreamChunk(
                        tool_calls=[_appel("vie_workspace", '{"action":"list_notes"}')]
                    )
                ],
                [StreamChunk(content="Contenu relu", finish_reason="stop")],
            ]
        )
        executeur = ExecuteurFactice("Contenu relu")
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [
                    Message(role=Role.USER, content="Retrouve ma note « Jeux »"),
                    Message(
                        role=Role.ASSISTANT,
                        content="Veux-tu que je relise son contenu ?",
                    ),
                    Message(role=Role.USER, content="oui"),
                ],
                tools=[OutilFactice("vie_workspace")],
                executor=executeur,
            )
        ]
        attendu = {"action": "list_notes", "search": "Jeux"}
        assert json.loads(executeur.recus[0].arguments) == attendu, (
            "filtre réellement exécuté"
        )
        debut = next(e for e in events if e.kind == "tool_start")
        assert json.loads(debut.data["arguments"]) == attendu, (
            "la carte montre le vrai filtre"
        )

    @pytest.mark.parametrize(
        "arguments",
        [
            '{"action":"list_notes","search":"Autre titre"}',
            '{"action":"update_note","item_id":"id"}',
            '{"action":"read_note","item_id":"id"}',
            "[]",
            "invalide",
        ],
    )
    def test_ne_modifie_pas_une_recherche_existante_ni_une_action(self, arguments):
        """§5 : cibler une lecture n'invente ni action ni nouveaux arguments."""
        assert (
            cibler_recherche_note(arguments, "Relis la note « Jeux »") == arguments
        ), "seule une liste sans filtre peut recevoir le titre cité"

    @pytest.mark.asyncio
    async def test_l_accord_retrouve_le_titre_avant_de_declarer_la_note_absente(self):
        """§100 : « oui » ne permet pas d'affirmer une absence sans recherche."""
        import json

        from diapason.core.types import ToolResult

        class ExecuteurAvecEchec(ExecuteurFactice):
            def execute(self, appel):
                if json.loads(appel.arguments).get("action") == "read_note":
                    self.recus.append(appel)
                    return ToolResult(
                        tool_name=appel.name,
                        content="Identifiant inconnu",
                        success=False,
                    )
                return super().execute(appel)

        moteur = MoteurFactice(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            _appel(
                                "vie_workspace",
                                '{"action":"read_note","item_id":"inventé"}',
                            )
                        ]
                    )
                ],
                [StreamChunk(content="Cette note n'existe pas", finish_reason="stop")],
                [StreamChunk(content="Contenu actuel", finish_reason="stop")],
            ]
        )
        executeur = ExecuteurAvecEchec("Contenu actuel")
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [
                    Message(role=Role.USER, content="Retrouve ma note « Jeux »"),
                    Message(
                        role=Role.ASSISTANT,
                        content="Veux-tu que je relise son contenu actuel ?",
                    ),
                    Message(role=Role.USER, content="oui"),
                ],
                tools=[OutilFactice("vie_workspace")],
                executor=executeur,
            )
        ]
        assert json.loads(executeur.recus[-1].arguments) == {
            "action": "list_notes",
            "search": "Jeux",
        }, "le titre est retrouvé dans la demande acceptée, sans id inventé"
        assert (
            "".join(e.data for e in events if e.kind == "token") == "Contenu actuel"
        ), "aucun faux constat d'absence ne doit atteindre le chat"

    @pytest.mark.asyncio
    async def test_un_acquiescement_apres_lecture_ne_relance_pas_la_tache(self):
        """§5 : accuser réception d'une lecture terminée n'en demande pas une autre."""
        moteur = MoteurFactice(
            [[StreamChunk(content="D'accord.", finish_reason="stop")]]
        )
        executeur = ExecuteurFactice()
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [
                    Message(role=Role.USER, content="Relis ma note « Jeux »"),
                    Message(
                        role=Role.ASSISTANT,
                        content="Objectif : apprendre la programmation.",
                    ),
                    Message(role=Role.USER, content="ok"),
                ],
                tools=[OutilFactice("vie_workspace")],
                executor=executeur,
            )
        ]
        assert executeur.recus == [], "aucune nouvelle lecture après réception"
        assert "".join(e.data for e in events if e.kind == "token") == "D'accord."


@pytest.mark.asyncio
async def test_la_relecture_livre_le_resultat_recu_et_non_le_graphique_invente():
    moteur = MoteurFactice(
        [
            [StreamChunk(content="```diapason-chart\nfaux\n```", finish_reason="stop")],
            [
                StreamChunk(
                    tool_calls=[
                        _appel(
                            "vie_workspace", '{"action":"read_note","item_id":"test"}'
                        )
                    ]
                )
            ],
            [StreamChunk(content="Contenu actuel", finish_reason="stop")],
        ]
    )
    executeur = ExecuteurFactice("Contenu actuel")
    evenements = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [Message(role=Role.USER, content="Relis ma note")],
            tools=[OutilFactice("vie_workspace")],
            executor=executeur,
        )
    ]
    assert (
        "".join(e.data for e in evenements if e.kind == "token") == "Contenu actuel"
    ), "aucun brouillon inventé ne doit atteindre le chat"
    assert len(executeur.recus) == 1, "lecture effectivement exécutée"


@pytest.mark.asyncio
async def test_un_modele_sans_appel_ne_peut_pas_affirmer_avoir_relu():
    moteur = MoteurFactice([[StreamChunk(content="Note relue", finish_reason="stop")]])
    evenements = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [Message(role=Role.USER, content="Relis ma note")],
            tools=[OutilFactice("vie_workspace")],
            executor=ExecuteurFactice(),
        )
    ]
    assert len(moteur.appels) == 2, "une seule reprise sans boucle"
    assert "pas pu relire" in "".join(
        e.data for e in evenements if e.kind == "token"
    ), "dire l'échec réel"


def test_expliquer_une_lecture_ne_lance_pas_d_outil():
    assert not relecture_note_demandee("Explique comment lire une note"), (
        "explication seulement"
    )
    assert not relecture_note_demandee("Ne relis pas ma note"), "respecter la négation"
    assert not relecture_note_demandee("Relis ma note dans Apple Notes"), (
        "la garde Diapason ne doit pas imposer une autre destination"
    )
    assert not relecture_note_demandee("Lis ma note dans Notes.app"), (
        "un autre nom explicite de l'application garde son outil"
    )


@pytest.mark.asyncio
async def test_le_titre_cite_permet_une_recherche_sans_identifiant_devine():
    import json

    moteur = MoteurFactice(
        [
            [StreamChunk(content="Ancien souvenir", finish_reason="stop")],
            [StreamChunk(content="Contenu relu", finish_reason="stop")],
        ]
    )
    executeur = ExecuteurFactice("Contenu relu")
    events = [
        e
        async for e in stream_with_tools(
            moteur,
            "test",
            [Message(role=Role.USER, content="Relis ma note « Jeux »")],
            tools=[OutilFactice("vie_workspace")],
            executor=executeur,
        )
    ]
    assert json.loads(executeur.recus[0].arguments) == {
        "action": "list_notes",
        "search": "Jeux",
    }, "recherche exacte et sans écriture"
    assert "".join(e.data for e in events if e.kind == "token") == "Contenu relu"
