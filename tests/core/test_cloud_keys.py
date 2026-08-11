"""The Keychain fallback: env wins, values never leak, names are validated."""

from __future__ import annotations

import subprocess

import pytest

from diapason.core import cloud_keys


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    cloud_keys._cache.clear()
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    yield
    cloud_keys._cache.clear()


def _fake_security(monkeypatch, values):
    """Stub the security CLI: values maps account name -> stored secret."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        account = cmd[cmd.index("-a") + 1]
        if account in values:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=values[account] + "\n", stderr=""
            )
        return subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")

    monkeypatch.setattr(cloud_keys.subprocess, "run", fake_run)
    monkeypatch.setattr(cloud_keys.sys, "platform", "darwin")
    return calls


def test_environment_wins_over_keychain(monkeypatch):
    # A deliberate env override must keep working — that is the existing
    # contract with the app's own injection.
    calls = _fake_security(monkeypatch, {"GEMINI_API_KEY": "from-keychain"})
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert cloud_keys.get_cloud_key("GEMINI_API_KEY") == "from-env"
    assert calls == [], "the keychain must not even be consulted"


def test_falls_back_to_keychain(monkeypatch):
    _fake_security(monkeypatch, {"GEMINI_API_KEY": "sk-stored"})
    assert cloud_keys.get_cloud_key("GEMINI_API_KEY") == "sk-stored"


def test_tries_names_in_order(monkeypatch):
    # GOOGLE_API_KEY is the legacy spelling; it must still be honoured when
    # GEMINI_API_KEY is absent everywhere.
    _fake_security(monkeypatch, {"GOOGLE_API_KEY": "sk-google"})
    assert cloud_keys.get_cloud_key("GEMINI_API_KEY", "GOOGLE_API_KEY") == "sk-google"


def test_missing_everywhere_is_empty(monkeypatch):
    _fake_security(monkeypatch, {})
    assert cloud_keys.get_cloud_key("GEMINI_API_KEY") == ""


def test_result_is_cached_briefly(monkeypatch):
    calls = _fake_security(monkeypatch, {"GEMINI_API_KEY": "sk-x"})
    cloud_keys.get_cloud_key("GEMINI_API_KEY")
    cloud_keys.get_cloud_key("GEMINI_API_KEY")
    assert len(calls) == 1, "a burst of health checks must not spawn one process each"


def test_invalid_names_never_reach_a_subprocess(monkeypatch):
    calls = _fake_security(monkeypatch, {})
    assert cloud_keys.get_cloud_key("weird; rm -rf /") == ""
    assert cloud_keys.get_cloud_key("lowercase_api_key") == ""
    assert cloud_keys.get_cloud_key("NOT_A_KEY_NAME") == ""
    assert calls == []


def test_non_darwin_skips_the_keychain(monkeypatch):
    calls = _fake_security(monkeypatch, {"GEMINI_API_KEY": "sk-x"})
    monkeypatch.setattr(cloud_keys.sys, "platform", "linux")
    assert cloud_keys.get_cloud_key("GEMINI_API_KEY") == ""
    assert calls == []


def test_a_broken_security_binary_degrades_to_absent(monkeypatch):
    def boom(cmd, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(cloud_keys.subprocess, "run", boom)
    monkeypatch.setattr(cloud_keys.sys, "platform", "darwin")
    assert cloud_keys.get_cloud_key("GEMINI_API_KEY") == ""


def test_key_values_never_reach_the_logger(monkeypatch, caplog):
    _fake_security(monkeypatch, {"GEMINI_API_KEY": "sk-SECRET-VALUE"})
    with caplog.at_level("DEBUG"):
        cloud_keys.get_cloud_key("GEMINI_API_KEY")
    assert "sk-SECRET-VALUE" not in caplog.text
