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

from openjarvis.core.local_mode import engine_is_local, local_only

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
    with patch("openjarvis.core.config.load_config", return_value=_cfg(True)) as loader:
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
    from openjarvis.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text("[privacy]\nlocal_only = true\n", encoding="utf-8")

    cfg = load_config(path)
    assert cfg.privacy.local_only is True
    assert local_only(cfg) is True


def test_privacy_key_is_settable_from_the_cli():
    """`jarvis config set privacy.local_only true` must validate."""
    from openjarvis.core.config import validate_config_key

    assert validate_config_key("privacy.local_only") is bool
