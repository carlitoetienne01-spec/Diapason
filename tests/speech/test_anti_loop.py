"""Un assistant ne redit pas la même chose à chaque tour.

Vécu en session réelle : interrogé sur « comment t'aider à trouver tes
sources », le modèle a répondu « Je t'écoute. » — une béquille que le prompt
lui SUGGÉRAIT alors (« Prefer natural openers like "Je t'écoute." ») — puis
l'a redite à chaque tour : sa propre répétition dans l'historique devenait le
motif le plus probable à continuer. La règle du prompt est corrigée, mais un
prompt est un vœu ; ce garde est un mécanisme.
"""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from diapason.speech.realtime.local_voice import INPUT_RATE, LocalVoiceSession
from diapason.speech.realtime.oral_prompt import ORAL_VOICE_RULES


def _session(llm, texte="comment puis-je t'aider à trouver tes sources"):
    s = LocalVoiceSession(stt=lambda p: texte, llm=llm, tts=lambda t: b"\x00")
    if s._stt is None:
        s._stt = lambda p: texte
    if s._llm is None:
        s._llm = llm
    return s


class TestLaNoteAntiBoucle:
    def _hist(self, *reponses):
        h = []
        for r in reponses:
            h.append({"role": "user", "content": "question"})
            h.append({"role": "assistant", "content": r})
        return h

    def test_deux_repliques_identiques_declenchent(self):
        note = LocalVoiceSession._anti_loop_note(
            self._hist("Je t'écoute.", "Je t'écoute.")
        )
        assert note is not None and note["role"] == "system"
        assert "Je t'écoute." in note["content"], "la phrase répétée est NOMMÉE"

    def test_la_casse_ne_deguise_pas_la_repetition(self):
        assert (
            LocalVoiceSession._anti_loop_note(
                self._hist("Je t'écoute.", "JE T'ÉCOUTE.")
            )
            is not None
        )

    def test_deux_repliques_differentes_ne_declenchent_pas(self):
        assert (
            LocalVoiceSession._anti_loop_note(self._hist("Bonjour.", "Je t'écoute."))
            is None
        )

    def test_une_seule_replique_ne_declenche_pas(self):
        assert LocalVoiceSession._anti_loop_note(self._hist("Je t'écoute.")) is None

    def test_un_historique_vide_ne_declenche_pas(self):
        assert LocalVoiceSession._anti_loop_note([]) is None


class TestLaSceneReelle:
    @pytest.mark.asyncio
    async def test_le_troisieme_tour_recoit_l_injonction(self):
        """La scène exacte de la session : un modèle bloqué qui répond
        « Je t'écoute. » à chaque tour. Au troisième assemblage, la note doit
        être dans les messages — y compris ceux de la SPÉCULATION, qui passe
        par le même chemin."""
        recus: list[list] = []

        def llm(messages):
            recus.append(list(messages))
            q: asyncio.Queue = asyncio.Queue()
            q.put_nowait("Je t'écoute. ")
            q.put_nowait(None)
            return q

        s = _session(llm)

        async def vide():
            while True:
                await s._queue.get()

        fond = asyncio.create_task(vide())

        def trame(sec, ampl):
            n = int(INPUT_RATE * sec)
            return struct.pack(
                f"<{n}h", *[int(ampl * 32767 * math.sin(i / 8)) for i in range(n)]
            )

        try:
            for _ in range(3):
                for _ in range(30):
                    await s.send_audio(trame(0.1, 0.30))
                    await asyncio.sleep(0.004)
                for _ in range(10):
                    await s.send_audio(trame(0.1, 0.0001))
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.4)
        finally:
            fond.cancel()

        notes_t2 = [m for m in recus[1] if m.get("role") == "system"]
        notes_t3 = [m for m in recus[-1] if m.get("role") == "system"]
        assert notes_t2 == [], "pas d'injonction avant deux répétitions"
        assert notes_t3, "au troisième tour, l'injonction est là"
        assert "Je t'écoute." in notes_t3[0]["content"]


class TestLePromptNEnseignePlusLaBequille:
    def test_je_t_ecoute_est_interdit_pas_suggere(self):
        """La règle disait « Prefer natural openers like "Je t'écoute." » —
        en contradiction directe avec la règle 3 qui interdit les phrases
        toutes faites. Le modèle a choisi la béquille quand il était coincé."""
        assert "Prefer natural openers" not in ORAL_VOICE_RULES
        # La phrase n'apparaît plus que dans la liste des INTERDITS.
        ligne = next(li for li in ORAL_VOICE_RULES.splitlines() if "Je t'écoute" in li)
        assert "canned" in ligne or "filler" in ligne.lower() or '"' in ligne
