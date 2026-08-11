"""Env var resolution — the new name wins, the old ones keep working."""

from __future__ import annotations

import pytest

from diapason.core import env


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for spelling in ("DIAPASON_HOME", "OPENJARVIS_HOME", "JARVIS_HOME"):
        monkeypatch.delenv(spelling, raising=False)
    env._warned.clear()
    yield


def test_new_name_is_read(monkeypatch):
    monkeypatch.setenv("DIAPASON_HOME", "/new")
    assert env.get("HOME") == "/new"


def test_legacy_openjarvis_still_works(monkeypatch):
    """A shell profile exporting the old name must not break silently."""
    monkeypatch.setenv("OPENJARVIS_HOME", "/legacy")
    assert env.get("HOME") == "/legacy"


def test_legacy_jarvis_prefix_still_works(monkeypatch):
    """Both prefixes existed (OPENJARVIS_HOME but JARVIS_NUM_CTX)."""
    monkeypatch.setenv("JARVIS_HOME", "/legacy2")
    assert env.get("HOME") == "/legacy2"


def test_new_name_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("DIAPASON_HOME", "/new")
    monkeypatch.setenv("OPENJARVIS_HOME", "/old")
    assert env.get("HOME") == "/new"


def test_openjarvis_wins_over_jarvis(monkeypatch):
    """Deterministic order when both legacy spellings are set."""
    monkeypatch.setenv("OPENJARVIS_HOME", "/a")
    monkeypatch.setenv("JARVIS_HOME", "/b")
    assert env.get("HOME") == "/a"


def test_default_when_nothing_set():
    assert env.get("HOME") is None
    assert env.get("HOME", "/fallback") == "/fallback"


def test_empty_string_is_a_value_not_absence(monkeypatch):
    """An explicitly emptied variable must not fall through to the old one."""
    monkeypatch.setenv("DIAPASON_HOME", "")
    monkeypatch.setenv("OPENJARVIS_HOME", "/old")
    assert env.get("HOME") == ""


def test_is_set_covers_every_spelling(monkeypatch):
    assert env.is_set("HOME") is False
    monkeypatch.setenv("JARVIS_HOME", "/x")
    assert env.is_set("HOME") is True


def test_names_lists_new_first():
    assert env.names("HOME") == (
        "DIAPASON_HOME",
        "OPENJARVIS_HOME",
        "JARVIS_HOME",
    )


def test_legacy_use_is_logged_once(monkeypatch, caplog):
    monkeypatch.setenv("OPENJARVIS_HOME", "/legacy")
    with caplog.at_level("DEBUG", logger="diapason.core.env"):
        env.get("HOME")
        env.get("HOME")
    hits = [r for r in caplog.records if "OPENJARVIS_HOME" in r.getMessage()]
    assert len(hits) == 1, "the deprecation note must not spam every read"
