"""§78/§100 — partir à la voix ferme le micro, sans effacer le chat."""

import asyncio
import time
from unittest.mock import AsyncMock, Mock

import pytest

from diapason.speech.realtime.base import SessionEvent
from diapason.speech.realtime.bridge import event_to_client_json
from diapason.speech.realtime.fin_conversation import demande_fin_conversation
from diapason.speech.realtime.local_voice import LocalVoiceSession


@pytest.mark.parametrize(
    "texte",
    [
        "Merci Diapason, ce sera tout.",
        "Diapason, tu peux disposer.",
        "OK Diapason, vous pouvez disposer !",
        "Diapason, j’en ai fini avec toi.",
        "On s’arrête là pour aujourd’hui, Diapason.",
        "À bientôt, Diapason.",
        "Diapason, termine la conversation et coupe le micro.",
        "Diapason euh j'en ai fini avec toi",
        "Merci, au revoir.",
        "Je n'ai plus besoin de toi pour le moment.",
        "On en reste là Diapason",
        "Ce sera tout pour aujourd'hui.",
        "Ferme cette session vocale s'il te plaît.",
        "À la prochaine !",
        "Bon, on s'arrête là, merci.",
        "Bonne nuit Diapason",
        "Au revoir",
        "Coupe le micro et termine notre conversation",
        "J'en ai fini pour le moment",
    ],
)
def test_une_formule_complete_termine(texte):
    assert demande_fin_conversation(texte), texte


@pytest.mark.parametrize(
    "texte",
    [
        "Stop",
        "C'est bon",
        "J'ai plus besoin de toi",
        "'Au revoir'",
        "Merci",
        "OK",
        "Attends",
        "Diapason",
        "Arrête de parler",
        "Silence",
        "Je veux continuer",
        "",
        "Ne termine pas la conversation",
        "Ne coupe pas le micro",
        "Tu ne peux pas disposer",
        "Je n'en ai pas fini avec toi",
        "Je n'ai plus besoin de toi pour le moment, mais explique ceci",
        "Si je dis au revoir, coupe le micro",
        "Comment dit-on au revoir ?",
        "Diapason, dis « tu peux disposer »",
        '"Au revoir"',
        "Diapason, traduis au revoir en anglais",
        "Ce sera tout ?",
        "Au revoir puis continue",
        "On s'arrête là pour aujourd'hui ou pas ?",
        "J'ai terminé ma tâche",
        "Fin de la conversation dans ce roman",
        "Il m'a dit au revoir",
        "Ferme la fenêtre",
        "Quitte Diapason",
        "Je préfère que tu dises bonne nuit",
        "c'est tout ce que tu sais ?",
    ],
)
def test_les_mentions_et_interruptions_ne_ferment_pas(texte):
    assert not demande_fin_conversation(texte), texte


@pytest.mark.parametrize("texte", ["stop", "attends", "c’est bon"])
def test_les_interruptions_restent_silencieuses(texte):
    from diapason.speech.realtime.local_voice import is_stop_phrase

    assert is_stop_phrase(texte), (
        "interrompre ne doit pas produire une nouvelle réponse"
    )


def session(tts=None):
    return LocalVoiceSession(
        stt=lambda _: "Merci Diapason, ce sera tout",
        llm=Mock(side_effect=AssertionError("pas de modèle pour fermer")),
        tts=tts or (lambda _: b"\x01\x02" * 240),
    )


def vider(s):
    evenements = []
    while not s._queue.empty():
        evenement = s._queue.get_nowait()
        if evenement is not None:
            evenements.append(evenement)
    return evenements


@pytest.mark.asyncio
async def test_le_depart_coupe_avant_le_son_et_garde_les_deux_messages():
    s = session()
    s._try_fast_voice_action = AsyncMock()
    await s.send_text("Merci Diapason, ce sera tout")
    await s._respond_task
    evenements = vider(s)
    assert [e.kind for e in evenements] == [
        "closing",
        "transcript",
        "transcript",
        "audio",
        "transcript",
        "closed",
    ], "fermer le micro avant de prononcer l'au revoir, puis finir"
    assert evenements[-1].detail == "farewell", "fin normale identifiée"
    assert [
        (e.role, e.text) for e in evenements if e.kind == "transcript" and e.final
    ] == [
        ("user", "Merci Diapason, ce sera tout"),
        ("assistant", "À bientôt."),
    ], "le chat conserve le départ et une seule réponse finale"
    s._try_fast_voice_action.assert_not_called()
    await s.send_audio(b"\x01\x02" * 16000)
    await s.send_text("Diapason, ouvre Safari")
    await s.interrupt()
    assert vider(s) == [], "aucun écho ou paquet tardif ne reprend la séance"
    await s.close()
    assert s._closed, "le pont peut encore libérer les ressources"


@pytest.mark.asyncio
async def test_une_identite_refusee_ne_peut_pas_fermer(monkeypatch):
    from diapason.speech.speaker_id import VerdictVocal

    s = session()
    s._voice_lock = True
    verificateur = Mock()
    verificateur.evaluer.return_value = VerdictVocal("notRecognized", 0.1)
    monkeypatch.setattr("diapason.speech.speaker_id.get_verifier", lambda: verificateur)
    await s._dispatch_text(
        "Diapason, au revoir", turn_started=time.monotonic(), utterance=b"son"
    )
    assert not s._fin_demandee, "pas de fermeture par une autre voix"
    assert vider(s)[-1].detail == "voiceNotRecognized", "le verrou reste intact"


@pytest.mark.asyncio
async def test_le_silence_expire_demande_encore_le_nom():
    s = session()
    s._engagee_jusqua = 0
    await s._dispatch_text("au revoir", turn_started=time.monotonic())
    assert vider(s)[-1].detail == "waitingForName", (
        "la télévision ne clôt pas une séance désengagée"
    )
    assert not s._fin_demandee, "le nom reste requis"


@pytest.mark.asyncio
@pytest.mark.parametrize("probleme", ["erreur", "attente"])
async def test_un_au_revoir_impossible_ne_bloque_pas_la_fermeture(
    monkeypatch, probleme
):
    s = session()

    async def parole(*_):
        if probleme == "erreur":
            raise RuntimeError("voix indisponible")
        await asyncio.Event().wait()

    monkeypatch.setattr(s, "_speak_sentence", parole)
    monkeypatch.setattr("diapason.speech.realtime.local_voice.DELAI_AU_REVOIR_S", 0.01)
    await asyncio.wait_for(
        s._dispatch_text("Au revoir", turn_started=time.monotonic()), 1
    )
    assert vider(s)[-1].kind == "closed", "une panne audio n'annule pas le départ"


@pytest.mark.asyncio
async def test_x_annule_le_depart_encore_en_preparation():
    s = session()
    en_cours = asyncio.Event()

    async def parole(*_):
        en_cours.set()
        await asyncio.Event().wait()

    s._speak_sentence = parole
    await s.send_text("Diapason, au revoir")
    await asyncio.wait_for(en_cours.wait(), 1)
    await s.close()
    await asyncio.gather(s._respond_task, return_exceptions=True)
    assert all(e.kind != "audio" for e in vider(s)), (
        "X ne laisse pas jouer un son tardif"
    )


def test_la_fin_voyage_sans_devenir_une_erreur():
    for sorte in ("closing", "closed"):
        assert event_to_client_json(SessionEvent(kind=sorte, detail="farewell")) == {
            "type": sorte,
            "reason": "farewell",
        }, "le client distingue arrêt du micro et fin du dernier son"
    assert event_to_client_json(SessionEvent(kind="closed")) == {"type": "closed"}, (
        "anciens clients inchangés"
    )


@pytest.mark.asyncio
async def test_le_pont_libere_la_session_apres_le_dernier_son():
    from diapason.speech.realtime.bridge import VoiceLiveBridge
    from tests.speech.test_voix_coupure import _Client

    s = session()
    s.connect = AsyncMock()
    client = _Client()
    client.entrantes.put_nowait({"type": "text", "text": "Diapason, tu peux disposer"})
    pont = VoiceLiveBridge(client, s)
    await asyncio.wait_for(pont.run(), 2)
    assert s._closed, "le serveur libère ses ressources sans attendre le lecteur"
    assert client.fermeture == (1000, "farewell"), "fin normale du WebSocket"
    assert client.envoyes[-1] == {"type": "closed", "reason": "farewell"}, (
        "aucune trame après la clôture"
    )
    assert any(e["type"] == "audio" for e in client.envoyes), (
        "la formule a été envoyée avant"
    )
