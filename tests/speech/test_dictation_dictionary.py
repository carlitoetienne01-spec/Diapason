"""Tests for user dictation dictionary + polish pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from openjarvis.desktop.voice_commands import finalize_dictation, parse_voice_command
from openjarvis.speech.dictate_polish import polish_dictation, polish_pipeline
from openjarvis.speech.dictation_dictionary import (
    DictionaryEntry,
    apply_dictionary,
    save_dictionary,
)
from openjarvis.speech.llm_polish import llm_polish_text


def test_polish_removes_fillers_en_fr():
    en = polish_dictation("um hello uh world like yeah")
    assert "um" not in en.lower()
    assert "uh" not in en.lower()
    fr = polish_dictation("euh bonjour du coup ça va")
    assert "euh" not in fr.lower()
    assert "du coup" not in fr.lower()


def test_spoken_dot_extension():
    assert "readme.md" in polish_dictation("open the readme dot md file please").lower()


def test_dictionary_replacement(tmp_path: Path):
    path = tmp_path / "dict.json"
    save_dictionary(
        [
            DictionaryEntry(
                word="OpenAI",
                replacements=["open ai", "open a i"],
                usage_count=5,
            ),
            DictionaryEntry(
                word="Kubernetes",
                original_word="cooper netes",
                replacements=["kube netes"],
            ),
        ],
        path=path,
    )
    out = apply_dictionary("we use open ai and cooper netes daily", path=path)
    assert "OpenAI" in out
    assert "Kubernetes" in out


def test_dictionary_longer_keys_first(tmp_path: Path):
    path = tmp_path / "dict.json"
    save_dictionary(
        [
            DictionaryEntry(word="AI", replacements=["ai"]),
            DictionaryEntry(word="OpenAI", replacements=["open ai"]),
        ],
        path=path,
    )
    out = apply_dictionary("try open ai today", path=path)
    assert "OpenAI" in out


def test_polish_pipeline_with_dictionary(tmp_path: Path):
    path = tmp_path / "dict.json"
    save_dictionary(
        [DictionaryEntry(word="Diapason", replacements=["diapazon"])],
        path=path,
    )
    text = polish_pipeline(
        "um diapazon is ready",
        polish=True,
        use_dictionary=True,
        llm_polish=False,
        dictionary_path=str(path),
    )
    assert "Diapason" in text
    assert "um" not in text.lower()


def test_command_untouched_by_polish():
    cmd = finalize_dictation("open Spotify", polish=True, llm_polish=False)
    assert cmd["mode"] == "command"
    assert cmd["text"] == "open Spotify"


def test_command_with_filler_still_command():
    # Filler strip retry for command parse
    with patch(
        "openjarvis.desktop.voice_commands.execute_voice_action",
        return_value={"handled": True, "kind": "focus_app", "success": True},
    ):
        cmd = finalize_dictation("um open Spotify", polish=True, llm_polish=False)
    assert cmd["mode"] == "command"


def test_paste_path_polishes():
    paste = finalize_dictation(
        "um this is a longer note for pasting into the editor",
        polish=True,
        llm_polish=False,
        use_dictionary=False,
    )
    assert paste["mode"] == "paste"
    assert "um" not in paste["text"].lower()


def test_polish_false_returns_rawish():
    raw = "um keep fillers please here"
    paste = finalize_dictation(raw, polish=False, llm_polish=False, use_dictionary=False)
    assert paste["mode"] == "paste"
    assert paste["text"] == raw.strip()


def test_llm_polish_mock_engine():
    engine = MagicMock()
    engine.generate.return_value = {"content": "Hello world, this is clean."}
    with patch("openjarvis.core.config.load_config") as load:
        cfg = MagicMock()
        cfg.intelligence.default_model = "test-model"
        cfg.engine.default = "ollama"
        load.return_value = cfg
        out = llm_polish_text(
            "um hello world this is messy text",
            engine=engine,
            timeout_ms=2000,
        )
    assert out is not None
    assert "Hello" in out
    engine.generate.assert_called_once()


def test_llm_polish_timeout_returns_none():
    engine = MagicMock()

    def slow(*_a, **_k):
        import time

        time.sleep(2)
        return {"content": "late"}

    engine.generate.side_effect = slow
    with patch("openjarvis.core.config.load_config") as load:
        cfg = MagicMock()
        cfg.intelligence.default_model = "test-model"
        cfg.engine.default = "ollama"
        load.return_value = cfg
        out = llm_polish_text("one two three four five", engine=engine, timeout_ms=100)
    assert out is None


def test_parse_still_works():
    assert parse_voice_command("ouvre Cursor").kind == "focus_app"
