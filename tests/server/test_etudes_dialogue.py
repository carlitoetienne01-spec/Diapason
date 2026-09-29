"""§5/§100 : le parcours prononcé suit l'épreuve, jamais une question inventée."""

import asyncio
import json

import pytest

from diapason.core.types import Message, Role, ToolResult
from diapason.etudes.conversation import ContexteEtudes, utiliser_contexte
from diapason.etudes.dialogue import (
    InterpretationPreparation,
    InterpretationReponse,
    actions_explicites,
    interpreter_preparation,
    interpreter_reponse,
)
from diapason.etudes.magasin import MagasinEtudes, vue_publique
from diapason.etudes.service import ServiceEtudes
from diapason.server.agentic_stream import stream_with_tools
from diapason.speech.realtime.local_voice import LocalVoiceSession
from diapason.tools.etudier import EtudierTool
from tests.server.test_etudes import demande, programme
from tests.server.test_etudes_routes import Moteur


class Executeur:
    def execute(self, appel):
        return EtudierTool().execute(**json.loads(appel.arguments))


@pytest.fixture
def service(tmp_path):
    return ServiceEtudes(MagasinEtudes(tmp_path / "etudes.db"), Moteur())


class TestDialogue:
    @pytest.mark.asyncio
    async def test_la_creation_orale_execute_loutil_et_garde_les_documents(
        self, service, monkeypatch
    ):
        """§100 : une préparation annoncée sans outil ne crée aucun parcours."""
        sources = [d.model_dump(by_alias=True) for d in demande().sources]
        texte = "Prépare-moi un cours débutant avec mon document, deux questions."

        async def classer(moteur, modele, contrat, consigne, donnees, **kw):
            assert donnees["studentMessage"] == texte
            return InterpretationPreparation(
                prepare=True,
                topic="Les fractions",
                level="Débutant",
                mode="practice",
                questionCount=5,
                useDocuments=True,
            )

        monkeypatch.setattr("diapason.etudes.dialogue.produire", classer)
        paroles = []

        def executer(nom, arguments):
            assert nom == "study" and "sessionId" not in arguments
            r = EtudierTool().execute(**arguments)
            return {"ok": r.success, "content": r.content}

        def modele_interdit(*a, **kw):
            raise AssertionError("La demande classée doit créer le vrai cours.")

        session = LocalVoiceSession(
            stt=lambda a: "",
            llm=modele_interdit,
            tts=lambda t: (paroles.append(t), b"\x01\x00" * 120)[1],
            tool_executor=executer,
        )
        with utiliser_contexte(
            ContexteEtudes(
                service,
                "fil-test",
                "local",
                asyncio.get_running_loop(),
                sources=sources,
            )
        ):
            await session.send_text(texte)
            await session._respond_task
        etudes = service.depot.lister("fil-test")
        assert len(etudes) == 1 and len(etudes[0]["questions"]) == 2
        assert service.depot.lire(etudes[0]["id"])["sources"] == sources
        assert "est prêt" in " ".join(paroles)
        await session.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "texte",
        [
            "Ne prépare pas de cours",
            "Peux-tu créer des examens ?",
            "Prépare un cours puis supprime mes notes",
        ],
    )
    async def test_une_creation_non_confirmee_par_le_classifieur_necrit_rien(
        self, service, monkeypatch, texte
    ):
        async def classer(*a, **kw):
            return InterpretationPreparation(
                prepare=False,
                topic="",
                level="Débutant",
                mode="practice",
                questionCount=5,
                useDocuments=True,
            )

        monkeypatch.setattr("diapason.etudes.dialogue.produire", classer)
        c = ContexteEtudes(
            service, "fil-test", "local", asyncio.get_running_loop(), demande=texte
        )
        assert await interpreter_preparation(c) is None
        assert service.depot.lister("fil-test") == []

    @pytest.mark.asyncio
    async def test_un_examen_ne_contourne_pas_le_refus_daide_par_la_reponse_du_modele(
        self, service, monkeypatch
    ):
        s = service.depot.creer(demande(mode="exam"), programme())
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        s = service.depot.modifier(
            s["id"], s["version"], "navigate", {"questionId": "q2"}
        )

        async def classer(*a, **kw):
            return InterpretationReponse(answer=False, choiceIndex=None)

        monkeypatch.setattr("diapason.etudes.dialogue.produire", classer)
        with utiliser_contexte(
            ContexteEtudes(service, "fil-test", "local", asyncio.get_running_loop())
        ):
            evts = [
                e
                async for e in stream_with_tools(
                    object(),
                    "local",
                    [Message(role=Role.USER, content="Explique-moi la bonne réponse.")],
                    tools=[EtudierTool()],
                    executor=Executeur(),
                )
            ]
        texte = "".join(e.data for e in evts if e.kind == "token")
        assert "corrigé reste masqué" in texte
        assert s["program"]["questions"][1]["answer"] not in texte
        assert service.depot.lire(s["id"])["responses"] == {}

    @pytest.mark.asyncio
    async def test_la_classification_ne_voit_pas_le_corrige_et_ne_reecrit_pas_la_copie(
        self, service, monkeypatch
    ):
        s = service.depot.creer(demande(mode="practice"), programme())
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        s = service.depot.modifier(
            s["id"], s["version"], "navigate", {"questionId": "q2"}
        )
        texte = "Je pense que, euh, on additionne les deux nombres du haut."
        contexte = ContexteEtudes(
            service, "fil-test", "local", asyncio.get_running_loop()
        )

        async def classer(moteur, modele, contrat, consigne, donnees, **kw):
            assert set(donnees["question"]) == {"kind", "prompt", "choices"}
            assert donnees["studentMessage"] == texte
            return InterpretationReponse(answer=True, choiceIndex=None)

        monkeypatch.setattr("diapason.etudes.dialogue.produire", classer)
        with utiliser_contexte(contexte):
            evts = [
                e
                async for e in stream_with_tools(
                    object(),
                    "local",
                    [Message(role=Role.USER, content=texte)],
                    tools=[EtudierTool()],
                    executor=Executeur(),
                )
            ]
        assert service.depot.lire(s["id"])["responses"]["q2"]["text"] == texte
        assert not service.depot.lire(s["id"])["grades"], "enregistrer ne corrige pas"
        assert (
            "".join(e.data for e in evts if e.kind == "token")
            == "Ta réponse est enregistrée."
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("issue", ["help", "ambiguous", "unavailable"])
    async def test_laide_un_choix_ambigu_et_la_panne_nenregistrent_rien(
        self, service, monkeypatch, issue
    ):
        s = service.depot.creer(demande(), programme())
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        c = ContexteEtudes(service, "fil-test", "local", asyncio.get_running_loop())

        async def classer(*a, **kw):
            if issue == "unavailable":
                raise RuntimeError("moteur indisponible")
            return InterpretationReponse(answer=issue == "ambiguous", choiceIndex=None)

        monkeypatch.setattr("diapason.etudes.dialogue.produire", classer)
        assert await interpreter_reponse(c, vue_publique(s)) is None
        assert not service.depot.lire(s["id"])["responses"]

    @pytest.mark.asyncio
    async def test_la_voix_demarre_et_le_chat_corrige_la_meme_epreuve(self, service):
        s = service.depot.creer(demande(mode="practice"), programme())
        contexte = ContexteEtudes(
            service, "fil-test", "local", asyncio.get_running_loop()
        )

        def modele_interdit(*args, **kwargs):
            raise AssertionError("Une commande explicite n'exige pas d'inférence.")

        def executer(n, p):
            r = EtudierTool().execute(**p)
            return {"ok": r.success, "content": r.content}

        paroles = []
        session = LocalVoiceSession(
            stt=lambda a: "",
            llm=modele_interdit,
            tts=lambda t: (paroles.append(t), b"\x01\x00" * 120)[1],
            tool_executor=executer,
        )
        with utiliser_contexte(contexte):
            await session.send_text(
                "Fais-moi passer ce test, pose-moi la première question."
            )
            await session._respond_task
            assert service.depot.lire(s["id"])["state"] == "active"
            assert "1/2" in " ".join(paroles), "les vrais choix sont lus"
            paroles.clear()
            await session.send_text("La réponse un")
            await session._respond_task
        assert " ".join(paroles) == "Ta réponse est enregistrée.", (
            "ni félicitation sans note, ni nouvelle question inventée"
        )
        assert (
            service.depot.lire(s["id"])["responses"]["q1"]["spokenText"]
            == "La réponse un"
        )
        with utiliser_contexte(contexte):
            evts = [
                e
                async for e in stream_with_tools(
                    object(),
                    "local",
                    [
                        Message(
                            role=Role.USER,
                            content=(
                                "Corrige ma réponse, puis passe à la question suivante."
                            ),
                        )
                    ],
                    tools=[EtudierTool()],
                    executor=Executeur(),
                )
            ]
        final = service.depot.lire(s["id"])
        assert (
            final["currentQuestionId"] == "q2" and final["grades"]["q1"]["score"] == 1
        )
        assert final["program"]["questions"][1]["prompt"] in "".join(
            e.data for e in evts if e.kind == "token"
        ), "la question affichée est celle de la base"
        await session.close()

    @pytest.mark.asyncio
    async def test_le_refus_de_capacite_ne_devient_pas_un_demarrage(self, service):
        s = service.depot.creer(demande(), programme())

        class Refus:
            def execute(self, appel):
                return ToolResult(
                    tool_name="study", success=False, content="Accès refusé"
                )

        with utiliser_contexte(
            ContexteEtudes(service, "fil-test", "local", asyncio.get_running_loop())
        ):
            evts = [
                e
                async for e in stream_with_tools(
                    object(),
                    "local",
                    [Message(role=Role.USER, content="Commence le test")],
                    tools=[EtudierTool()],
                    executor=Refus(),
                )
            ]
        assert service.depot.lire(s["id"])["state"] == "ready"
        assert "Accès refusé" in "".join(e.data for e in evts if e.kind == "token")
        assert not next(e.data for e in evts if e.kind == "tool_end")["success"]

    @pytest.mark.parametrize(
        "texte",
        [
            "Ne commence pas le test",
            "Comment commencer le test ?",
            "Si je dis commence le test, que fais-tu ?",
            "Commence le test et efface mes notes",
            "La réponse un, mais explique-moi aussi le dénominateur",
            "Pourquoi la réponse un ?",
        ],
    )
    def test_les_demandes_ambigues_negatives_et_composees_restant_au_modele(
        self, service, texte
    ):
        s = service.depot.creer(demande(), programme())
        assert not actions_explicites(texte, vue_publique(s))
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        assert not actions_explicites(texte, vue_publique(s))
