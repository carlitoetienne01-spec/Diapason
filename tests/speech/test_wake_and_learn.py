"""Tests for wake ML resolve, dictionary auto-learn, backends."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.speech.dictation_dictionary import (
    DictionaryEntry,
    apply_dictionary,
    learn_from_correction,
    load_dictionary,
    save_dictionary,
)
from openjarvis.speech.wakeword import (
    WakeListenConfig,
    WakeWordListener,
    resolve_backend,
)


def test_resolve_backend_phrase_gate():
    assert resolve_backend("phrase_gate") == "phrase_gate"


def test_resolve_backend_openwakeword_missing():
    # Without openwakeword installed, explicit backend should raise
    try:
        import openwakeword  # noqa: F401

        pytest.skip("openwakeword installed in this env")
    except ImportError:
        pass
    with pytest.raises(ImportError):
        resolve_backend("openwakeword")


def test_resolve_backend_auto_falls_back():
    # auto never raises — falls back if missing
    assert resolve_backend("auto") in ("openwakeword", "phrase_gate")


def test_wake_check_text_fires():
    hits: list[str] = []
    listener = WakeWordListener(
        hits.append,
        cfg=WakeListenConfig(cooldown_s=0.0, phrases=("jarvis", "hey jarvis")),
        once=False,
    )
    assert listener.check_text("Hey Jarvis") is True
    assert hits
    assert listener.check_text("bonjour") is False


def test_learn_from_correction(tmp_path: Path):
    path = tmp_path / "dict.json"
    save_dictionary([], path)
    learned = learn_from_correction(
        "meet with carlos tomorrow",
        "meet with Carlito tomorrow",
        path=path,
    )
    assert learned
    entries = load_dictionary(path)
    assert any(e.word == "Carlito" for e in entries)
    applied = apply_dictionary(
        "I spoke to carlos yesterday", path=path, bump_usage=False
    )
    assert "Carlito" in applied


def test_learn_skips_fillers(tmp_path: Path):
    path = tmp_path / "dict.json"
    save_dictionary([], path)
    learned = learn_from_correction("um hello there", "hello there", path=path)
    # delete opcodes only — no replace of learnable tokens required
    assert learned == [] or all(e.context == "auto-learn" for e in learned)


def test_apply_bumps_usage(tmp_path: Path):
    path = tmp_path / "dict.json"
    save_dictionary(
        [
            DictionaryEntry(
                word="OpenJarvis",
                original_word="open jarvis",
                replacements=["open jarvis"],
                usage_count=0,
            )
        ],
        path,
    )
    apply_dictionary("try open jarvis now", path=path, bump_usage=True)
    entries = load_dictionary(path)
    assert entries[0].usage_count >= 1
