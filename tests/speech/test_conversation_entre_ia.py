"""§78 / §100 — une autre voix discute sans prendre le contrôle du Mac."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, Mock

import pytest

from diapason.core.origine_telephone import marquer_le_telephone
from diapason.speech.realtime.bridge import event_to_client_json
from diapason.speech.realtime.factory import create_realtime_session
from diapason.speech.realtime.local_voice import LocalVoiceSession


def seance(**options):
    return LocalVoiceSession(
        stt=lambda _: "Bonjour",
        llm=lambda _: None,
        tts=lambda _: b"",
        **options,
    )


def test_la_voix_invitee_ne_recoit_ni_outils_ni_identite_privee():
    s = seance(
        conversation_seule=True,
        enable_tools=True,
        instructions="SOUVENIR PERSONNEL",
        tool_executor=Mock(),
    )
    assert not s._enable_tools, "le drapeau client ne rouvre pas les outils"
    assert s._tool_executor is None, "aucun exécuteur dans cette séance"
    assert not s._voice_lock_actif(), "l'invité peut parler sans enrôlement"
    assert "SOUVENIR PERSONNEL" not in s._system_prompt(), "pas de mémoire privée"
    assert seance()._conversation_seule is False, "le prochain démarrage est normal"


@pytest.mark.asyncio
async def test_l_acquittement_confirme_la_restriction(monkeypatch):
    s = seance(conversation_seule=True)
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.ollama_reachable", lambda: True
    )
    s._warm = AsyncMock(return_value=True)
    await s.connect()
    assert event_to_client_json(s._queue.get_nowait()) == {
        "type": "ready",
        "conversationOnly": True,
    }, "le micro invité attend cette confirmation"


@pytest.mark.asyncio
async def test_le_controle_vocal_et_l_enrolement_ne_sont_pas_appeles(monkeypatch):
    def interdit():
        raise AssertionError("le profil vocal ne doit pas être touché")

    monkeypatch.setattr("diapason.speech.speaker_id.get_verifier", interdit)
    monkeypatch.setattr("diapason.desktop.etat_bureau.etat_du_bureau", interdit)
    s = seance(conversation_seule=True)
    s._respond_to_text = AsyncMock()
    await s._dispatch_text(
        "Bonjour Diapason", turn_started=time.monotonic(), utterance=b"autre voix"
    )
    s._respond_to_text.assert_awaited_once()


def test_le_bureau_et_la_memoire_ne_sont_ni_lus_ni_nourris(monkeypatch):
    def interdit(*_a, **_k):
        raise AssertionError("le contexte personnel doit rester fermé")

    monkeypatch.setattr("diapason.desktop.etat_bureau.dernier_etat_connu", interdit)
    s = seance(conversation_seule=True, sur_echange=interdit)
    s._magasin_traces = interdit
    assert s._turn_messages("Bonjour") == [{"role": "user", "content": "Bonjour"}]
    s._journaliser_echange("Bonjour", "Salut")


@pytest.mark.asyncio
async def test_meme_un_appel_direct_d_outil_est_refuse():
    s = seance(conversation_seule=True)
    executer = Mock()
    s._tool_executor = executer
    resultat = await s._run_tool(
        {"function": {"name": "open_anything", "arguments": {}}}
    )
    assert json.loads(resultat["content"])["ok"] is False, "aucun faux succès"
    assert not await s._try_fast_voice_action(
        "ouvre Safari", turn_started=time.monotonic()
    )
    executer.assert_not_called()


@pytest.mark.asyncio
async def test_sa_propre_voix_ne_lance_pas_un_nouveau_tour():
    s = seance(conversation_seule=True)
    s._speaking_until = time.monotonic() + 2
    s._respond_task = asyncio.create_task(asyncio.sleep(10))
    await s.send_audio(b"\xff\x7f" * 8000)
    assert not s._buffer, "l'audio du haut-parleur ne doit pas devenir une question"
    assert not s._respond_task.cancelling(), "pas d'auto-interruption"
    s._respond_task.cancel()
    await asyncio.gather(s._respond_task, return_exceptions=True)


def test_le_telephone_et_le_cloud_ne_peuvent_pas_elargir_la_portee():
    with marquer_le_telephone(), pytest.raises(ValueError, match="bureau local"):
        seance(conversation_seule=True)
    with pytest.raises(ValueError, match="bureau local"):
        create_realtime_session("openai", conversation_seule=True)


@pytest.mark.asyncio
async def test_les_trous_entre_morceaux_ne_rouvrent_pas_l_ecoute():
    """§100 — essai du 26/09 : le premier morceau finissait avant le suivant."""
    s = seance(conversation_seule=True)
    attente = asyncio.Event()
    s._respond_task = asyncio.create_task(attente.wait())
    s._speaking_until = 0
    await s.send_audio(b"\xff\x7f" * 2400)
    assert not s._respond_task.cancelling(), "pas d'interruption entre deux morceaux"
    assert not s._buffer, "l'écho intermédiaire doit être jeté"
    attente.set()
    await s._respond_task
    await s.send_audio(b"\xff\x7f" * 2400)
    assert s._in_speech, "le tour fini, l'invité peut reprendre"
