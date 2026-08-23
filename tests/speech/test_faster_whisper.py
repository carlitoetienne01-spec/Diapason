"""Tests for Faster-Whisper speech backend."""

from unittest.mock import MagicMock, patch

import pytest

from diapason.core.registry import SpeechRegistry
from diapason.speech.faster_whisper import FasterWhisperBackend


@pytest.fixture(autouse=True)
def _register_faster_whisper():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("faster-whisper"):
        SpeechRegistry.register_value("faster-whisper", FasterWhisperBackend)


def test_faster_whisper_backend_registers():
    """Backend registers itself in SpeechRegistry."""
    assert SpeechRegistry.contains("faster-whisper")


def test_faster_whisper_transcribe():
    """Transcribe returns a TranscriptionResult."""
    from diapason.speech._stubs import TranscriptionResult

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = " Hello world"
    mock_segment.start = 0.0
    mock_segment.end = 1.2
    mock_segment.avg_logprob = -0.3

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.95
    mock_info.duration = 1.5

    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    with patch(
        "diapason.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        from diapason.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend(model_size="base", device="cpu")
        result = backend.transcribe(b"fake audio bytes")

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 1.5


def test_realtime_transcription_uses_fast_vad_decode_without_hotwords():
    mock_model = MagicMock()
    mock_info = MagicMock(language="fr", language_probability=0.99, duration=1.0)
    mock_model.transcribe.return_value = (iter(()), mock_info)

    with patch("diapason.speech.faster_whisper.WhisperModel", return_value=mock_model):
        backend = FasterWhisperBackend(
            model_size="small",
            language="fr",
            use_dictionary_hints=False,
            realtime=True,
        )
        backend.transcribe(b"not a wav")

    kwargs = mock_model.transcribe.call_args.kwargs
    assert kwargs["beam_size"] == 1
    assert kwargs["best_of"] == 1
    assert kwargs["condition_on_previous_text"] is False
    assert kwargs["vad_filter"] is True
    assert kwargs["vad_parameters"]["min_speech_duration_ms"] >= 250
    assert "hotwords" not in kwargs


def test_faster_whisper_transcribe_temp_file_reopenable_and_removed():
    """The temp file must be closed before the model reads it, and gone after.

    On Windows, an open NamedTemporaryFile holds an exclusive handle, so
    PyAV's reopen of the path inside model.transcribe() fails with EACCES
    unless the file is closed first. Opening the path inside the mocked
    transcribe reproduces that failure mode on Windows.
    """
    import os

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.95
    mock_info.duration = 1.5

    seen = {}

    def fake_transcribe(path, **kwargs):
        seen["path"] = path
        with open(path, "rb") as fh:
            seen["content"] = fh.read()
        return iter(()), mock_info

    mock_model = MagicMock()
    mock_model.transcribe.side_effect = fake_transcribe

    with patch(
        "diapason.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        backend = FasterWhisperBackend(model_size="base", device="cpu")
        backend.transcribe(b"fake audio bytes")

    assert seen["content"] == b"fake audio bytes"
    assert not os.path.exists(seen["path"])


def test_faster_whisper_transcribe_removes_temp_file_on_error():
    """The temp file is cleaned up even when transcription fails."""
    import os

    seen = {}

    def fake_transcribe(path, **kwargs):
        seen["path"] = path
        raise RuntimeError("decode failed")

    mock_model = MagicMock()
    mock_model.transcribe.side_effect = fake_transcribe

    with patch(
        "diapason.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        backend = FasterWhisperBackend(model_size="base", device="cpu")
        with pytest.raises(RuntimeError, match="decode failed"):
            backend.transcribe(b"fake audio bytes")

    assert "path" in seen
    assert not os.path.exists(seen["path"])
    assert "decode failed" in (backend.last_error() or "")


def test_faster_whisper_falls_back_from_unsupported_float16():
    mock_model = MagicMock()

    with (
        patch(
            "diapason.speech.faster_whisper.WhisperModel",
            return_value=mock_model,
        ) as mock_whisper,
        patch(
            "diapason.speech.faster_whisper.ctranslate2",
            MagicMock(
                get_supported_compute_types=MagicMock(return_value={"float32", "int8"})
            ),
        ),
    ):
        backend = FasterWhisperBackend(
            model_size="base",
            device="cpu",
            compute_type="float16",
        )
        assert backend._ensure_model() is mock_model

    mock_whisper.assert_called_once_with("base", device="cpu", compute_type="int8")


def test_faster_whisper_missing_dependency_hint_uses_desktop_extra():
    with patch("diapason.speech.faster_whisper.WhisperModel", new=None):
        backend = FasterWhisperBackend()

        with pytest.raises(ImportError) as excinfo:
            backend._ensure_model()

    assert "uv sync --extra desktop" in str(excinfo.value)
    assert "uv sync --extra speech" not in str(excinfo.value)


def test_faster_whisper_health_no_model():
    """Health returns False before model is loaded."""
    with patch(
        "diapason.speech.faster_whisper.WhisperModel",
        new=None,
    ):
        backend = FasterWhisperBackend()
        assert backend.health() is False
        assert "uv sync --extra desktop" in (backend.last_error() or "")


def test_faster_whisper_health_captures_load_error():
    with patch(
        "diapason.speech.faster_whisper.WhisperModel",
        side_effect=RuntimeError("missing cublas64_12.dll"),
    ):
        backend = FasterWhisperBackend()
        assert backend.health() is False
        assert "missing cublas64_12.dll" in (backend.last_error() or "")


def test_faster_whisper_supported_formats():
    """Backend supports standard audio formats."""
    with patch("diapason.speech.faster_whisper.WhisperModel"):
        from diapason.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        formats = backend.supported_formats()
        assert "wav" in formats
        assert "mp3" in formats
        assert "webm" in formats


# ── language: configured, cached, or detected ────────────────────────────────


class TestEffectiveLanguage:
    """Whisper runs a separate detection pass whenever no language is given.

    On a 4-second French clip that pass costs about as much as the decode
    itself, and it is least reliable exactly where dictation lives — a
    two-second utterance. So the language is resolved once and reused.
    """

    def test_configured_language_wins(self):
        backend = FasterWhisperBackend(language="fr")
        assert backend._effective_language(None) == "fr"

    def test_explicit_call_argument_beats_config(self):
        backend = FasterWhisperBackend(language="fr")
        assert backend._effective_language("en") == "en"

    def test_none_until_something_is_known(self):
        assert FasterWhisperBackend()._effective_language(None) is None

    def test_detected_language_is_reused(self):
        backend = FasterWhisperBackend()
        backend._detected = "fr"
        assert backend._effective_language(None) == "fr"

    def test_auto_forces_detection_every_time(self):
        """The escape hatch for someone who really does switch language."""
        backend = FasterWhisperBackend(language="auto")
        backend._detected = "fr"
        assert backend._effective_language(None) is None

    def test_blank_and_whitespace_are_not_a_language(self):
        assert FasterWhisperBackend(language="   ")._effective_language(None) is None

    def test_detection_is_remembered_after_a_transcription(self):
        mock_info = MagicMock()
        mock_info.language = "fr"
        mock_info.language_probability = 0.99
        mock_info.duration = 4.0
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(()), mock_info)

        with patch(
            "diapason.speech.faster_whisper.WhisperModel", return_value=mock_model
        ):
            backend = FasterWhisperBackend(model_size="base", device="cpu")
            backend.transcribe(b"not a wav")
            assert backend._detected == "fr"

            backend.transcribe(b"not a wav")
            assert mock_model.transcribe.call_args.kwargs["language"] == "fr"

    def test_configured_language_is_never_overwritten_by_detection(self):
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.99
        mock_info.duration = 4.0
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(()), mock_info)

        with patch(
            "diapason.speech.faster_whisper.WhisperModel", return_value=mock_model
        ):
            backend = FasterWhisperBackend(model_size="base", language="fr")
            backend.transcribe(b"not a wav")
            assert backend._detected is None
            assert backend._effective_language(None) == "fr"


# ── the in-memory WAV fast path ──────────────────────────────────────────────


class TestDecodePcmWav:
    """Encoding a float array to WAV, writing it to disk and having PyAV
    decode it back measured ~27% of transcription time — a round trip to
    nowhere, since the dictation path starts with the array."""

    @staticmethod
    def _wav(samples, *, rate=16_000, channels=1, width=2):
        import io
        import struct
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(width)
            w.setframerate(rate)
            w.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in samples))
        return buf.getvalue()

    def test_round_trips_the_dictation_format(self):
        from diapason.speech.faster_whisper import _decode_pcm_wav

        samples = [0.0, 0.5, -0.5, 0.25]
        out = _decode_pcm_wav(self._wav(samples))
        assert out is not None
        assert len(out) == 4
        for got, want in zip(out, samples):
            assert abs(got - want) < 1e-4

    def test_rejects_a_rate_whisper_would_misread(self):
        """A bare sample array carries no rate; the wrong one transposes speech."""
        from diapason.speech.faster_whisper import _decode_pcm_wav

        assert _decode_pcm_wav(self._wav([0.1] * 8, rate=44_100)) is None

    def test_rejects_stereo(self):
        from diapason.speech.faster_whisper import _decode_pcm_wav

        assert _decode_pcm_wav(self._wav([0.1] * 8, channels=2)) is None

    def test_rejects_non_wav_bytes(self):
        from diapason.speech.faster_whisper import _decode_pcm_wav

        assert _decode_pcm_wav(b"definitely not a wav") is None

    def test_rejects_empty_audio(self):
        from diapason.speech.faster_whisper import _decode_pcm_wav

        assert _decode_pcm_wav(self._wav([])) is None

    def test_dictation_output_takes_the_fast_path(self):
        """The format DictationService actually produces must qualify —
        otherwise the optimisation silently never applies."""
        import numpy as np

        from diapason.desktop.dictation_service import float_mono_to_wav
        from diapason.speech.faster_whisper import _decode_pcm_wav

        audio = np.linspace(-0.4, 0.4, 1600, dtype="float32")
        decoded = _decode_pcm_wav(float_mono_to_wav(audio))
        assert decoded is not None
        assert np.abs(decoded - audio).max() < 1e-3

    def test_wav_input_never_touches_the_disk(self):
        import numpy as np

        from diapason.desktop.dictation_service import float_mono_to_wav

        mock_info = MagicMock()
        mock_info.language = "fr"
        mock_info.language_probability = 0.9
        mock_info.duration = 0.1
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(()), mock_info)

        with patch(
            "diapason.speech.faster_whisper.WhisperModel", return_value=mock_model
        ):
            backend = FasterWhisperBackend(model_size="base", language="fr")
            backend.transcribe(float_mono_to_wav(np.zeros(1600, dtype="float32")))

        passed = mock_model.transcribe.call_args.args[0]
        assert not isinstance(passed, str), "a path means it went via a temp file"
        assert len(passed) == 1600


class TestLanguageLatchGuards:
    """A cached language must be earned, not assumed.

    Regression: one uncertain detection on a short first clip latched a
    session to English, and every French sentence afterwards came back
    translated. Whisper does not refuse a wrong language — it renders the
    speech *as* that language. Re-detecting costs a few hundred milliseconds;
    a wrong latch costs every utterance until restart.
    """

    @staticmethod
    def _backend_with(language: str, probability: float, duration: float):
        info = MagicMock()
        info.language = language
        info.language_probability = probability
        info.duration = duration
        model = MagicMock()
        model.transcribe.return_value = (iter(()), info)
        with patch("diapason.speech.faster_whisper.WhisperModel", return_value=model):
            backend = FasterWhisperBackend(model_size="base")
            backend.transcribe(b"not a wav")
        return backend

    def test_an_unsure_detection_does_not_latch(self):
        backend = self._backend_with("en", 0.55, 6.0)
        assert backend._detected is None

    def test_a_short_clip_does_not_latch(self):
        # Detection reads only the first window, so a two-word utterance is
        # exactly where it is least trustworthy.
        backend = self._backend_with("en", 0.99, 0.8)
        assert backend._detected is None

    def test_a_confident_long_detection_does_latch(self):
        backend = self._backend_with("fr", 0.97, 5.0)
        assert backend._detected == "fr"

    def test_thresholds_are_strict_enough_to_matter(self):
        from diapason.speech.faster_whisper import (
            LANGUAGE_LATCH_CONFIDENCE,
            LANGUAGE_LATCH_SECONDS,
        )

        assert LANGUAGE_LATCH_CONFIDENCE >= 0.8
        assert LANGUAGE_LATCH_SECONDS >= 1.5

    def test_a_configured_language_skips_the_guards_entirely(self):
        # Someone who states their language should never pay for detection,
        # nor be at its mercy.
        backend = FasterWhisperBackend(model_size="base", language="fr")
        assert backend._effective_language(None) == "fr"


def _segment(text, no_speech, logprob):
    seg = MagicMock()
    seg.text = text
    seg.start = 0.0
    seg.end = 1.0
    seg.no_speech_prob = no_speech
    seg.avg_logprob = logprob
    return seg


def test_le_merci_fantome_est_raye():
    """Bruit transcrit « Merci. » (23 août 2026) : les deux signaux d'alarme
    s'accordent, le segment tombe ; la vraie phrase à côté survit."""
    mock_model = MagicMock()
    mock_info = MagicMock(language="fr", language_probability=0.95, duration=2.0)
    mock_model.transcribe.return_value = (
        [_segment(" Bonjour Diapason", 0.1, -0.3), _segment(" Merci.", 0.92, -1.6)],
        mock_info,
    )
    with patch(
        "diapason.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        from diapason.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend(model_size="base", device="cpu")
        result = backend.transcribe(b"fake audio bytes")
        assert result.text == "Bonjour Diapason"
        assert [s.text for s in result.segments] == ["Bonjour Diapason"]


def test_un_seul_signal_ne_suffit_pas_a_rejeter():
    """Un vrai « Merci. » clairement prononcé garde un bon logprob ; douter
    de la parole sans douter de la transcription (ou l'inverse) ne raye rien."""
    from diapason.speech.faster_whisper import est_hallucination

    assert est_hallucination(0.92, -1.6) is True
    assert est_hallucination(0.92, -0.4) is False  # transcription sûre
    assert est_hallucination(0.2, -1.6) is False  # parole probable
    assert est_hallucination(0.0, 0.0) is False
