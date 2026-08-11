"""Tests for speech backend auto-discovery."""

from unittest.mock import patch

from diapason.core.config import DiapasonConfig


def test_get_speech_backend_explicit():
    """Explicit backend selection works."""
    from diapason.speech._discovery import get_speech_backend

    config = DiapasonConfig()
    config.speech.backend = "faster-whisper"

    with patch("diapason.speech._discovery._create_backend") as mock_create:
        mock_backend = type(
            "MockBackend",
            (),
            {
                "backend_id": "faster-whisper",
                "health": lambda self: True,
            },
        )()
        mock_create.return_value = mock_backend

        result = get_speech_backend(config)
        assert result is not None
        assert result.backend_id == "faster-whisper"


def test_get_speech_backend_returns_none_if_nothing_available():
    """Returns None when no backend can be created."""
    from diapason.speech._discovery import get_speech_backend

    config = DiapasonConfig()
    config.speech.backend = "nonexistent"

    result = get_speech_backend(config)
    assert result is None


def test_auto_discovery_priority():
    """Auto mode tries backends in priority order."""
    from diapason.speech._discovery import DISCOVERY_ORDER

    assert DISCOVERY_ORDER[0] == "faster-whisper"
    assert "openai" in DISCOVERY_ORDER
    assert "deepgram" in DISCOVERY_ORDER


# ── Local-only mode: the fallback that used to be silent ─────────────────────
#
# The bug these pin down: `_create_backend` swallowed every exception and
# returned None, which auto-discovery could not tell apart from "backend not
# installed". A faster-whisper that failed to load therefore sent the user's
# voice to OpenAI or Deepgram as soon as a key happened to sit in the
# environment. The assertion is that the cloud backend is never *built* — not
# merely that its result is discarded.


_CREATE = "diapason.speech._discovery._create_backend"


def _local_only_config(backend: str = "auto") -> DiapasonConfig:
    config = DiapasonConfig()
    config.speech.backend = backend
    config.privacy.local_only = True
    return config


def test_local_only_never_falls_back_to_cloud_when_the_local_backend_fails():
    from diapason.speech._discovery import get_speech_backend

    attempted: list[str] = []

    def _fake_create(key, config):
        attempted.append(key)
        return None  # faster-whisper is broken; nothing else may be tried

    with patch(_CREATE, side_effect=_fake_create):
        assert get_speech_backend(_local_only_config()) is None

    assert attempted == ["faster-whisper"]
    assert "openai" not in attempted
    assert "deepgram" not in attempted


def test_local_only_refuses_an_explicitly_configured_cloud_backend():
    """An explicit choice does not outrank the global switch."""
    from diapason.speech._discovery import get_speech_backend

    with patch(_CREATE) as mock_create:
        assert get_speech_backend(_local_only_config("deepgram")) is None
    mock_create.assert_not_called()


def test_local_only_still_returns_a_working_local_backend():
    """Counter-proof: the guard refuses the cloud, not the feature."""
    from diapason.speech._discovery import get_speech_backend

    sentinel = object()
    with patch(_CREATE, return_value=sentinel):
        assert get_speech_backend(_local_only_config()) is sentinel


def test_cloud_fallback_still_works_when_local_only_is_off():
    """Counter-proof: default behaviour is unchanged for cloud users."""
    from diapason.speech._discovery import get_speech_backend

    attempted: list[str] = []

    def _fake_create(key, config):
        attempted.append(key)
        return "a-backend" if key == "openai" else None

    config = DiapasonConfig()
    config.speech.backend = "auto"
    config.privacy.local_only = False

    with patch(_CREATE, side_effect=_fake_create):
        assert get_speech_backend(config) == "a-backend"

    assert attempted == ["faster-whisper", "openai"]
