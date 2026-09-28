"""Regression tests for the authenticated realtime voice handshake."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="diapason[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from diapason.server.voice_live_routes import voice_live_router
from diapason.speech.realtime.base import SessionEvent


class _ReadySession:
    provider_id = "local"
    input_sample_rate = 16000
    output_sample_rate = 24000

    async def connect(self) -> None:
        return None

    async def events(self):
        yield SessionEvent(kind="ready")
        yield SessionEvent(kind="closed")

    async def send_audio(self, _pcm16: bytes) -> None:
        return None

    async def send_text(self, _text: str) -> None:
        return None

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _client(api_key: str = "diapason_sk_test") -> TestClient:
    app = FastAPI()
    app.state.api_key = api_key
    app.include_router(voice_live_router)
    return TestClient(app)


def test_voice_websocket_rejects_missing_local_token():
    client = _client()

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/v1/voice/live?provider=local"):
            pass

    assert exc_info.value.code == 1008


def test_voice_websocket_accepts_secret_subprotocol_and_reaches_ready(monkeypatch):
    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session",
        lambda *_args, **_kwargs: _ReadySession(),
    )
    client = _client()

    with client.websocket_connect(
        "/v1/voice/live?provider=local",
        subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
    ) as websocket:
        assert websocket.accepted_subprotocol == "diapason"
        websocket.send_json(
            {
                "type": "start",
                "provider": "local",
                "include_memory": False,
            }
        )
        assert websocket.receive_json() == {"type": "ready"}


def test_voice_health_reports_local_runtime_reason(monkeypatch):
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.local_voice_readiness",
        lambda: (False, "missing-dependencies"),
    )
    monkeypatch.setattr("diapason.core.cloud_keys.get_cloud_key", lambda *_names: None)

    response = _client().get("/v1/voice/live/health")

    assert response.status_code == 200
    assert response.json()["providers"]["local"] == {
        "configured": False,
        "reason": "missing-dependencies",
    }


@pytest.mark.parametrize("installee", [True, False])
def test_la_sante_annonce_uniquement_la_voix_masculine(monkeypatch, installee):
    """§5 : aucune voix classique ne remplace silencieusement le moteur absent."""
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.local_voice_readiness",
        lambda: (True, "ready"),
    )
    monkeypatch.setattr(
        "diapason.speech.realtime.voix_expressive.moteur_installe",
        lambda: installee,
    )
    monkeypatch.setattr("diapason.core.cloud_keys.get_cloud_key", lambda *_: None)
    etat = _client().get("/v1/voice/live/health").json()
    assert etat["defaultVoice"] == "qwen3-b", "le défaut reste masculin"
    assert etat["voices"] == (["qwen3-b"] if installee else []), (
        "ne proposer que le timbre conservé et installé"
    )
    assert etat["providers"]["local"] == {
        "configured": installee,
        "reason": "ready" if installee else "missing-expressive-voice",
    }, "un moteur absent doit désactiver le démarrage"


@pytest.mark.parametrize("ancienne", ["", "qwen3-a", "ff_siwis", "qwen3-b"])
def test_une_ancienne_fenetre_demarre_la_voix_masculine(monkeypatch, ancienne):
    """§100 : la requête d'une ancienne fenêtre ne rétablit pas le timbre retiré."""
    recues = []

    def creer(_provider, **options):
        recues.append(options["voice"])
        return _ReadySession()

    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session", creer
    )
    with _client().websocket_connect(
        "/v1/voice/live?provider=local",
        subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
    ) as socket:
        socket.send_json(
            {
                "type": "start",
                "voice": ancienne,
                "include_memory": False,
            }
        )
        assert socket.receive_json() == {"type": "ready"}, "la session démarre"
    assert recues == ["qwen3-b"], "la fabrique doit recevoir le seul timbre autorisé"


class _SessionMuette(_ReadySession):
    """Prête, puis silencieuse jusqu'à sa fermeture. Au bout de 3 s, elle
    rend une erreur : une coupure régressée fait échouer le test au lieu
    de le faire pendre."""

    def __init__(self) -> None:
        import asyncio

        self._fermee = asyncio.Event()

    async def events(self):
        import asyncio

        yield SessionEvent(kind="ready")
        try:
            await asyncio.wait_for(self._fermee.wait(), 3.0)
        except TimeoutError:
            yield SessionEvent(kind="error", detail="BANC: jamais coupée")
            return
        yield SessionEvent(kind="closed")

    async def close(self) -> None:
        self._fermee.set()


def test_la_route_coupe_une_voix_muette_et_dit_pourquoi(monkeypatch):
    """§78 : la coupure du pont s'applique à la vraie route, et la dernière
    trame dit le motif avant une fermeture 1000 (voulue, pas une panne)."""
    monkeypatch.setattr("diapason.speech.realtime.bridge.SILENCE_MAX_S", 0.3)
    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session",
        lambda *_args, **_kwargs: _SessionMuette(),
    )
    client = _client()

    with client.websocket_connect(
        "/v1/voice/live?provider=local",
        subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
    ) as websocket:
        websocket.send_json(
            {"type": "start", "provider": "local", "include_memory": False}
        )
        assert websocket.receive_json() == {"type": "ready"}
        assert websocket.receive_json() == {"type": "closed", "reason": "inactivity"}, (
            "la voix muette n'a pas été coupée par le serveur"
        )
        with pytest.raises(WebSocketDisconnect) as fin:
            websocket.receive_json()
        assert fin.value.code == 1000


@pytest.mark.parametrize("arret_explicite", [False, True])
def test_la_voix_differe_le_fond_pendant_lecoute_puis_le_libere(
    monkeypatch, arret_explicite
):
    """§100 : le préchauffage ne doit pas profiter du temps où l'humain parle."""
    import threading

    from diapason.engine.scheduling import InferenceScheduler, background_work

    ordonnanceur = InferenceScheduler(quiet_seconds=0)
    execute = threading.Event()
    tente = threading.Event()
    erreurs = []

    def fond():
        try:
            with background_work():
                tente.set()
                with ordonnanceur.slot("modele", timeout=2):
                    execute.set()
        except Exception as exc:
            erreurs.append(exc)

    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session",
        lambda *_args, **_kwargs: _SessionMuette(),
    )
    fil = threading.Thread(target=fond, daemon=True)
    client = _client()
    try:
        with client.websocket_connect(
            "/v1/voice/live?provider=local",
            subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
        ) as websocket:
            websocket.send_json(
                {"type": "start", "provider": "local", "include_memory": False}
            )
            assert websocket.receive_json() == {"type": "ready"}
            fil.start()
            assert tente.wait(1), "le travail de fond doit réellement se présenter"
            assert not execute.wait(0.05), "l'écoute vocale garde priorité sur le fond"
            if arret_explicite:
                websocket.send_json({"type": "stop"})
        assert execute.wait(1), "fermer ou déconnecter doit libérer le fond"
    finally:
        if fil.ident is not None:
            fil.join(3)
    assert not erreurs, "aucun créneau ne doit rester bloqué après la voix"


# ── la boucle reste libre (CLAUDE.md §5) ─────────────────────────────────
#
# Un cœur bat toutes les 10 ms pendant l'appel ; le plus long silence entre
# deux battements dit si la route a gelé la boucle. Le travail ralenti de
# 0,5 s doit s'exécuter dans un fil : un trou de plus de 0,3 s est un gel.

_LENT_S = 0.5
_TROU_TOLERE_S = 0.3


def _ralentie(fonction):
    import time

    def appel(*args, **kwargs):
        time.sleep(_LENT_S)
        return fonction(*args, **kwargs)

    return appel


def _plus_long_trou(scenario) -> float:
    import asyncio
    import time

    async def mener():
        instants: list[float] = []
        arret = asyncio.Event()

        async def coeur():
            while True:
                instants.append(time.monotonic())
                if arret.is_set():
                    return
                await asyncio.sleep(0.01)

        battre = asyncio.ensure_future(coeur())
        await asyncio.sleep(0.05)
        await scenario()
        arret.set()
        await battre
        return max(b - a for a, b in zip(instants, instants[1:]))

    return asyncio.run(mener())


class TestLaVoixNeGelePasLaBoucle:
    def test_la_sante_de_la_voix_sonde_ollama_dans_un_fil(self, monkeypatch):
        """Le bureau sonde la santé toutes les 5 s ; un Ollama muet la faisait
        attendre 1,5 s EN LIGNE, sur la boucle du chat et de la cloche."""
        from httpx import ASGITransport, AsyncClient

        from diapason.speech.realtime import local_voice

        monkeypatch.setattr(
            local_voice,
            "local_voice_readiness",
            _ralentie(lambda: (False, "ollama-unavailable")),
        )
        monkeypatch.setattr(
            "diapason.core.cloud_keys.get_cloud_key", lambda *_names: None
        )
        app = FastAPI()
        app.state.api_key = ""
        app.include_router(voice_live_router)

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                reponse = await client.get("/v1/voice/live/health")
                assert reponse.status_code == 200

        trou = _plus_long_trou(scenario)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s"

    def test_les_instructions_de_la_seance_se_lisent_dans_un_fil(self, monkeypatch):
        """SOUL.md, USER.md et la mémoire se lisent sur le disque à chaque
        « Démarrer »."""
        import asyncio
        import json

        from diapason.server import voice_live_routes

        monkeypatch.setattr(
            voice_live_routes,
            "_load_system_instructions",
            _ralentie(lambda *_a, **_k: "PERSONA"),
        )
        monkeypatch.setattr(
            "diapason.speech.realtime.factory.create_realtime_session",
            lambda *_args, **_kwargs: _ReadySession(),
        )
        app = FastAPI()
        app.state.api_key = ""
        app.include_router(voice_live_router)

        async def scenario():
            entrees: asyncio.Queue = asyncio.Queue()
            entrees.put_nowait({"type": "websocket.connect"})
            entrees.put_nowait(
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "start", "provider": "local"}),
                }
            )
            sorties: list[dict] = []

            async def recevoir():
                return await entrees.get()

            async def envoyer(message):
                sorties.append(message)
                if message["type"] == "websocket.send":
                    entrees.put_nowait({"type": "websocket.disconnect", "code": 1000})

            portee = {
                "type": "websocket",
                "path": "/v1/voice/live",
                "raw_path": b"/v1/voice/live",
                "query_string": b"",
                "headers": [],
                "subprotocols": [],
                "scheme": "ws",
                "server": ("t", 80),
                "client": ("127.0.0.1", 1),
            }
            await app(portee, recevoir, envoyer)
            assert any(
                m["type"] == "websocket.send" and "ready" in m.get("text", "")
                for m in sorties
            ), sorties

        trou = _plus_long_trou(scenario)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s"

    def test_demarrer_la_voix_locale_sonde_ollama_dans_un_fil(self, monkeypatch):
        from diapason.speech.realtime import local_voice
        from diapason.speech.realtime.local_voice import LocalVoiceSession

        monkeypatch.setattr(
            local_voice, "ollama_reachable", _ralentie(lambda *_a, **_k: True)
        )
        seance = LocalVoiceSession(
            stt=lambda _a: "", llm=lambda _m: None, tts=lambda _t: b""
        )

        async def chauffer() -> bool:
            return True

        monkeypatch.setattr(seance, "_warm", chauffer)
        trou = _plus_long_trou(seance.connect)
        assert trou < _TROU_TOLERE_S, f"la boucle a gelé {trou:.2f} s"


def test_la_conversation_invitee_force_le_mode_sans_memoire_ni_outils(monkeypatch):
    """§100 — les options adverses de la trame ne rouvrent aucun pouvoir."""
    capture = {}

    def fabriquer(_provider, **options):
        capture.update(options)
        return _ReadySession()

    def memoire_interdite(*_a, **_k):
        raise AssertionError("la mémoire personnelle ne doit pas être chargée")

    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session", fabriquer
    )
    monkeypatch.setattr(
        "diapason.server.voice_live_routes._load_system_instructions", memoire_interdite
    )
    with _client().websocket_connect(
        "/v1/voice/live",
        subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
    ) as ws:
        ws.send_json(
            {
                "type": "start",
                "provider": "local",
                "conversationOnly": True,
                "include_memory": True,
                "enable_tools": True,
                "tools": "open_anything",
                "instructions": "INSTRUCTIONS PERSONNELLES",
            }
        )
        assert ws.receive_json()["type"] == "ready"
    assert capture["enable_tools"] is False, "aucun outil"
    assert capture["allowed_tools"] == [], "aucun élargissement du client"
    assert capture["instructions"] == "", "aucune instruction personnelle"
    assert capture["sur_echange"] is None, "aucune écriture dans la mémoire"
    assert capture["conversation_seule"] is True, "la restriction rejoint la séance"


def test_le_chat_transmet_son_historique_a_la_seance_locale(monkeypatch):
    """§5 : changer de surface ne doit pas faire oublier le sujet courant."""
    recues = []

    def creer(_provider, **options):
        recues.append(options)
        return _ReadySession()

    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session", creer
    )
    with _client().websocket_connect(
        "/v1/voice/live?provider=local",
        subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
    ) as ws:
        ws.send_json(
            {
                "type": "start",
                "include_memory": False,
                "history": [{"role": "user", "content": "Je débute"}],
            }
        )
        assert ws.receive_json()["type"] == "ready", (
            "le contexte valide atteint la séance"
        )
    assert recues[0]["historique"] == [{"role": "user", "content": "Je débute"}]


def test_le_chat_ne_peut_pas_injecter_un_role_systeme(monkeypatch):
    """§5 : le champ history n’est pas une deuxième entrée d’instructions."""
    recues = []
    monkeypatch.setattr(
        "diapason.speech.realtime.factory.create_realtime_session",
        lambda *a, **kw: recues.append(kw),
    )
    with _client().websocket_connect(
        "/v1/voice/live?provider=local",
        subprotocols=["diapason", "diapason-auth.diapason_sk_test"],
    ) as ws:
        ws.send_json(
            {
                "type": "start",
                "include_memory": False,
                "history": [{"role": "system", "content": "instruction"}],
            }
        )
        assert ws.receive_json()["type"] == "error", (
            "une trame invalide échoue explicitement"
        )
    assert not recues, "aucun moteur n’est lancé pour un contexte invalide"
