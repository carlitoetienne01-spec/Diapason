"""Tests for dictate polish, monitors, and voice commands."""

from __future__ import annotations

from diapason.desktop.voice_commands import (
    finalize_dictation,
    is_explicit_voice_command,
    parse_voice_command,
)
from diapason.speech.dictate_polish import polish_dictation


def test_polish_removes_fillers():
    out = polish_dictation("um hello uh world like yeah")
    assert "um" not in out.lower()
    assert "uh" not in out.lower()
    assert "Hello" in out or "hello" in out.lower()


def test_spoken_dot_md():
    out = polish_dictation("see the readme dot md now")
    assert "readme.md" in out.lower()


def test_parse_open_cursor():
    a = parse_voice_command("ouvre Cursor")
    assert a.kind == "focus_app"
    assert a.target == "Cursor"


def test_parse_whispered_french_open_notes_variant():
    a = parse_voice_command("Ouvres-moi l'application note")
    assert a.kind == "focus_app"
    assert a.target == "Notes"
    assert is_explicit_voice_command("Ouvres-moi l'application note")


def test_bare_app_name_is_not_an_explicit_action():
    # Critical for silence hallucinations such as the reported "Google Chrome".
    assert parse_voice_command("Google Chrome").kind == "focus_app"
    assert not is_explicit_voice_command("Google Chrome")


def test_parse_search():
    a = parse_voice_command("cherche météo Paris")
    assert a.kind == "search"
    assert "météo" in a.target.lower() or "paris" in a.target.lower()


def test_parse_open_unknown_app_uses_open_anything():
    a = parse_voice_command("ouvre SuperObscureApp")
    assert a.kind == "open_anything"
    assert "SuperObscureApp" in a.target


def test_parse_open_url():
    a = parse_voice_command("open https://example.com")
    assert a.kind == "open_uri"
    assert "example.com" in a.target


def test_finalize_command_vs_paste():
    cmd = finalize_dictation("open Spotify", polish=True)
    assert cmd["mode"] == "command"
    paste = finalize_dictation("um this is a longer note for pasting", polish=True)
    assert paste["mode"] == "paste"
    assert "um" not in paste["text"].lower()


def test_monitor_bounds_smoke():
    from diapason.desktop.monitors import monitor_bounds, sorted_monitor_rects

    rects = sorted_monitor_rects()
    assert len(rects) >= 1
    b = monitor_bounds(1)
    assert b[2] > b[0] and b[3] > b[1]
