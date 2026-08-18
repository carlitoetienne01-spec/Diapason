"""L'écran doit suivre la voix pendant qu'elle parle.

Tous les événements « transcript » partaient avec ``final=True`` : rien ne
pouvait s'afficher avant la fin de la phrase. On parlait devant un écran
vide, puis tout apparaissait d'un coup. ``SessionEvent`` portait pourtant
déjà un champ ``final`` que personne n'alimentait — le canal existait, il
était muet.
"""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from diapason.speech.realtime.base import SessionEvent
from diapason.speech.realtime.bridge import event_to_client_json
from diapason.speech.realtime.local_voice import INPUT_RATE, LocalVoiceSession


def trame(secondes: float, amplitude: float) -> bytes:
    n = int(INPUT_RATE * secondes)
    return struct.pack(
        f"<{n}h", *[int(amplitude * 32767 * math.sin(i / 8)) for i in range(n)]
    )


def session(stt) -> LocalVoiceSession:
    s = LocalVoiceSession(stt=stt, llm=lambda m: asyncio.Queue(), tts=lambda t: b"")
    s._stt = stt
    return s


async def parler(s: LocalVoiceSession, secondes: float, amplitude: float = 0.30):
    """Pousse de l'audio et récolte les transcriptions émises au passage."""
    vus: list[SessionEvent] = []

    async def ecoute():
        while True:
            e = await s._queue.get()
            if e.kind == "transcript":
                vus.append(e)

    tache = asyncio.create_task(ecoute())
    for _ in range(int(secondes / 0.2)):
        await s.send_audio(trame(0.2, amplitude))
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)
    tache.cancel()
    return vus


class TestLesMotsParaissentPendantQuOnParle:
    @pytest.mark.asyncio
    async def test_des_partiels_sont_emis_avant_la_fin_du_tour(self):
        etapes = ["Quelle", "Quelle heure", "Quelle heure est-il"]

        def stt(pcm):
            secondes = len(pcm) / 2 / INPUT_RATE
            return etapes[min(int(secondes / 0.7), len(etapes) - 1)]

        vus = await parler(session(stt), 4.0)
        assert vus, "aucune transcription pendant la parole"
        assert all(not e.final for e in vus), "un tour non terminé n'est pas final"

    @pytest.mark.asyncio
    async def test_ils_demandent_un_remplacement_pas_un_ajout(self):
        """Whisper relit tout le tampon et peut réviser ce qu'il a compris.
        Concaténer donnerait « QuelleQuelle heureQuelle heure est-il »."""
        vus = await parler(session(lambda pcm: "Quelle heure est-il"), 3.0)
        assert vus and all(e.replace for e in vus)

    @pytest.mark.asyncio
    async def test_le_texte_progresse_sans_se_repeter(self):
        etapes = ["Quelle", "Quelle heure", "Quelle heure est-il"]

        def stt(pcm):
            return etapes[min(int(len(pcm) / 2 / INPUT_RATE / 0.7), len(etapes) - 1)]

        textes = [e.text for e in await parler(session(stt), 4.0)]
        assert textes == sorted(set(textes), key=len), textes
        assert len(set(textes)) == len(textes), "le même texte émis deux fois"


class TestCeQuiNeDoitPasSAfficher:
    @pytest.mark.asyncio
    async def test_un_souffle_ne_produit_aucun_texte(self):
        """Whisper invente des mots sur un fragment trop court. Afficher une
        phrase que personne n'a dite est pire que n'afficher rien."""
        vus = await parler(session(lambda pcm: "bonjour"), 0.2)
        assert vus == []

    @pytest.mark.asyncio
    async def test_le_silence_ne_declenche_rien(self):
        vus = await parler(session(lambda pcm: "bonjour"), 3.0, amplitude=0.0001)
        assert vus == []


class TestLeProtocoleDitLaDifference:
    def test_un_partiel_local_porte_replace(self):
        payload = event_to_client_json(
            SessionEvent(kind="transcript", role="user", text="salut", replace=True)
        )
        assert payload["replace"] is True
        assert payload["final"] is False

    def test_un_delta_de_fournisseur_ne_le_porte_pas(self):
        """Gemini et OpenAI envoient des deltas : l'interface doit continuer
        de les concaténer, et ce test garde cette voie intacte."""
        payload = event_to_client_json(
            SessionEvent(kind="transcript", role="assistant", text=" heure")
        )
        assert payload["replace"] is False
