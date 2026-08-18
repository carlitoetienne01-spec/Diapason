"""La génération part pendant le silence ; rien d'autre ne part avec elle.

Une fois la fin de tour sémantique en place, il restait un temps mort : la
transcription spéculative atterrit vers 0,3–0,5 s de silence, et la
génération n'était lancée qu'à la clôture du tour (0,45 à 1,15 s). Cet écart
est maintenant recouvert : dès que le texte du tour est connu, le modèle
démarre, et la clôture ADOPTE la file en vol au lieu de régénérer.

La sûreté tient à une propriété structurelle, pas à une promesse : les
outils ne s'exécutent et la voix ne sort que dans la boucle de drainage de
``_respond_to_text``. Une file qu'on remplit sans la drainer ne peut ni
agir ni parler — spéculer, c'est remplir sans drainer.
"""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from diapason.speech.realtime.local_voice import INPUT_RATE, LocalVoiceSession

TEXTE = "quelle est la capitale de l'Australie"  # neutre : clôture à 0,8 s


def trame(sec: float, ampl: float) -> bytes:
    n = int(INPUT_RATE * sec)
    return struct.pack(f"<{n}h", *[int(ampl * 32767 * math.sin(i / 8)) for i in range(n)])


class Banc:
    """Session instrumentée : compte les lancements LLM, les outils, la voix."""

    def __init__(self, texte: str = TEXTE):
        self.appels: list[list] = []
        self.outils: list[str] = []
        self.dits: list[str] = []

        def llm(messages):
            self.appels.append(list(messages))
            q: asyncio.Queue = asyncio.Queue()
            q.put_nowait("Canberra, bien sûr. ")
            q.put_nowait(None)
            return q

        self.s = LocalVoiceSession(
            stt=lambda pcm: texte,
            llm=llm,
            tts=lambda t: self.dits.append(t) or b"\x00\x00",
        )
        if self.s._stt is None:
            self.s._stt = lambda pcm: texte
        if self.s._llm is None:
            self.s._llm = llm
        self.s._tool_executor = lambda n, a: self.outils.append(n) or "ok"
        self._fond = None

    async def __aenter__(self):
        async def draine():
            while True:
                await self.s._queue.get()

        self._fond = asyncio.create_task(draine())
        return self

    async def __aexit__(self, *exc):
        self._fond.cancel()

    async def parle(self, sec: float):
        for _ in range(int(sec / 0.1)):
            await self.s.send_audio(trame(0.1, 0.30))
            await asyncio.sleep(0.005)

    async def se_tait(self, sec: float):
        for _ in range(int(sec / 0.1)):
            await self.s.send_audio(trame(0.1, 0.0001))
            await asyncio.sleep(0.01)


class TestLaGenerationPartPendantLeSilence:
    @pytest.mark.asyncio
    async def test_lancee_avant_la_cloture_du_tour(self):
        async with Banc() as b:
            await b.parle(3.0)
            await b.se_tait(0.5)
            assert len(b.appels) == 1, "la génération doit partir sur le silence"
            assert b.s._respond_task is None, "le tour ne doit PAS être clos"

    @pytest.mark.asyncio
    async def test_aucun_outil_ne_s_execute_avant_confirmation(self):
        """LA propriété de sûreté. Le reste est de la vitesse."""
        async with Banc() as b:
            await b.parle(3.0)
            await b.se_tait(0.5)
            assert b.outils == []
            assert b.dits == [], "et aucun son ne part non plus"

    @pytest.mark.asyncio
    async def test_la_cloture_adopte_au_lieu_de_regenerer(self):
        async with Banc() as b:
            await b.parle(3.0)
            await b.se_tait(0.9)
            await asyncio.sleep(0.3)
            assert len(b.appels) == 1, "adopter, pas régénérer"
            assert b.dits, "la réponse a bien été prononcée"

    @pytest.mark.asyncio
    async def test_les_messages_specules_sont_ceux_du_vrai_tour(self):
        """Même assemblage que _respond_to_text : historique plafonné plus le
        tour en cours. Un désaccord ici ferait répondre à un autre contexte."""
        async with Banc() as b:
            b.s._history.extend(
                {"role": "user", "content": f"tour {i}"} for i in range(20)
            )
            await b.parle(3.0)
            await b.se_tait(0.5)
            messages = b.appels[0]
            assert messages[-1] == {"role": "user", "content": TEXTE}
            assert len(messages) <= 16, "le plafond d'historique s'applique aussi"


class TestCeQuiNeDoitPasSpeculer:
    @pytest.mark.asyncio
    async def test_la_reprise_de_parole_jette_la_file(self):
        async with Banc() as b:
            await b.parle(3.0)
            await b.se_tait(0.5)
            assert len(b.appels) == 1
            await b.s.send_audio(trame(0.3, 0.30))  # la parole reprend
            assert b.s._spec_llm is None

    @pytest.mark.asyncio
    async def test_une_phrase_d_arret_ne_specule_pas(self):
        """« Arrête » ne reçoit aucune réponse ; générer dessus chaufferait
        la machine pour un texte que personne ne lira."""
        async with Banc(texte="arrête") as b:
            await b.parle(3.0)
            await b.se_tait(0.5)
            assert b.appels == []

    @pytest.mark.asyncio
    async def test_une_commande_vocale_explicite_ne_specule_pas(self):
        """« Ouvre … » prend le chemin direct sans LLM."""
        async with Banc(texte="ouvre la porte du garage") as b:
            await b.parle(3.0)
            await b.se_tait(0.5)
            assert b.appels == []
