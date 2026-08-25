"""Headless tests for the push-to-talk dictation stack.

Everything here runs without a microphone, a keyboard tap, or Accessibility
permission — the live I/O lives in thin wrappers, and the logic that decides
*what to do* is pure. That separation is the point: the behaviour a user feels
(hold to dictate, double-tap for hands-free, clipboard survives) is pinned by
tests, not left to a device.
"""

from __future__ import annotations

import numpy as np

from diapason.desktop import clipboard, keycodes, mic_capture
from diapason.desktop.ptt import Action, PushToTalk, State

# ── keycodes ─────────────────────────────────────────────────────────────────


def test_unknown_hotkey_falls_back_to_control():
    assert keycodes.normalize_hotkey("") == "control"
    assert keycodes.normalize_hotkey("banana") == "control"
    assert keycodes.normalize_hotkey("OPTION") == "option"


def test_keycode_matches_left_and_right_modifier():
    assert keycodes.keycode_matches("control", 59) is True
    assert keycodes.keycode_matches("control", 62) is True  # right control
    assert keycodes.keycode_matches("control", 55) is False  # command


def test_bare_press_rejects_a_chord():
    ctrl = keycodes.FLAG_MASKS["control"]
    cmd = keycodes.FLAG_MASKS["command"]
    assert keycodes.is_bare_press("control", ctrl) is True
    # Cmd+Control is a chord for the app in front, not a dictation trigger.
    assert keycodes.is_bare_press("control", ctrl | cmd) is False


def test_flags_change_classifies_down_and_up():
    ctrl = keycodes.FLAG_MASKS["control"]
    assert keycodes.classify_flags_change("control", 59, ctrl) == "down"
    assert keycodes.classify_flags_change("control", 59, 0) == "up"
    assert keycodes.classify_flags_change("control", 55, ctrl) is None  # wrong key


# ── push-to-talk state machine ───────────────────────────────────────────────


def test_hold_and_release_transcribes():
    ptt = PushToTalk()
    assert ptt.down(0.0) == [Action.START]
    assert ptt.state is State.PTT_HELD
    assert ptt.up(0.8) == [Action.STOP_AND_TRANSCRIBE]
    assert ptt.state is State.IDLE


def test_double_tap_enters_hands_free_and_cancels_the_tiny_first_clip():
    ptt = PushToTalk()
    ptt.down(0.0)  # first tap down
    ptt.up(0.05)  # first tap up (tiny)
    actions = ptt.down(0.2)  # second tap within the window
    assert actions == [Action.CANCEL, Action.START_HANDS_FREE]
    assert ptt.state is State.HANDS_FREE


def test_release_does_not_stop_hands_free():
    ptt = PushToTalk()
    ptt.down(0.0)
    ptt.up(0.05)
    ptt.down(0.2)  # -> hands free
    assert ptt.up(0.25) == []  # releasing keeps it running
    assert ptt.state is State.HANDS_FREE


def test_tap_stops_hands_free_and_transcribes():
    ptt = PushToTalk()
    ptt.down(0.0)
    ptt.up(0.05)
    ptt.down(0.2)  # -> hands free
    assert ptt.down(3.0) == [Action.STOP_HANDS_FREE_AND_TRANSCRIBE]
    assert ptt.state is State.IDLE


def test_two_slow_taps_are_two_normal_sessions_not_hands_free():
    ptt = PushToTalk()
    ptt.down(0.0)
    ptt.up(0.3)
    # 2 s later — outside the double-tap window.
    assert ptt.down(2.3) == [Action.START]
    assert ptt.state is State.PTT_HELD


def test_cancel_discards_without_transcribing():
    ptt = PushToTalk()
    ptt.down(0.0)
    assert ptt.cancel() == [Action.CANCEL]
    assert ptt.state is State.IDLE
    # Nothing to cancel when idle.
    assert ptt.cancel() == []


# ── clipboard: paste without eating the clipboard ────────────────────────────


class _FakePasteboard:
    """Minimal NSPasteboard stand-in backed by a dict of type -> data."""

    def __init__(self, initial):
        self._data = dict(initial)

    def types(self):
        return list(self._data.keys())

    def dataForType_(self, t):
        return self._data.get(t)

    def clearContents(self):
        self._data.clear()
        return 1

    def setString_forType_(self, s, t):
        self._data[t] = s
        return True

    def setData_forType_(self, data, t):
        self._data[t] = data
        return True

    def stringForType_(self, type_):
        # Miroir du Protocol (PasteboardLike n'est pas runtime_checkable :
        # sans cette méthode le double divergerait en silence).
        data = self._data.get(type_)
        return data.decode("utf-8") if isinstance(data, bytes) else data


def test_paste_restores_the_previous_clipboard():
    pb = _FakePasteboard({"public.utf8-plain-text": "user had this copied"})
    pasted = {}

    ok = clipboard.paste_text(
        "dictated sentence",
        pasteboard=pb,
        send_paste=lambda: pasted.setdefault(
            "text", pb.dataForType_("public.utf8-plain-text")
        ),
        sleep=lambda _s: None,
    )

    assert ok is True
    # Cmd+V saw the dictated text...
    assert pasted["text"] == "dictated sentence"
    # ...and afterwards the user's original clipboard is back.
    assert pb.dataForType_("public.utf8-plain-text") == "user had this copied"


def test_paste_restores_even_when_the_paste_raises():
    pb = _FakePasteboard({"public.utf8-plain-text": "precious"})

    def _boom():
        raise RuntimeError("Cmd+V failed")

    try:
        clipboard.paste_text(
            "x", pasteboard=pb, send_paste=_boom, sleep=lambda _s: None
        )
    except RuntimeError:
        pass
    assert pb.dataForType_("public.utf8-plain-text") == "precious"


def test_snapshot_keeps_non_text_flavours():
    pb = _FakePasteboard({"public.tiff": b"\x00img", "public.utf8-plain-text": "t"})
    clipboard.paste_text(
        "new", pasteboard=pb, send_paste=lambda: None, sleep=lambda _s: None
    )
    # Both original flavours restored, not just the text one.
    assert pb.dataForType_("public.tiff") == b"\x00img"
    assert pb.dataForType_("public.utf8-plain-text") == "t"


def test_empty_text_is_a_no_op():
    pb = _FakePasteboard({"public.utf8-plain-text": "keep"})
    assert clipboard.paste_text("", pasteboard=pb, send_paste=lambda: None) is False
    assert pb.dataForType_("public.utf8-plain-text") == "keep"


# ── mic DSP ──────────────────────────────────────────────────────────────────


def test_to_mono_averages_channels():
    stereo = np.array([[1.0, 3.0], [2.0, 4.0]], dtype="float32")
    assert list(mic_capture.to_mono(stereo)) == [2.0, 3.0]


def test_resample_changes_length_proportionally():
    block = np.ones(1000, dtype="float32")
    out = mic_capture.resample_linear(block, 48_000, 16_000)
    assert abs(len(out) - 333) <= 1  # 1000 * 16/48


def test_resample_is_identity_at_same_rate():
    block = np.arange(10, dtype="float32")
    out = mic_capture.resample_linear(block, 16_000, 16_000)
    assert list(out) == list(block)


def test_rms_level_of_silence_is_zero():
    assert mic_capture.rms_level(np.zeros(100, dtype="float32")) == 0.0
    assert mic_capture.rms_level(np.array([], dtype="float32")) == 0.0


def test_capture_ingest_accumulates_resampled_audio():
    cap = mic_capture.MicCapture(target_rate=16_000)
    cap._ingest(np.ones(48_000, dtype="float32"), 48_000)  # 1 s at 48 kHz
    buf = cap.buffer()
    assert abs(len(buf) - 16_000) <= 1  # ~1 s at 16 kHz
    assert cap.level > 0.0


def test_lire_texte_rend_le_texte_du_presse_papiers():
    pb = _FakePasteboard({"public.utf8-plain-text": "copié tel quel"})
    assert clipboard.lire_texte(pb) == "copié tel quel"


def test_lire_texte_rend_none_sans_texte():
    pb = _FakePasteboard({"public.png": b"\x89PNG"})
    assert clipboard.lire_texte(pb) is None
