"""§5/§100 : les transports gardent le contexte et ne promettent pas un outil fini."""

import asyncio
import json
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from diapason.etudes.conversation import (
    ContexteEtudes,
    contexte_actuel,
    utiliser_contexte,
)
from diapason.etudes.magasin import MagasinEtudes
from diapason.etudes.service import ServiceEtudes
from diapason.server.etudes_conversation import contexte_etudes_chat
from diapason.server.models import ChatCompletionRequest
from diapason.server.voice_live_routes import voice_live_router
from diapason.speech.realtime.base import SessionEvent
from diapason.speech.realtime.bridge import VoiceLiveBridge
from diapason.speech.realtime.local_voice import LocalVoiceSession
from diapason.tools.etudier import EtudierTool
from tests.server.test_etudes import demande, programme
from tests.server.test_etudes_routes import Moteur
from tests.server.test_voice_live_routes import _ReadySession


@pytest.fixture
def app(tmp_path):
    a = FastAPI()
    a.state.api_key = "diapason_sk_test"
    a.state.engine = Moteur()
    a.state.etudes_store = MagasinEtudes(tmp_path / "etudes.db")
    a.include_router(voice_live_router)
    return a


class TestTransportEtudier:
    @pytest.mark.asyncio
    async def test_le_chat_retient_aussi_la_fausse_sauvegarde(self, app):
        from diapason.core.types import Message, Role
        from diapason.engine._stubs import StreamChunk
        from diapason.server.agentic_stream import stream_with_tools
        from tests.server.test_agentic_stream import MoteurFactice, _appel

        service = ServiceEtudes(app.state.etudes_store, app.state.engine)
        s = service.depot.creer(demande(mode="practice"), programme())
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        arguments = {
            "action": "answer",
            "sessionId": s["id"],
            "version": s["version"],
            "choiceIndex": 1,
        }
        moteur = MoteurFactice(
            [
                [
                    StreamChunk(
                        content="Ta réponse est enregistrée et correcte.",
                        finish_reason="stop",
                    )
                ],
                [
                    StreamChunk(
                        tool_calls=[_appel("study", json.dumps(arguments))],
                        finish_reason="stop",
                    )
                ],
                [
                    StreamChunk(
                        content="Ta réponse est enregistrée.", finish_reason="stop"
                    )
                ],
            ]
        )

        class Executeur:
            def execute(self, appel):
                return EtudierTool().execute(**json.loads(appel.arguments))

        with utiliser_contexte(
            ContexteEtudes(
                service, "fil-test", "local", asyncio.get_running_loop(), demande="1/2"
            )
        ):
            evts = [
                e
                async for e in stream_with_tools(
                    moteur,
                    "local",
                    [Message(role=Role.USER, content="1/2")],
                    tools=[EtudierTool()],
                    executor=Executeur(),
                )
            ]
        assert "".join(e.data for e in evts if e.kind == "token") == (
            "Ta réponse est enregistrée."
        ), "la fausse correction ne doit pas être affichée avant l'outil"
        assert service.depot.lire(s["id"])["responses"]["q1"]["text"] == "1/2"

    def test_le_flux_chat_garde_les_documents_et_les_mots_exacts(self, app):
        @app.post("/banc", dependencies=[Depends(contexte_etudes_chat)])
        async def flux(request_body: ChatCompletionRequest):
            async def produire():
                r = await asyncio.to_thread(EtudierTool().execute, action="list")
                c = contexte_actuel()
                yield json.dumps(
                    {"ok": r.success, "fil": c.conversation, "texte": c.demande}
                )

            return StreamingResponse(produire())

        with TestClient(app) as client:
            r = client.post(
                "/banc",
                json={
                    "model": "local",
                    "conversationId": "fil-test",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Voici mon cours.",
                            "documents": [{"nom": "cours.txt", "texte": "Texte."}],
                        },
                        {"role": "user", "content": "Ma réponse exacte."},
                    ],
                },
            )
        assert r.json() == {
            "ok": True,
            "fil": "fil-test",
            "texte": "Ma réponse exacte.",
        }, "le générateur SSE doit garder le contexte après retour de la route"
        assert app.state.etudes_store.lire_sources("fil-test")[0]["text"] == "Texte."
        assert contexte_actuel() is None, "aucun contexte ne fuit vers le prochain fil"

    @pytest.mark.parametrize("invite", [True, False])
    def test_la_session_vocale_herite_du_fil_sauf_le_mode_invite(
        self, app, monkeypatch, invite
    ):
        recus = []

        class Session(_ReadySession):
            async def connect(self):
                c = contexte_actuel()
                recus.append(c.conversation if c else None)

        monkeypatch.setattr(
            "diapason.speech.realtime.factory.create_realtime_session",
            lambda *a, **kw: Session(),
        )
        with TestClient(app).websocket_connect(
            "/v1/voice/live?provider=local",
            subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
        ) as ws:
            ws.send_json(
                {
                    "type": "start",
                    "provider": "local",
                    "include_memory": False,
                    "conversationId": "fil-test",
                    "conversationOnly": invite,
                }
            )
            ws.receive_json()
        assert recus == [None if invite else "fil-test"]

    @pytest.mark.asyncio
    async def test_le_tour_oral_enregistre_la_vraie_reponse(self, app):
        service = ServiceEtudes(app.state.etudes_store, app.state.engine)
        s = service.depot.creer(demande(mode="practice"), programme())
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        s = service.depot.modifier(
            s["id"], s["version"], "navigate", {"questionId": "q2"}
        )
        texte = "Deux moitiés forment une unité."
        tours = []

        def llm(messages):
            q = asyncio.Queue()
            if not tours:
                q.put_nowait("Ta réponse est enregistrée. La réponse est correcte.")
            elif len(tours) == 1:
                q.put_nowait(
                    (
                        "tools",
                        [
                            {
                                "function": {
                                    "name": "study",
                                    "arguments": {
                                        "action": "answer",
                                        "sessionId": s["id"],
                                        "version": s["version"],
                                    },
                                }
                            }
                        ],
                    )
                )
            else:
                q.put_nowait("Ta réponse est enregistrée.")
            tours.append(messages)
            q.put_nowait(None)
            return q

        def executer(nom, arguments):
            r = EtudierTool().execute(**arguments)
            return {"ok": r.success, "content": r.content, "metadata": r.metadata}

        paroles = []
        session = LocalVoiceSession(
            stt=lambda a: "",
            llm=llm,
            tts=lambda t: (paroles.append(t), b"\x01\x00" * 120)[1],
            tool_executor=executer,
        )
        with utiliser_contexte(
            ContexteEtudes(service, "fil-test", "local", asyncio.get_running_loop())
        ):
            await session.send_text(texte)
            await session._respond_task
        assert service.depot.lire(s["id"])["responses"]["q2"]["text"] == texte
        assert paroles == ["Ta réponse est enregistrée."], (
            "la fausse correction doit être retenue avant le premier son"
        )
        await session.close()

    def test_le_delai_de_loutil_couvre_la_preparation_bornee(self):
        assert EtudierTool().spec.timeout_seconds > 200, (
            "les cours réels dépassent les 30 secondes par défaut de l'exécuteur"
        )

    @pytest.mark.asyncio
    async def test_une_preparation_active_ne_passe_pas_pour_du_silence(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "diapason.speech.realtime.local_voice.INTERVALLE_ETUDE_S",
            0.01,
            raising=False,
        )

        def executer(n, a):
            time.sleep(0.05)
            return {"ok": True}

        session = LocalVoiceSession(
            stt=lambda a: "",
            llm=lambda m: None,
            tts=lambda t: b"",
            tool_executor=executer,
        )
        r = await session._executer_avec_annonce("study", {"action": "prepare"}, [])
        evenements = []
        while not session._queue.empty():
            evenements.append(session._queue.get_nowait())
        assert r["ok"] and any(e.kind == "status" for e in evenements)
        assert not any(e.kind == "tool" for e in evenements), (
            "une opération en cours ne doit annoncer ni réussite ni échec"
        )
        temps = [0.0]
        pont = VoiceLiveBridge(None, session, horloge=lambda: temps[0])
        temps[0] = 100
        pont._noter(SessionEvent(kind="status", detail="study_processing"))
        assert pont._parole_jusqua == 100
        temps[0] = 110
        pont._noter(SessionEvent(kind="status", detail="listening"))
        assert pont._parole_jusqua == 100, "l'écoute seule ne repousse pas la coupure"
