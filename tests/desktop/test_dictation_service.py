"""End-to-end orchestration of the dictation service, with fakes.

No microphone, no keyboard tap, no transcription model: the capture object,
transcriber and paster are all injected. What is verified is the *wiring* —
that a hold-and-release actually leads to capture → transcribe → paste, that
hands-free survives the release, and that cancel throws the audio away.
"""

from __future__ import annotations

import numpy as np

from openjarvis.desktop.dictation_service import DictationService, float_mono_to_wav


class _FakeCapture:
    """Stands in for MicCapture; records lifecycle, returns canned audio."""

    def __init__(self, audio):
        self._audio = audio
        self.started = False
        self.stopped = False

    def start(self, **_):
        self.started = True

    def stop(self):
        self.stopped = True
        return self._audio


def _service(audio=None, transcript="bonjour le monde"):
    captures = []
    pasted = []

    def factory():
        cap = _FakeCapture(np.ones(16_000, dtype="float32") if audio is None else audio)
        captures.append(cap)
        return cap

    clk = {"t": 0.0}

    svc = DictationService(
        transcribe=lambda _wav: transcript,
        paste=pasted.append,
        capture_factory=factory,
        clock=lambda: clk["t"],
    )
    return svc, captures, pasted, clk


# ── the happy path ───────────────────────────────────────────────────────────


def test_hold_release_captures_transcribes_and_pastes():
    svc, captures, pasted, clk = _service()

    svc.on_down()          # START -> capture begins
    assert captures[0].started is True

    clk["t"] = 0.8
    svc.on_up()            # STOP -> transcribe -> paste

    assert captures[0].stopped is True
    assert pasted == ["bonjour le monde"]


def test_empty_transcript_pastes_nothing():
    svc, _caps, pasted, _clk = _service(transcript="   ")
    svc.on_down()
    svc.on_up()
    assert pasted == []


def test_silent_capture_pastes_nothing():
    svc, _caps, pasted, _clk = _service(audio=np.zeros(0, dtype="float32"))
    svc.on_down()
    svc.on_up()
    assert pasted == []


# ── hands-free ───────────────────────────────────────────────────────────────


def test_double_tap_hands_free_survives_release_then_a_tap_pastes():
    # The first tap is a 50 ms press with no speech, so its capture returns
    # empty audio → empty transcript → nothing pasted. This is what actually
    # happens: you cannot say anything in the gap of a double-tap. The second
    # capture (hands-free) holds the real speech.
    audios = [np.zeros(0, dtype="float32"), np.ones(16_000, dtype="float32")]
    captures = []
    pasted = []

    def factory():
        cap = _FakeCapture(audios[len(captures)])
        captures.append(cap)
        return cap

    clk = {"t": 0.0}
    svc = DictationService(
        transcribe=lambda _wav: "bonjour le monde",
        paste=pasted.append,
        capture_factory=factory,
        clock=lambda: clk["t"],
    )

    svc.on_down()          # tap 1 down -> capture[0] (the tiny one)
    clk["t"] = 0.05
    svc.on_up()            # tap 1 up -> transcribe empty -> nothing pasted
    assert pasted == []
    clk["t"] = 0.2
    svc.on_down()          # tap 2 -> CANCEL, START_HANDS_FREE -> capture[1]

    assert captures[1].started is True

    clk["t"] = 0.25
    svc.on_up()            # release does NOT stop hands-free
    assert pasted == []

    clk["t"] = 4.0
    svc.on_down()          # tap -> stop hands-free -> transcribe -> paste
    assert pasted == ["bonjour le monde"]


# ── cancel ───────────────────────────────────────────────────────────────────


def test_cancel_discards_audio_without_pasting():
    svc, captures, pasted, _clk = _service()
    svc.on_down()
    svc.cancel()
    assert captures[0].stopped is True   # capture ended
    assert pasted == []                  # but nothing transcribed/pasted


# ── WAV encoding ─────────────────────────────────────────────────────────────


def test_wav_encoding_is_16bit_mono_16k():
    import wave

    wav_bytes = float_mono_to_wav(np.zeros(16_000, dtype="float32"), 16_000)
    with wave.open(__import__("io").BytesIO(wav_bytes)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16_000
        assert w.getnframes() == 16_000


def test_wav_encoding_clips_out_of_range_samples():
    import wave

    loud = np.array([2.0, -2.0, 0.5], dtype="float32")  # beyond [-1, 1]
    wav_bytes = float_mono_to_wav(loud, 16_000)
    with wave.open(__import__("io").BytesIO(wav_bytes)) as w:
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert frames[0] == 32767   # +2.0 clipped to +full scale
    assert frames[1] == -32767  # -2.0 clipped to -full scale


def test_silence_below_floor_is_not_transcribed():
    """A near-silent buffer skips the model — avoids Whisper hallucinations."""
    quiet = np.full(16_000, 0.001, dtype="float32")  # RMS ~0.1, below floor 0.5
    calls = []

    def _factory():
        return _FakeCapture(quiet)

    svc = DictationService(
        transcribe=lambda w: calls.append(w) or "hallucinated text",
        paste=lambda t: calls.append(("paste", t)),
        capture_factory=_factory,
        clock=lambda: 0.0,
    )
    svc.on_down()
    svc.on_up()
    assert calls == []  # neither transcribed nor pasted


def test_status_narrates_the_happy_path():
    """Each stage reports; 'nothing happened' is no longer indistinguishable."""
    statuses = []
    svc, _caps, pasted, clk = _service()
    svc._on_status = statuses.append

    svc.on_down()
    clk["t"] = 0.8
    svc.on_up()

    assert pasted == ["bonjour le monde"]
    assert statuses[0] == "recording…"
    assert any(s.startswith("captured ") for s in statuses)
    assert "transcribing…" in statuses
    assert statuses[-1] == "pasted ✓"


def test_status_explains_a_silent_buffer():
    quiet = np.full(16_000, 0.001, dtype="float32")
    statuses = []

    svc = DictationService(
        transcribe=lambda _w: "x",
        paste=lambda _t: None,
        capture_factory=lambda: _FakeCapture(quiet),
        clock=lambda: 0.0,
        on_status=statuses.append,
    )
    svc.on_down()
    svc.on_up()
    assert any("silence floor" in s for s in statuses)


def test_status_reports_a_crash_instead_of_swallowing_it():
    """A capture that raises must surface as an ERROR status, not vanish."""
    statuses = []

    class _Boom:
        def start(self, **_):
            raise RuntimeError("device unavailable")

    svc = DictationService(
        transcribe=lambda _w: "x",
        paste=lambda _t: None,
        capture_factory=_Boom,
        clock=lambda: 0.0,
        on_status=statuses.append,
    )
    svc.on_down()
    assert any(s.startswith("ERROR") and "device unavailable" in s for s in statuses)


def test_successful_dictation_is_recorded_in_history(tmp_path, monkeypatch):
    """History reflects what was DELIVERED, so it is written after the paste."""
    from openjarvis.desktop import dictation_history

    hist = tmp_path / "h.jsonl"
    monkeypatch.setattr(dictation_history, "default_history_path", lambda: hist)

    svc, _caps, pasted, clk = _service()
    svc._model_name = "small"
    svc.on_down()
    clk["t"] = 1.0
    svc.on_up()

    assert pasted == ["bonjour le monde"]
    entries = dictation_history.load_history(hist)
    assert len(entries) == 1
    assert entries[0].text == "bonjour le monde"
    assert entries[0].model == "small"


def test_nothing_is_recorded_when_nothing_was_pasted(tmp_path, monkeypatch):
    from openjarvis.desktop import dictation_history

    hist = tmp_path / "h.jsonl"
    monkeypatch.setattr(dictation_history, "default_history_path", lambda: hist)

    svc, _caps, pasted, _clk = _service(transcript="   ")
    svc.on_down()
    svc.on_up()

    assert pasted == []
    assert dictation_history.load_history(hist) == []


def test_history_failure_never_breaks_a_successful_dictation(monkeypatch):
    """Bookkeeping is not allowed to lose the user their sentence."""
    from openjarvis.desktop import dictation_history

    def _boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(dictation_history, "append_entry", _boom)

    svc, _caps, pasted, clk = _service()
    svc.on_down()
    clk["t"] = 1.0
    svc.on_up()

    assert pasted == ["bonjour le monde"]  # paste still happened


def test_history_can_be_turned_off(tmp_path, monkeypatch):
    from openjarvis.desktop import dictation_history

    hist = tmp_path / "h.jsonl"
    monkeypatch.setattr(dictation_history, "default_history_path", lambda: hist)

    svc, _caps, pasted, clk = _service()
    svc._history = False
    svc.on_down()
    clk["t"] = 1.0
    svc.on_up()

    assert pasted == ["bonjour le monde"]
    assert dictation_history.load_history(hist) == []
