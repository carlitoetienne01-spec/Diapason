"""§100 : vérifier une écriture demande une lecture neuve, sans la répéter."""

import json

import pytest

from diapason.core.types import Message, Role, ToolResult
from diapason.engine._stubs import StreamChunk
from diapason.server.agentic_stream import stream_with_tools
from tests.server.test_agentic_stream import (
    ExecuteurFactice,
    MoteurFactice,
    OutilFactice,
    _appel,
    _collecter,
)


class TestRelectureApresEcriture:
    @pytest.mark.asyncio
    async def test_la_verification_demande_une_lecture_apres_la_modification(self):
        """§100 : annoncer le budget écrit ne remplace pas sa relecture demandée."""
        moteur = MoteurFactice(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            _appel(
                                "diapason_app",
                                '{"operation":"upsert_budget","params":{"body":{"limit":720}}}',
                            )
                        ]
                    )
                ],
                [
                    StreamChunk(
                        content="Budget enregistré, relis-le toi-même.",
                        finish_reason="stop",
                    )
                ],
                [
                    StreamChunk(
                        tool_calls=[
                            _appel(
                                "diapason_app",
                                '{"operation":"list_budgets","params":{"yearMonth":"2026-10"}}',
                            )
                        ]
                    )
                ],
                [StreamChunk(content="Montant relu : 720.", finish_reason="stop")],
            ]
        )
        executeur = ExecuteurFactice()
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [
                    Message(
                        role=Role.USER,
                        content="Modifie le budget à 720 et relis le montant.",
                    )
                ],
                tools=[OutilFactice("diapason_app")],
                executor=executeur,
            )
        ]
        assert [json.loads(c.arguments)["operation"] for c in executeur.recus] == [
            "upsert_budget",
            "list_budgets",
        ], "écriture puis relecture réelle"
        assert (
            "".join(e.data for e in events if e.kind == "token")
            == "Montant relu : 720."
        ), "aucune vérification déléguée à l'utilisateur"

    @pytest.mark.asyncio
    async def test_une_fausse_confirmation_est_retenue_avant_la_vraie_ecriture(self):
        """§100 : le budget annoncé à 720 restait réellement à 650."""
        moteur = MoteurFactice(
            [
                [StreamChunk(content="Budget modifié à 720.", finish_reason="stop")],
                [
                    StreamChunk(
                        tool_calls=[
                            _appel(
                                "diapason_app",
                                '{"operation":"upsert_budget","params":{"body":{"limit":720}}}',
                            )
                        ]
                    )
                ],
                [StreamChunk(content="Budget enregistré : 720.", finish_reason="stop")],
            ]
        )
        executeur = ExecuteurFactice()
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [Message(role=Role.USER, content="Modifie le budget à 720.")],
                tools=[OutilFactice("diapason_app")],
                executor=executeur,
            )
        ]
        assert len(executeur.recus) == 1, "une écriture réelle remplace l'annonce seule"
        assert (
            "".join(e.data for e in events if e.kind == "token")
            == "Budget enregistré : 720."
        ), "aucun faux succès ne fuit avant l'outil"

    @pytest.mark.asyncio
    async def test_une_ecriture_refusee_ne_devient_pas_un_succes(self):
        """§100 : un refus de capacité est un résultat, pas une exception."""

        class Refus(ExecuteurFactice):
            def execute(self, call):
                self.recus.append(call)
                return ToolResult(tool_name=call.name, content="Refusé", success=False)

        moteur = MoteurFactice(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            _appel(
                                "diapason_app_delete",
                                '{"operation":"delete_note","params":{"noteId":"cible"}}',
                            )
                        ]
                    )
                ],
                [StreamChunk(content="Note supprimée.", finish_reason="stop")],
            ]
        )
        executeur = Refus()
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [Message(role=Role.USER, content="Supprime la note Courses.")],
                tools=[
                    OutilFactice("diapason_app"),
                    OutilFactice("diapason_app_delete"),
                ],
                executor=executeur,
            )
        ]
        assert (
            "".join(e.data for e in events if e.kind == "token")
            == "Je n’ai pas pu effectuer cette modification dans Diapason."
        ), "le refus reste un échec"
        assert len(executeur.recus) == 1, "le refus ne relance pas la suppression"

    @pytest.mark.asyncio
    async def test_une_cible_manquante_peut_etre_precisee(self):
        """§100 : aucun identifiant de note ne doit être inventé pour agir."""
        moteur = MoteurFactice(
            [
                [
                    StreamChunk(
                        content="Quelle note souhaites-tu retirer ?",
                        finish_reason="stop",
                    )
                ]
            ]
        )
        executeur = ExecuteurFactice()
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [Message(role=Role.USER, content="Supprime une note.")],
                tools=[OutilFactice("diapason_app")],
                executor=executeur,
            )
        ]
        assert not executeur.recus, (
            "ne pas choisir une note à la place de l'utilisateur"
        )
        assert "Quelle note" in "".join(e.data for e in events if e.kind == "token")

    @pytest.mark.parametrize(
        "texte",
        [
            "Comment créer une note ?",
            "Ne supprime pas ma note.",
            "Explique-moi les budgets.",
            "Donne-moi trois recettes de pâtes.",
        ],
    )
    def test_les_conseils_ne_demandent_pas_de_mutation(self, texte):
        """§100 : une explication reste une explication, sans écriture forcée."""
        from diapason.server.actions_internes import mutation_interne_demandee

        assert not mutation_interne_demandee(texte), "aucune modification demandée"

    @pytest.mark.asyncio
    async def test_la_note_creee_est_relue_par_son_identifiant_recu(self):
        """§100 : pas besoin que le titre ait été dicté entre guillemets."""

        class Executeur(ExecuteurFactice):
            def execute(self, call):
                self.recus.append(call)
                if json.loads(call.arguments).get("action") == "create_note":
                    return ToolResult(
                        tool_name=call.name,
                        content="Créée",
                        success=True,
                        metadata={"note": {"id": "id-recu", "content": "Pain"}},
                    )
                return ToolResult(tool_name=call.name, content="Pain", success=True)

        moteur = MoteurFactice(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            _appel(
                                "vie_workspace",
                                '{"action":"create_note","title":"Courses","content":"Pain"}',
                            )
                        ]
                    )
                ],
                [StreamChunk(content="C'est relu", finish_reason="stop")],
                [StreamChunk(content="Pain", finish_reason="stop")],
            ]
        )
        executeur = Executeur()
        events = [
            e
            async for e in stream_with_tools(
                moteur,
                "test",
                [
                    Message(
                        role=Role.USER,
                        content="Crée une note Courses et relis la note.",
                    )
                ],
                tools=[OutilFactice("vie_workspace")],
                executor=executeur,
            )
        ]
        assert json.loads(executeur.recus[-1].arguments) == {
            "action": "read_note",
            "item_id": "id-recu",
        }
        assert "".join(e.data for e in events if e.kind == "token") == "Pain", (
            "seule la relecture aboutie est présentée"
        )

    def test_lecture_rejouee_apres_ecriture_mais_pas_la_creation(self):
        """§100 : le cache ne doit ni masquer l'écriture ni en créer un doublon."""
        lecture = json.dumps(
            {"operation": "list_budgets", "params": {"yearMonth": "2026-10"}}
        )
        ecriture = json.dumps(
            {"operation": "upsert_budget", "params": {"body": {"limit": 50}}}
        )
        inverse = json.dumps(
            {"params": {"body": {"limit": 50}}, "operation": "upsert_budget"}
        )
        moteur = MoteurFactice(
            [
                [StreamChunk(tool_calls=[_appel("diapason_app", arg)])]
                for arg in (lecture, ecriture, lecture, inverse, lecture)
            ]
            + [[StreamChunk(content="Terminé", finish_reason="stop")]]
        )
        executeur = ExecuteurFactice()
        _collecter(moteur, executeur, outils=("diapason_app",))
        assert [json.loads(a.arguments)["operation"] for a in executeur.recus] == [
            "list_budgets",
            "upsert_budget",
            "list_budgets",
        ], "une écriture, deux lectures ; ni doublon ni lecture périmée"
