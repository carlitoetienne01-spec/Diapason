"""Tests for TTS backend infrastructure."""

from __future__ import annotations

from unittest.mock import patch

from diapason.core.registry import TTSRegistry
from diapason.speech.tts import TTSResult

# ---------------------------------------------------------------------------
# TTSResult tests
# ---------------------------------------------------------------------------


def test_tts_result_dataclass():
    result = TTSResult(
        audio=b"fake-audio-bytes",
        format="mp3",
        duration_seconds=3.5,
        voice_id="jarvis-v1",
    )
    assert result.audio == b"fake-audio-bytes"
    assert result.format == "mp3"
    assert result.duration_seconds == 3.5


def test_tts_result_save(tmp_path):
    result = TTSResult(audio=b"fake-mp3-data", format="mp3")
    out = result.save(tmp_path / "test.mp3")
    assert out.exists()
    assert out.read_bytes() == b"fake-mp3-data"


# ---------------------------------------------------------------------------
# Cartesia backend tests
# ---------------------------------------------------------------------------


def test_cartesia_registered():
    from diapason.speech.cartesia_tts import CartesiaTTSBackend

    TTSRegistry.register_value("cartesia", CartesiaTTSBackend)
    assert TTSRegistry.contains("cartesia")


def test_cartesia_synthesize():
    from diapason.speech.cartesia_tts import CartesiaTTSBackend

    backend = CartesiaTTSBackend(api_key="fake-key")

    with patch(
        "diapason.speech.cartesia_tts._cartesia_synthesize",
        return_value=b"fake-audio-mp3-bytes",
    ):
        result = backend.synthesize("Hello world", voice_id="test-voice")

    assert result.audio == b"fake-audio-mp3-bytes"
    assert result.format == "mp3"
    assert result.voice_id == "test-voice"


# ---------------------------------------------------------------------------
# Kokoro backend tests
# ---------------------------------------------------------------------------


def test_kokoro_registered():
    from diapason.speech.kokoro_tts import KokoroTTSBackend

    TTSRegistry.register_value("kokoro", KokoroTTSBackend)
    assert TTSRegistry.contains("kokoro")


def test_kokoro_health_false_without_package():
    from diapason.speech.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    # Without kokoro installed, health returns False
    assert backend.health() is False


# ---------------------------------------------------------------------------
# OpenAI TTS backend tests
# ---------------------------------------------------------------------------


def test_openai_tts_registered():
    from diapason.speech.openai_tts import OpenAITTSBackend

    TTSRegistry.register_value("openai_tts", OpenAITTSBackend)
    assert TTSRegistry.contains("openai_tts")


def test_openai_tts_synthesize():
    from diapason.speech.openai_tts import OpenAITTSBackend

    backend = OpenAITTSBackend(api_key="fake-key")

    with patch(
        "diapason.speech.openai_tts._openai_tts_request",
        return_value=b"fake-openai-audio",
    ):
        result = backend.synthesize("Hello", voice_id="nova")

    assert result.audio == b"fake-openai-audio"
    assert result.voice_id == "nova"


# ---------------------------------------------------------------------------
# ElevenLabs TTS backend tests
# ---------------------------------------------------------------------------


def test_elevenlabs_registered():
    from diapason.speech.elevenlabs_tts import ElevenLabsTTSBackend

    TTSRegistry.register_value("elevenlabs", ElevenLabsTTSBackend)
    assert TTSRegistry.contains("elevenlabs")


def test_elevenlabs_synthesize_and_cache(tmp_path):
    from diapason.speech.elevenlabs_tts import ElevenLabsTTSBackend

    backend = ElevenLabsTTSBackend(
        api_key="fake-key",
        model_id="eleven_multilingual_v2",
        cache_enabled=True,
        cache_dir=tmp_path,
    )

    with patch(
        "diapason.speech.elevenlabs_tts._elevenlabs_tts_request",
        return_value=b"fake-el-audio",
    ) as mock_req:
        result = backend.synthesize("Welcome home", voice_id="voice123")
        assert result.audio == b"fake-el-audio"
        assert result.metadata.get("cache") == "miss"
        assert mock_req.call_count == 1

        result2 = backend.synthesize("Welcome home", voice_id="voice123")
        assert result2.audio == b"fake-el-audio"
        assert result2.metadata.get("cache") == "hit"
        assert mock_req.call_count == 1


def test_elevenlabs_health_requires_key():
    from diapason.speech.elevenlabs_tts import ElevenLabsTTSBackend

    assert ElevenLabsTTSBackend(api_key="").health() is False
    assert ElevenLabsTTSBackend(api_key="sk").health() is True
