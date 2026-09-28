"""§5 — l'orbe doit dire pourquoi elle ne répond pas (26/09/2026)."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from diapason.speech.realtime.base import SessionEvent
from diapason.speech.realtime.bridge import event_to_client_json
from diapason.speech.realtime.local_voice import ADDRESS_WINDOW_S, LocalVoiceSession


def session():
    return LocalVoiceSession(
        stt=lambda _: "Bonjour", llm=lambda _: None, tts=lambda _: b""
    )


def test_le_motif_voyage_jusqu_au_client():
    event = SessionEvent(kind="status", detail="waitingForName")
    assert event_to_client_json(event) == {
        "type": "status",
        "stage": "waitingForName",
    }, "le refus d'adresse ne doit plus être muet"


@pytest.mark.asyncio
async def test_le_chauffage_ne_consomme_pas_la_fenetre_d_adresse(monkeypatch):
    s = session()
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.ollama_reachable", lambda: True
    )

    async def chauffer():
        s._engagee_jusqua = time.monotonic() - 1
        return True

    monkeypatch.setattr(s, "_warm", chauffer)
    await s.connect()
    assert s._engagee_jusqua > time.monotonic() + ADDRESS_WINDOW_S - 1, (
        "prêt veut dire prêt"
    )


@pytest.mark.asyncio
async def test_la_garde_du_nom_signale_son_attente_sans_appeler_le_modele():
    s = session()
    s._engagee_jusqua = 0
    s._respond_to_text = AsyncMock()
    await s._dispatch_text("Bonjour", turn_started=time.monotonic())
    e = s._queue.get_nowait()
    assert (e.kind, e.detail) == ("status", "waitingForName"), "l'attente doit se voir"
    s._respond_to_text.assert_not_called()


@pytest.mark.asyncio
async def test_une_voix_refusee_est_signalee_sans_ouvrir_les_outils(monkeypatch):
    s = session()
    s._voice_lock = True
    s._respond_to_text = AsyncMock()

    class Verificateur:
        arme = True

        def evaluer(self, _pcm):
            from diapason.speech.speaker_id import VerdictVocal

            return VerdictVocal("notRecognized", 0.1)

    monkeypatch.setattr(
        "diapason.speech.speaker_id.get_verifier", lambda: Verificateur()
    )
    await s._dispatch_text("Bonjour", turn_started=time.monotonic(), utterance=b"audio")
    evenements = []
    while not s._queue.empty():
        evenements.append(s._queue.get_nowait())
    assert [e.detail for e in evenements] == ["checkingVoice", "voiceNotRecognized"], (
        "le refus doit être explicite"
    )
    s._respond_to_text.assert_not_called()


@pytest.mark.asyncio
async def test_transcription_lente_visible_avant_son_resultat(monkeypatch):
    s = session()
    fini = asyncio.Event()
    t = asyncio.create_task(fini.wait())
    s._dispatch_text = AsyncMock()
    reponse = asyncio.create_task(s._respond(b"", early_stt=t))
    event = await asyncio.wait_for(s._queue.get(), timeout=1)
    assert event.detail == "transcribing", "on ne reste pas sur Je t'écoute"
    reponse.cancel()
    await asyncio.gather(reponse, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "etat"),
    [
        ("insufficientAudio", "voiceNeedsMoreSpeech"),
        ("profileMissing", "voiceProfileRequired"),
        ("unavailable", "voiceCheckUnavailable"),
    ],
)
async def test_le_doute_ne_publie_pas_de_message_et_n_ouvre_pas_les_commandes(
    monkeypatch, verdict, etat
):
    """§100 : ni confiance héritée ni apprentissage silencieux sur un refus."""
    from unittest.mock import Mock

    from diapason.speech.speaker_id import VerdictVocal

    s = session()
    s._voice_lock = True
    s._engagee_jusqua = time.monotonic() + ADDRESS_WINDOW_S
    s._respond_to_text = AsyncMock()
    s._try_fast_voice_action = AsyncMock()
    verifier = Mock()
    verifier.evaluer.return_value = VerdictVocal(verdict)
    monkeypatch.setattr("diapason.speech.speaker_id.get_verifier", lambda: verifier)
    await s._dispatch_text(
        "Diapason, supprime ma note", turn_started=time.monotonic(), utterance=b"audio"
    )
    evenements = []
    while not s._queue.empty():
        evenements.append(s._queue.get_nowait())
    assert [(e.kind, e.detail) for e in evenements] == [
        ("status", "checkingVoice"),
        ("status", etat),
    ], "aucun message accepté"
    s._respond_to_text.assert_not_called()
    s._try_fast_voice_action.assert_not_called()
    verifier.enroll.assert_not_called()


@pytest.mark.asyncio
async def test_un_oui_court_reconnu_passe_mais_n_autorise_pas_la_voix_suivante(
    monkeypatch, tmp_path
):
    """§100 : mot bref accepté, mais identité vérifiée à chaque tour."""
    import numpy as np

    from diapason.speech.speaker_id import SpeakerVerifier

    pcm = (np.sin(np.arange(3840) * 0.08) * 4000).astype("<i2").tobytes()
    profil = tmp_path / "profil.npz"
    np.savez(profil, embeddings=np.array([[1.0, 0.0]] * 5, dtype=np.float32))
    v = SpeakerVerifier(profile_path=profil)
    monkeypatch.setattr(v, "embed", lambda *_: np.array([1.0, 0.0], dtype=np.float32))
    monkeypatch.setattr("diapason.speech.speaker_id.get_verifier", lambda: v)
    s = session()
    s._voice_lock = True
    s._du_telephone = True  # Aucun cliché du bureau dans ce test de dialogue.
    s._engagee_jusqua = time.monotonic() + ADDRESS_WINDOW_S
    s._try_fast_voice_action = AsyncMock(return_value=False)
    s._respond_to_text = AsyncMock()
    await s._dispatch_text("Oui", turn_started=time.monotonic(), utterance=pcm)
    s._respond_to_text.assert_awaited_once()
    evenements = []
    while not s._queue.empty():
        evenements.append(s._queue.get_nowait())
    assert any(
        e.kind == "transcript" and e.text == "Oui" and e.final for e in evenements
    ), "le mot reconnu rejoint le chat"
    monkeypatch.setattr(v, "embed", lambda *_: np.array([0.0, 1.0], dtype=np.float32))
    s._respond_to_text.reset_mock()
    s._try_fast_voice_action.reset_mock()
    await s._dispatch_text("Oui", turn_started=time.monotonic(), utterance=pcm)
    s._respond_to_text.assert_not_called()
    s._try_fast_voice_action.assert_not_called()
    assert not s._closed, "l'écoute continue sans imposer de nouvelle connexion"
    assert v.echantillons == 5, "aucun apprentissage automatique des deux voix"
