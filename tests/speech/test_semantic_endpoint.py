"""Combien de silence avant de considérer que la personne a fini.

800 ms est le prix de l'ignorance : sans indice sur le contenu, il faut ce
délai pour ne pas couper une phrase en deux. Mais c'était payé même quand la
transcription disait déjà « Quelle heure est-il ? » — une phrase FINIE — et
c'était le premier poste de latence de toute la boucle vocale, devant le
modèle lui-même. À l'inverse, « et donc je voulais te dire que » était coupé
à 800 ms comme n'importe quoi d'autre, en plein milieu d'une pensée.

Les humains tournent à ~200 ms parce qu'ils jugent la complétude pendant que
l'autre parle. C'est ce que la transcription partielle (commit précédent)
rend enfin possible ici.
"""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from diapason.speech.realtime.local_voice import (
    INPUT_RATE,
    LocalVoiceSession,
    classify_endpoint,
)


def trame(sec: float, ampl: float) -> bytes:
    n = int(INPUT_RATE * sec)
    return struct.pack(
        f"<{n}h", *[int(ampl * 32767 * math.sin(i / 8)) for i in range(n)]
    )


async def silence_avant_reponse(texte_stt: str, *, stt=None) -> float:
    """Parle 3 s, puis mesure le silence nécessaire pour clore le tour."""
    s = LocalVoiceSession(
        stt=stt or (lambda pcm: texte_stt),
        llm=lambda m: asyncio.Queue(),
        tts=lambda t: b"",
    )
    if s._stt is None:
        s._stt = stt or (lambda pcm: texte_stt)

    async def draine():
        while True:
            await s._queue.get()

    fond = asyncio.create_task(draine())
    try:
        for _ in range(30):
            await s.send_audio(trame(0.1, 0.30))
            await asyncio.sleep(0.01)
        n = 0
        while s._respond_task is None and n < 20:
            await s.send_audio(trame(0.1, 0.0001))
            await asyncio.sleep(0.01)
            n += 1
        return n * 0.1
    finally:
        fond.cancel()


class TestLeSilenceExigeSuitLeSens:
    @pytest.mark.asyncio
    async def test_une_phrase_finie_clot_vite(self):
        assert await silence_avant_reponse("Quelle heure est-il ?") <= 0.55

    @pytest.mark.asyncio
    async def test_une_hesitation_attend_plus_que_la_normale(self):
        """Couper « et donc je voulais te dire que » à 800 ms, c'est répondre
        à une phrase encore en construction."""
        assert await silence_avant_reponse("et donc je voulais te dire que") >= 1.0

    @pytest.mark.asyncio
    async def test_sans_indice_le_delai_normal_tient(self):
        """Pas de ponctuation, dernier mot quelconque : on ne sait pas, donc
        on paie le prix de l'ignorance — ni plus ni moins."""
        sec = await silence_avant_reponse("ouvre la porte du garage")
        assert 0.7 <= sec <= 0.9

    @pytest.mark.asyncio
    async def test_un_stt_muet_garde_le_delai_normal(self):
        sec = await silence_avant_reponse("", stt=lambda pcm: "")
        assert 0.7 <= sec <= 0.9


class TestLeClassificateur:
    @pytest.mark.parametrize(
        "texte",
        ["Quelle heure est-il ?", "Ouvre la porte.", "C'est noté !"],
    )
    def test_ponctuation_terminale_egale_complet(self, texte):
        assert classify_endpoint(texte) == "complete"

    @pytest.mark.parametrize(
        "texte",
        [
            "et donc je voulais te dire que",
            "parce que j'",
            "bon alors,",
            # « … » est l'orthographe même du trailing-off : la voix retombe
            # sans conclure. C'est le contraire d'une phrase finie.
            "je voulais dire…",
            "je voulais dire...",
        ],
    )
    def test_suspension_egale_hesitation(self, texte):
        assert classify_endpoint(texte) == "hesitation"

    @pytest.mark.parametrize("texte", ["ouvre la porte du garage", "", "  "])
    def test_le_reste_est_neutre(self, texte):
        """Sans ponctuation, pas de raccourci : « complete » est le seul
        verdict qui peut couper quelqu'un, il exige une preuve."""
        assert classify_endpoint(texte) == "neutral"


class TestLaCouvertureGardeLeRaccourci:
    @pytest.mark.asyncio
    async def test_une_respiration_ne_separe_pas_la_demande_sur_un_ancien_partiel(self):
        """§100 — une pause de 600 ms ne doit pas jeter l'amorce de la demande."""
        s = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
        liberer = asyncio.Event()
        recus = []

        async def decoder(audio, **_):
            await liberer.wait()
            recus.append(audio)
            return "la demande complète"

        async def recevoir(*_, **__):
            pass

        s._transcription_serie = decoder
        s._dispatch_text = recevoir
        debut = trame(2.4, 0.3)
        pause = trame(0.1, 0.0)
        suite = trame(0.4, 0.3)
        try:
            await s.send_audio(debut)
            s._partial_text = "Je veux apprendre."
            s._partial_text_mark = INPUT_RATE * 2 * 2
            for _ in range(6):
                await s.send_audio(pause)
                await asyncio.sleep(0)
            assert s._respond_task is None, (
                "le premier fragment ne doit pas être abandonné à la reprise"
            )
            await s.send_audio(suite)
            for _ in range(8):
                await s.send_audio(pause)
                await asyncio.sleep(0)
            liberer.set()
            assert s._respond_task is not None, "la fin réelle ouvre bien un tour"
            await s._respond_task
            attendu = debut + pause * 6 + suite
            assert any(audio.startswith(attendu) for audio in recus), (
                "le décodeur final doit recevoir les deux parties sans perdre le début"
            )
        finally:
            liberer.set()
            await s.close()

    @pytest.mark.asyncio
    async def test_la_derniere_syllabe_absente_interdit_de_couper(self):
        """§100 — 400 ms non transcrites peuvent contenir « pas » ou « que »."""
        s = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
        s._partial_text = "Je veux apprendre."
        s._partial_text_mark = int(INPUT_RATE * 2 * 2.0)
        s._speech_end_mark = int(INPUT_RATE * 2 * 2.4)
        assert s._end_of_turn_s() == pytest.approx(0.8), (
            "la ponctuation d'un texte incomplet n'autorise pas à couper la suite"
        )

    @pytest.mark.asyncio
    async def test_un_partiel_en_retard_ne_raccourcit_pas(self):
        """Le partiel dit « Quelle heure est-il ? » mais ne couvre pas la fin
        de la parole : la personne a peut-être ajouté « à Tokyo » — ou « à »
        tout court, et elle réfléchit. Pas de verdict « complet » sans
        couverture serrée."""
        s = LocalVoiceSession(
            stt=lambda pcm: "Quelle heure est-il ?",
            llm=lambda m: asyncio.Queue(),
            tts=lambda t: b"",
        )
        if s._stt is None:
            s._stt = lambda pcm: "Quelle heure est-il ?"
        s._partial_text = "Quelle heure est-il ?"
        s._partial_mark = 0  # ne couvre rien
        s._speech_end_mark = INPUT_RATE * 2 * 3  # 3 s de parole
        s._speculative = None
        assert s._end_of_turn_s() == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_le_prochain_calcul_ne_rajeunisse_pas_l_ancien_texte(self):
        """§100 — un partiel en calcul n'a pas encore compris la suite."""
        s = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
        s._partial_mark = INPUT_RATE * 2
        s._partial = asyncio.create_task(
            asyncio.sleep(0, result="Quelle heure est-il ?")
        )
        await s._partial
        await s._harvest_partial()
        s._speech_end_mark = INPUT_RATE * 2 * 4
        s._partial_mark = s._speech_end_mark  # nouveau calcul, texte encore ancien
        assert s._end_of_turn_s() == pytest.approx(0.8), (
            "la nouvelle couverture ne doit pas écourter le délai à 450 ms"
        )

    @pytest.mark.asyncio
    async def test_un_texte_identique_actualise_quand_meme_sa_couverture(self):
        s = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
        s._partial_text = "Bonjour."
        s._partial_mark = INPUT_RATE * 2 * 4
        s._speech_end_mark = s._partial_mark
        s._partial = asyncio.create_task(asyncio.sleep(0, result="Bonjour."))
        await s._partial
        await s._harvest_partial()
        assert s._end_of_turn_s() == pytest.approx(0.45), (
            "une vraie couverture complète peut raccourcir la fin du tour"
        )
