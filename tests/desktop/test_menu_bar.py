"""The status-menu model — everything decidable without a screen."""

from __future__ import annotations

from openjarvis.desktop import menu_bar
from openjarvis.desktop.menu_bar import DictationMenuBar, build_menu, title_for


def _labels(items):
    return [i.label for i in items]


def _actions(items):
    return [i.action for i in items if i.action]


def test_title_reflects_what_the_service_is_doing():
    assert title_for("recording") == menu_bar.RECORDING_TITLE
    assert title_for("transcribing") == menu_bar.WORKING_TITLE
    assert title_for("pasting") == menu_bar.WORKING_TITLE
    assert title_for("idle") == menu_bar.IDLE_TITLE


def test_unknown_state_falls_back_to_idle():
    """A status icon is never worth crashing a running service over."""
    assert title_for("something new") == menu_bar.IDLE_TITLE
    assert title_for("") == menu_bar.IDLE_TITLE


def test_menu_tells_you_the_hotkey():
    items = build_menu(hotkey="control")
    assert "Hold Control to dictate" in _labels(items)


def test_menu_says_so_when_dictation_is_not_running():
    items = build_menu(hotkey="control", running=False)
    assert "Dictation is not running" in _labels(items)


def test_last_transcript_is_offered_for_copying():
    """The answer to 'it pasted into the wrong window'."""
    items = build_menu(hotkey="control", last_text="bonjour le monde")
    assert "copy_last" in _actions(items)
    assert any("bonjour le monde" in lbl for lbl in _labels(items))


def test_a_long_transcript_is_truncated_in_the_menu():
    long_text = "a" * 200
    items = build_menu(hotkey="control", last_text=long_text)
    preview = next(lbl for lbl in _labels(items) if lbl.startswith("Last:"))
    assert len(preview) < 80
    assert preview.endswith("…")


def test_no_copy_option_before_the_first_dictation():
    items = build_menu(hotkey="control", last_text="")
    assert "copy_last" not in _actions(items)
    assert "No dictation yet" in _labels(items)


def test_menu_always_offers_history_and_quit():
    for last in ("", "quelque chose"):
        actions = _actions(build_menu(hotkey="control", last_text=last))
        assert "open_history" in actions
        assert "quit" in actions


def test_set_state_is_safe_before_the_ui_exists():
    """Status updates arrive from the dictation thread, possibly headless."""
    bar = DictationMenuBar(hotkey="control")
    bar.set_state("recording")  # must not raise with no rumps app


def test_copy_to_clipboard_ignores_empty_text():
    assert menu_bar.copy_to_clipboard("") is False
