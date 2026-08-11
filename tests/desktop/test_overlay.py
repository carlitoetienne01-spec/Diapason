"""The floating indicator's geometry and state mapping.

Only the pure half is tested: a window server cannot be asserted on here, so
everything that can be decided without a screen, is.
"""

from __future__ import annotations

import pytest

from diapason.desktop import overlay as ov


class TestNormalizedLevel:
    def test_silence_is_zero(self):
        assert ov.normalized_level(0.0) == 0.0
        assert ov.normalized_level(-1.0) == 0.0

    def test_clamped_at_one(self):
        assert ov.normalized_level(1e6) == 1.0

    def test_monotonic(self):
        values = [ov.normalized_level(x) for x in (0.05, 0.2, 1.0, 2.0, 4.0)]
        assert values == sorted(values)

    def test_speech_lands_mid_scale(self):
        """rms_level puts ordinary speech near 1.0 on a 0–100 scale, so a
        linear map would leave the bars visually pinned at zero."""
        assert 0.35 < ov.normalized_level(1.0) < 0.65


class TestBarHeights:
    def test_bar_count(self):
        assert len(ov.bar_heights(1.0)) == ov.BARS
        assert len(ov.bar_heights(1.0, bars=3)) == 3

    def test_always_within_bounds(self):
        for level in (0.0, 0.05, 1.0, 4.0, 1e6):
            for phase in (0.0, 0.25, 0.5, 0.9):
                for h in ov.bar_heights(level, phase=phase):
                    assert ov.MIN_HEIGHT <= h <= 1.0

    def test_silence_is_a_visible_floor_not_zero(self):
        """A row collapsed to nothing reads as broken rather than quiet."""
        assert ov.bar_heights(0.0) == [ov.MIN_HEIGHT] * ov.BARS

    def test_louder_is_taller(self):
        quiet = sum(ov.bar_heights(0.2, phase=0.3))
        loud = sum(ov.bar_heights(3.0, phase=0.3))
        assert loud > quiet

    def test_bars_move_even_at_a_steady_level(self):
        """Without the phase wobble a constant tone freezes the indicator,
        which is indistinguishable from a hung service."""
        a = ov.bar_heights(1.5, phase=0.0)
        b = ov.bar_heights(1.5, phase=0.4)
        assert a != b

    def test_middle_bars_are_taller(self):
        heights = ov.bar_heights(4.0, phase=0.0, bars=ov.BARS)
        assert heights[ov.BARS // 2] > heights[0]

    def test_shape_covers_every_bar(self):
        assert len(ov.SHAPE) == ov.BARS

    def test_transcribing_ignores_the_level(self):
        """No microphone is open then; showing a meter would be a lie."""
        assert ov.bar_heights(0.0, state="transcribing", phase=0.2) == ov.bar_heights(
            99.0, state="transcribing", phase=0.2
        )

    def test_transcribing_still_animates(self):
        assert ov.bar_heights(0, state="transcribing", phase=0.0) != ov.bar_heights(
            0, state="transcribing", phase=0.5
        )

    def test_unknown_state_renders_idle_rather_than_raising(self):
        assert ov.bar_heights(5.0, state="banana") == [ov.MIN_HEIGHT] * ov.BARS


class TestStateForStatus:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("recording…", "recording"),
            ("recording (hands-free)…", "recording"),
            ("captured 2.1s (level 1.4)", "transcribing"),
            ("transcribing…", "transcribing"),
            ("pasting 42 chars…", "transcribing"),
            ("pasted ✓", "done"),
            ("cancelled — audio discarded", "hide"),
            ("no audio captured — check Microphone permission", "hide"),
            ("empty transcript — nothing to paste", "hide"),
            ("skipped: audio below silence floor", "hide"),
            ("ERROR during start: boom", "hide"),
        ],
    )
    def test_mapping(self, message, expected):
        assert ov.state_for_status(message) == expected

    def test_unrecognised_status_is_idle(self):
        assert ov.state_for_status("something new") == "idle"

    def test_every_service_status_is_accounted_for(self):
        """Guards the seam: a new DictationService status must be mapped
        deliberately, not silently fall through to idle mid-dictation."""
        import inspect

        from diapason.desktop import dictation_service

        source = inspect.getsource(dictation_service)
        emitted = [
            line.split('"')[1]
            for line in source.splitlines()
            if "_status(" in line and line.count('"') >= 2
        ]
        unmapped = [m for m in emitted if ov.state_for_status(m) == "idle"]
        assert not unmapped, f"unmapped status lines: {unmapped}"


class TestOverlayModel:
    def test_inputs_are_safe_before_start(self):
        """Levels arrive from the audio thread whether or not a window exists."""
        o = ov.DictationOverlay()
        o.set_level(2.0)
        o.set_state("recording")
        assert o.state == "recording"
        assert o.level == 2.0

    def test_hide_collapses_to_idle(self):
        o = ov.DictationOverlay()
        o.set_state("recording")
        o.set_state("hide")
        assert o.state == "idle"

    def test_on_status_adapter(self):
        o = ov.DictationOverlay()
        o.on_status("recording…")
        assert o.state == "recording"
        o.on_status("pasted ✓")
        assert o.state == "done"

    def test_stop_is_safe_when_never_started(self):
        ov.DictationOverlay().stop()

    def test_frame_heights_follows_state(self):
        o = ov.DictationOverlay()
        o.set_state("recording")
        o.set_level(3.0)
        assert sum(o.frame_heights()) > ov.MIN_HEIGHT * ov.BARS
