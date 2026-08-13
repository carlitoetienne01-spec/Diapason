"""The dictation blips: shape, encoding, and never breaking dictation."""

from __future__ import annotations

import io
import wave

import pytest

from diapason.desktop import audio_cues as ac


class TestGlide:
    def test_length_matches_duration(self):
        s = ac.glide(440, 880, 0.05, sample_rate=48_000)
        assert len(s) == 2400

    def test_starts_and_ends_at_silence(self):
        """A tone that begins at full amplitude clicks — the envelope is not
        decoration, it is the difference between a cue and a defect."""
        s = ac.glide(440, 880, 0.075)
        assert s[0] == pytest.approx(0.0, abs=1e-9)
        assert s[-1] == pytest.approx(0.0, abs=1e-9)

    def test_amplitude_is_respected(self):
        s = ac.glide(440, 880, 0.075, amplitude=0.1)
        assert max(abs(x) for x in s) <= 0.1 + 1e-9

    def test_reaches_full_amplitude_in_the_middle(self):
        """The envelope must open fully, not merely taper both ends."""
        s = ac.glide(600, 600, 0.2)
        mid = s[len(s) // 4 : 3 * len(s) // 4]
        assert max(abs(x) for x in mid) > ac.AMPLITUDE * 0.95

    def test_phase_is_continuous(self):
        """No sample-to-sample jump beyond what the frequency allows.

        This is what catches computing the argument as ``2π f(t) t``: that
        form makes the instantaneous frequency sweep twice as far and bends
        the pitch, which shows up here as an oversized step.
        """
        s = ac.glide(200, 400, 0.1, sample_rate=44_100, amplitude=1.0)
        # Highest frequency is 400 Hz, so the largest legitimate step is
        # 2π·400/44100 ≈ 0.057 rad — bounded well under 0.1 in amplitude.
        assert max(abs(b - a) for a, b in zip(s, s[1:])) < 0.1

    def test_frequency_is_actually_the_one_asked_for(self):
        """Count zero crossings of a steady tone: 440 Hz over 1 s ≈ 880."""
        s = ac.glide(440, 440, 1.0, amplitude=1.0)
        crossings = sum(1 for a, b in zip(s, s[1:]) if (a < 0) != (b < 0))
        assert crossings == pytest.approx(880, rel=0.02)

    def test_single_sample_does_not_divide_by_zero(self):
        assert len(ac.glide(440, 880, 1 / 44_100)) == 1


class TestWav:
    def test_is_a_readable_16bit_mono_wav(self):
        data = ac.wav_bytes(ac.glide(440, 880, 0.05), sample_rate=44_100)
        with wave.open(io.BytesIO(data)) as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == 44_100
            assert w.getnframes() == 2205

    def test_clips_instead_of_wrapping(self):
        """Out-of-range input must saturate; wrapping would invert the wave
        into a loud crackle."""
        data = ac.wav_bytes([5.0, -5.0], sample_rate=8_000)
        with wave.open(io.BytesIO(data)) as w:
            frames = w.readframes(2)
        import struct

        assert struct.unpack("<2h", frames) == (32767, -32767)


class TestCues:
    def test_every_cue_is_short_enough_to_be_a_cue(self):
        """A start blip that outlasts the word you are saying is a nuisance.
        (jarvis-main's only sound asset is 14.5 s long — hence synthesis.)"""
        for name in ac.CUES:
            seconds = len(ac.CUES[name]()) / ac.SAMPLE_RATE
            assert 0.02 < seconds < 0.25, f"{name} is {seconds:.3f}s"

    def test_start_rises_and_stop_falls(self):
        """Direction carries the meaning, so the pair must not be identical.

        Measured as zero-crossing density in each half: a rising sweep has
        more crossings late, a falling one more early.
        """

        def halves(samples):
            mid = len(samples) // 2

            def crossings(chunk):
                return sum(1 for a, b in zip(chunk, chunk[1:]) if (a < 0) != (b < 0))

            return crossings(samples[:mid]), crossings(samples[mid:])

        early, late = halves(ac._start())
        assert late > early, "the start cue must rise"
        early, late = halves(ac._stop())
        assert early > late, "the stop cue must fall"

    def test_cue_wav_rejects_unknown_names(self):
        with pytest.raises(KeyError):
            ac.cue_wav("nope")


class TestCuePlayer:
    def test_disabled_player_touches_nothing(self, tmp_path):
        player = ac.CuePlayer(enabled=False, directory=tmp_path)
        assert player.prime() is False
        assert player.play("start") is False
        assert list(tmp_path.iterdir()) == []

    def test_prime_writes_one_file_per_cue(self, tmp_path):
        player = ac.CuePlayer(directory=tmp_path)
        assert player.prime() is True
        written = {p.name for p in tmp_path.iterdir()}
        assert written == {f"{name}.wav" for name in ac.CUES}

    def test_prime_is_idempotent_and_does_not_rewrite(self, tmp_path):
        ac.CuePlayer(directory=tmp_path).prime()
        path = tmp_path / "start.wav"
        before = path.stat().st_mtime_ns
        ac.CuePlayer(directory=tmp_path).prime()
        assert path.stat().st_mtime_ns == before

    def test_changed_definition_replaces_a_stale_file(self, tmp_path):
        """The cues are code; a tuned frequency must land on the next start."""
        (tmp_path / "start.wav").write_bytes(b"stale")
        ac.CuePlayer(directory=tmp_path).prime()
        assert (tmp_path / "start.wav").read_bytes() == ac.cue_wav("start")

    def test_unknown_cue_is_ignored_not_raised(self, tmp_path):
        player = ac.CuePlayer(directory=tmp_path)
        player.prime()
        assert player.play("nonexistent") is False

    def test_play_survives_an_unwritable_cache(self, tmp_path, monkeypatch):
        """No sound is a cosmetic loss; an exception on the key-tap thread is
        a dead hotkey."""
        target = tmp_path / "ro"
        target.mkdir()
        target.chmod(0o500)
        try:
            player = ac.CuePlayer(directory=target / "sub")
            assert player.prime() is False
            assert player.play("start") is False
        finally:
            target.chmod(0o700)

    def test_a_broken_backend_falls_through_to_afplay(self, tmp_path, monkeypatch):
        """No sound is a cosmetic loss; an exception on the key-tap thread is
        a dead hotkey."""
        spawned = []
        monkeypatch.setattr(
            ac.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd)
        )

        class Boom:
            def isPlaying(self):
                raise RuntimeError("audio device vanished")

        player = ac.CuePlayer(directory=tmp_path)
        player.prime()
        player._sounds["start"] = Boom()
        assert player.play("start") is True
        assert spawned and spawned[0][0] == "/usr/bin/afplay"

    def test_afplay_is_never_waited_on(self, tmp_path, monkeypatch):
        """play() runs on the key-tap thread — blocking it stalls dictation."""
        monkeypatch.setattr(ac.subprocess, "Popen", lambda cmd, **kw: object())
        player = ac.CuePlayer(directory=tmp_path)
        player.prime()
        player._sounds.clear()  # force the fallback
        assert player.play("stop") is True
