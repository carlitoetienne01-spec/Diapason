"""§100 — un calcul rejeté ne doit pas retarder la réponse réellement demandée."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from diapason.speech.realtime.local_voice import LocalVoiceSession, _SpecTurn


class TestSpeculationVocale:
    @pytest.mark.asyncio
    async def test_annule_la_mauvaise_reponse_avant_de_demarrer_la_bonne(self):
        spec = _SpecTurn("ancienne transcription")
        spec.source = Mock()
        ordre = []
        spec.source.abort.side_effect = lambda: ordre.append("annulé")

        def modele(_messages):
            ordre.append("nouveau calcul")
            file = asyncio.Queue()
            file.put_nowait(None)
            return file

        session = LocalVoiceSession(
            stt=lambda _: "", llm=modele, tts=lambda _: b"", enable_tools=False
        )
        await session._respond_to_text("phrase corrigée", spec_llm=spec)
        assert ordre == ["annulé", "nouveau calcul"], (
            "avec un seul créneau Ollama, démarrer avant d'annuler fait attendre"
        )

    @pytest.mark.asyncio
    async def test_rejoue_la_bonne_speculation_sans_second_calcul(self):
        spec = _SpecTurn("bonjour")
        spec.source = Mock()
        spec.items = [None]
        modele = Mock(side_effect=AssertionError("calcul redondant"))
        session = LocalVoiceSession(
            stt=lambda _: "", llm=modele, tts=lambda _: b"", enable_tools=False
        )
        await session._respond_to_text("bonjour", spec_llm=spec)
        modele.assert_not_called()
        spec.source.abort.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("texte", ["", "paroles non adressées"])
    async def test_un_tour_vide_ou_ignore_libere_aussi_son_calcul(self, texte):
        spec = _SpecTurn("hypothèse")
        spec.source = Mock()
        session = LocalVoiceSession(
            stt=lambda _: texte, llm=Mock(), tts=lambda _: b"", enable_tools=False
        )
        session._dispatch_text = AsyncMock()
        await session._respond(b"", spec_llm=spec)
        spec.source.abort.assert_called_once()

    @pytest.mark.asyncio
    async def test_une_annulation_pendant_la_transcription_libere_la_speculation(self):
        spec = _SpecTurn("hypothèse")
        spec.source = Mock()
        session = LocalVoiceSession(
            stt=lambda _: "", llm=Mock(), tts=lambda _: b"", enable_tools=False
        )
        attente = asyncio.create_task(asyncio.Event().wait())
        tour = asyncio.create_task(
            session._respond(b"", early_stt=attente, spec_llm=spec)
        )
        await asyncio.sleep(0)
        tour.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tour
        spec.source.abort.assert_called_once()
        assert attente.cancelled(), "la transcription en attente ne survit pas au tour"

    @pytest.mark.asyncio
    async def test_annule_le_drainage_la_rediffusion_et_la_synthese_en_attente(self):
        spec = _SpecTurn("bonjour")
        spec.source = Mock()
        spec.drainer = asyncio.create_task(asyncio.Event().wait())
        spec.first_audio = asyncio.create_task(asyncio.Event().wait())
        rediffusion = spec.replay_queue()
        await asyncio.sleep(0)
        spec.abort()
        await asyncio.sleep(0)
        assert spec.drainer.cancelled(), "le lecteur original doit s'arrêter"
        assert spec.first_audio.cancelled(), "la synthèse non adoptée doit s'arrêter"
        assert rediffusion.producer.cancelled(), "aucune attente de jetons orpheline"
