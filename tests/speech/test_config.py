"""Tests for speech configuration."""

from diapason.core.config import DiapasonConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"
    assert cfg.realtime.enabled is True
    # Local is the shipped default: the product promises « rien ne quitte ce
    # Mac », so the cloud providers are the opt-in, never the reverse.
    assert cfg.realtime.provider == "local"


def test_jarvis_config_has_speech():
    cfg = DiapasonConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_jarvis_system_has_speech_backend():
    """DiapasonSystem has a speech_backend attribute."""
    from diapason.system import DiapasonSystem

    assert "speech_backend" in DiapasonSystem.__dataclass_fields__
