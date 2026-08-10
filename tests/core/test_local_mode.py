"""Local-only mode is a contract — the ratchet that keeps it honest.

Three outbound paths used to decide on their own whether they were allowed to
leave the machine, and each of them got it wrong in a different way:

* speech auto-discovery treated a broken local backend as an absent one and
  walked on to OpenAI and Deepgram;
* dictation polish sent every sentence to whatever engine the config named,
  local or not;
* screen vision wrote a full-screen temp file first and refused afterwards.

The assertions below are therefore not "the call failed" but "the call never
happened": no backend built, no engine invoked, no image produced. A guard
that lets the work start and merely discards the result would satisfy a naive
test and break the promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from diapason.core.local_mode import engine_is_local, local_only

# ── Doubles ──────────────────────────────────────────────────────────────────


@dataclass
class _Privacy:
    local_only: bool = False


@dataclass
class _Cfg:
    privacy: _Privacy


def _cfg(local: bool) -> _Cfg:
    return _Cfg(privacy=_Privacy(local_only=local))


class _Engine:
    def __init__(self, engine_id: str, is_cloud: bool | None = None):
        self.engine_id = engine_id
        if is_cloud is not None:
            self.is_cloud = is_cloud


# ── local_only() ─────────────────────────────────────────────────────────────


def test_local_only_reads_the_privacy_section():
    assert local_only(_cfg(True)) is True
    assert local_only(_cfg(False)) is False


def test_local_only_fails_closed_when_config_is_unreadable():
    """Cost asymmetry: a wrong "no" costs a feature, a wrong "yes" costs the data."""
    def _boom(self):
        raise RuntimeError("config unreadable")

    broken = MagicMock()
    type(broken).privacy = property(_boom)
    assert local_only(broken) is True


def test_local_only_fails_closed_on_a_config_without_privacy_section():
    """An object predating [privacy] is not evidence that sending is allowed."""

    @dataclass
    class _Old:
        engine: str = "ollama"

    assert local_only(_Old()) is True


def test_local_only_loads_the_active_config_when_none_is_passed():
    with patch("diapason.core.config.load_config", return_value=_cfg(True)) as loader:
        assert local_only() is True
    loader.assert_called_once()


# ── engine_is_local() ────────────────────────────────────────────────────────


def test_engine_is_local_trusts_the_explicit_flag_first():
    assert engine_is_local(_Engine("ollama", is_cloud=False)) is True
    assert engine_is_local(_Engine("ollama", is_cloud=True)) is False


def test_engine_is_local_falls_back_to_the_id():
    assert engine_is_local(_Engine("ollama")) is True
    assert engine_is_local(_Engine("openai")) is False


def test_an_unknown_engine_is_treated_as_remote():
    """An unrecognised backend is not a local one — silence is not consent."""
    assert engine_is_local(_Engine("some-new-backend")) is False
    assert engine_is_local(_Engine("")) is False
    assert engine_is_local(None) is False


# ── The switch must actually be reachable from a config file ─────────────────


def test_privacy_section_is_loaded_from_toml(tmp_path):
    """A privacy switch the config file cannot set is worse than none.

    `load_config` applies an explicit, hand-maintained tuple of top-level
    sections. `[privacy]` was missing from it at first, so `local_only = true`
    in a real config.toml parsed fine and was silently discarded — the mode
    could only ever be turned on from Python. This pins the wiring.
    """
    from diapason.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text("[privacy]\nlocal_only = true\n", encoding="utf-8")

    cfg = load_config(path)
    assert cfg.privacy.local_only is True
    assert local_only(cfg) is True


def test_privacy_key_is_settable_from_the_cli():
    """`jarvis config set privacy.local_only true` must validate."""
    from diapason.core.config import validate_config_key

    assert validate_config_key("privacy.local_only") is bool


# ── host_is_local: what counts as "not leaving" ──────────────────────────────


def test_loopback_is_local():
    from diapason.core.local_mode import host_is_local

    for url in (
        "http://localhost:11434",
        "http://127.0.0.1:8000/v1/chat",
        "http://[::1]:8079",
        "localhost:11434",
        "http://api.localhost:3000",
    ):
        assert host_is_local(url) is True, url


def test_a_lan_address_is_not_local():
    """192.168.1.50 is someone else's computer, not this one."""
    from diapason.core.local_mode import host_is_local

    for url in (
        "http://192.168.1.50:11434",
        "http://10.0.0.7:8000",
        "https://api.openai.com/v1",
        "https://generativelanguage.googleapis.com",
    ):
        assert host_is_local(url) is False, url


def test_unparseable_or_empty_hosts_are_not_local():
    """A host we cannot read is not a host we can vouch for."""
    from diapason.core.local_mode import host_is_local

    assert host_is_local("") is False
    assert host_is_local("   ") is False
    assert host_is_local("http://") is False


def test_unix_sockets_are_local():
    from diapason.core.local_mode import host_is_local

    assert host_is_local("/var/run/diapason.sock") is True
    assert host_is_local("unix:///tmp/x.sock") is True


# ── assert_may_leave: raises so a caller cannot forget to branch ─────────────


def test_assert_may_leave_raises_under_local_only():
    from diapason.core.local_mode import LocalOnlyError, assert_may_leave

    with pytest.raises(LocalOnlyError) as excinfo:
        assert_may_leave(
            "the dictated text", destination="https://api.openai.com", config=_cfg(True)
        )
    assert excinfo.value.nothing_left_the_machine is True


def test_assert_may_leave_is_silent_for_loopback_even_under_local_only():
    """Guarding a path that never left costs nothing."""
    from diapason.core.local_mode import assert_may_leave

    assert_may_leave(
        "the prompt", destination="http://localhost:11434", config=_cfg(True)
    )


def test_assert_may_leave_is_silent_when_local_only_is_off():
    from diapason.core.local_mode import assert_may_leave

    assert_may_leave(
        "the prompt", destination="https://api.openai.com", config=_cfg(False)
    )


def test_assert_may_leave_refuses_an_unknown_destination_under_local_only():
    """No destination given means no proof it was loopback."""
    from diapason.core.local_mode import LocalOnlyError, assert_may_leave

    with pytest.raises(LocalOnlyError):
        assert_may_leave("the screenshot", config=_cfg(True))
