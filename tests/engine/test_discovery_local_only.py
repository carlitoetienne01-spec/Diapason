"""Engine construction obeys local-only mode — the widest single guard.

Every path that reaches a cloud model resolves its engine through
``_make_engine``: chat, ask, agents, deep research, dictation polish, vision,
the HTTP server. Guarding the call sites instead would have meant guarding ten
of them and forgetting the eleventh.

The decisive assertion is not "the engine was not used" but "the engine was
never built". ``CloudEngine.__init__`` reads eight API-key environment
variables in its constructor, so a guard that lets construction happen and
refuses afterwards has already touched every credential on the machine. The
tests below therefore assert that ``EngineRegistry.get`` — the step before
instantiation — is never even reached.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from diapason.core.config import JarvisConfig
from diapason.core.local_mode import LocalOnlyError
from diapason.engine._discovery import _engine_key_is_remote, _make_engine

_REGISTRY_GET = "diapason.core.registry.EngineRegistry.get"


def _cfg(*, local: bool, ollama_host: str = "") -> JarvisConfig:
    config = JarvisConfig()
    config.privacy.local_only = local
    if ollama_host:
        config.engine.ollama_host = ollama_host
    return config


# ── Which keys mean "another machine" ────────────────────────────────────────


def test_cloud_and_litellm_are_remote_whatever_the_config():
    config = _cfg(local=True)
    assert _engine_key_is_remote("cloud", config) is True
    assert _engine_key_is_remote("litellm", config) is True


def test_in_process_engine_is_never_remote():
    assert _engine_key_is_remote("gemma_cpp", _cfg(local=True)) is False


def test_host_engines_are_judged_on_their_host_not_their_name():
    """The same Ollama is local on loopback and remote on the LAN."""
    assert _engine_key_is_remote("ollama", _cfg(local=True)) is False
    assert (
        _engine_key_is_remote(
            "ollama", _cfg(local=True, ollama_host="http://localhost:11434")
        )
        is False
    )
    assert (
        _engine_key_is_remote(
            "ollama", _cfg(local=True, ollama_host="http://192.168.1.50:11434")
        )
        is True
    )


# ── Refusal happens before construction ──────────────────────────────────────


def test_cloud_engine_is_never_constructed_under_local_only():
    with patch(_REGISTRY_GET) as registry_get:
        with pytest.raises(LocalOnlyError):
            _make_engine("cloud", _cfg(local=True))
    registry_get.assert_not_called()


def test_lan_ollama_is_refused_before_construction():
    config = _cfg(local=True, ollama_host="http://192.168.1.50:11434")
    with patch(_REGISTRY_GET) as registry_get:
        with pytest.raises(LocalOnlyError):
            _make_engine("ollama", config)
    registry_get.assert_not_called()


def test_the_error_says_nothing_left_the_machine():
    with patch(_REGISTRY_GET):
        with pytest.raises(LocalOnlyError) as excinfo:
            _make_engine("cloud", _cfg(local=True))
    assert excinfo.value.nothing_left_the_machine is True


# ── Counter-proofs: the guard refuses the cloud, not the feature ─────────────


def test_local_engine_is_still_built_under_local_only():
    sentinel = MagicMock()
    with patch(_REGISTRY_GET, return_value=lambda **_: sentinel) as registry_get:
        assert _make_engine("ollama", _cfg(local=True)) is sentinel
    registry_get.assert_called_once_with("ollama")


def test_cloud_engine_is_still_built_when_local_only_is_off():
    sentinel = MagicMock()
    with patch(_REGISTRY_GET, return_value=lambda **_: sentinel):
        assert _make_engine("cloud", _cfg(local=False)) is sentinel


def test_discovery_skips_remote_engines_instead_of_crashing():
    """`_probe` catches the refusal, so a cloud engine simply vanishes."""
    from diapason.engine._discovery import discover_engines

    config = _cfg(local=True)
    healthy = MagicMock()
    healthy.health.return_value = True

    def _fake_get(key):
        return lambda **_: healthy

    keys_at = "diapason.core.registry.EngineRegistry.keys"
    with patch(keys_at, return_value=["cloud", "ollama"]):
        with patch(_REGISTRY_GET, side_effect=_fake_get):
            found = dict(discover_engines(config))

    assert "cloud" not in found
    assert "ollama" in found
