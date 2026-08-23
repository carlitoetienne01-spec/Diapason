"""Les génériques de sous-titres que Whisper hallucine sur le silence.

Whisper a appris sur des sous-titres de vidéos ; face au souffle du micro en
fin de phrase, il « entend » ce qu'il a le plus vu à cet endroit : le crédit
des sous-titreurs. Rapporté le 23 août 2026 — « à chaque fin de phrase, ça me
dit : Sous-titres par la communauté d'Amara.org ».

Deux parades, testées ici et dans le backend : le filtre de silence coupe la
queue AVANT Whisper, et ce nettoyage raye ce qui passerait quand même.
"""

from __future__ import annotations

import pytest

from diapason.speech.dictate_polish import polish_dictation, strip_whisper_credits


class TestGeneriquesRayes:
    @pytest.mark.parametrize(
        "hallucine",
        [
            "Sous-titres par la communauté d'Amara.org",
            "Sous-titres réalisés para la communauté d'Amara.org",
            "sous-titres realises par la communaute d'amara.org",
            "Subtitles by the Amara.org community",
            "Sous-titrage Société Radio-Canada",
            "Sous-titrage ST' 501",
            "Merci d'avoir regardé cette vidéo !",
            "Merci d avoir regardé cette vidéo",
            "Thanks for watching!",
            "N'oubliez pas de vous abonner",
        ],
    )
    def test_un_generique_seul_devient_vide(self, hallucine):
        """La dictée dira « transcription vide » au lieu de coller le crédit."""
        assert strip_whisper_credits(hallucine) == ""

    def test_le_generique_en_fin_de_vraie_phrase_tombe_seul(self):
        """Le cas rapporté : la phrase dictée survit, le crédit meurt."""
        rendu = strip_whisper_credits(
            "Rendez-vous demain à dix heures. "
            "Sous-titres par la communauté d'Amara.org"
        )
        assert rendu == "Rendez-vous demain à dix heures."

    def test_parler_reellement_d_amara_reste_possible(self):
        """Les motifs exigent la FORMULE du générique, jamais un mot seul."""
        phrase = "Je veux parler du site amara.org dans ma phrase."
        assert strip_whisper_credits(phrase) == phrase

    def test_une_phrase_normale_est_intouchee(self):
        assert strip_whisper_credits("Bonjour, comment vas-tu ?") == (
            "Bonjour, comment vas-tu ?"
        )

    def test_le_polissage_complet_passe_par_le_nettoyage(self):
        """Le rayage vit DANS polish_dictation : aucun chemin ne l'esquive."""
        rendu = polish_dictation(
            "rendez-vous demain matin. Sous-titres par la communauté d'Amara.org"
        )
        assert "amara" not in rendu.lower()
        assert rendu.startswith("Rendez-vous")


class TestFiltreDeSilenceDictee:
    def test_le_chemin_dictee_coupe_le_silence_avant_whisper(self, monkeypatch):
        """La parade PREMIÈRE : Whisper ne voit plus la queue de souffle.

        Le chemin temps réel filtrait déjà ; la dictée envoyait tout."""
        from diapason.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        backend._realtime = False
        backend._language = "fr"
        captures: dict = {}

        class ModeleFactice:
            def transcribe(self, samples, **kwargs):
                captures.update(kwargs)
                return iter(()), None

        monkeypatch.setattr(backend, "_ensure_model", lambda: ModeleFactice())
        monkeypatch.setattr(backend, "_hotwords", lambda: "")
        import wave, io

        tampon = io.BytesIO()
        w = wave.open(tampon, "w")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
        w.close()
        backend.transcribe(tampon.getvalue(), format="wav")
        assert captures.get("vad_filter") is True, (
            "sans filtre, la queue de silence nourrit l'hallucination"
        )
        assert captures["vad_parameters"]["speech_pad_ms"] >= 200, (
            "le rembourrage protège les bords de mots"
        )
