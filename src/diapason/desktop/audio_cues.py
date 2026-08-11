"""Audible feedback for dictation — a blip down, a blip up.

Push-to-talk is a blind contract: you hold a key and *hope* a microphone
opened. Everything that can go wrong (permission missing, tap starved, key
not registered) fails the same silent way, so the single most useful signal
is a short sound the instant the key is seen. It confirms the tap fired,
before any device work has happened.

Two design choices worth stating:

* **The tones are synthesised, not shipped.** ``jarvis-main`` plays a WAV
  through ``sounddevice``, but its only asset is a 14.5-second spoken welcome
  phrase — a start cue must be under a tenth of a second. Rather than commit a
  binary asset that has to be found, licensed and reviewed, the cues are ~40
  lines of arithmetic, so they are diffable, tunable, and testable without a
  sound card.
* **Playback goes through NSSound, not ``sounddevice``.** The capture stream
  is a PortAudio *input* stream opening at the same moment; driving output
  through the same library invites device contention on the one code path
  that must never stall. NSSound loads the clip into memory once at startup
  and ``play()`` returns immediately, so the cue costs nothing at keypress.

Nothing here is allowed to break dictation: every failure degrades to
silence. A missing sound is a cosmetic loss; a raised exception on the tap
callback thread is a dead hotkey.
"""

from __future__ import annotations

import logging
import math
import struct
import subprocess
import wave
from pathlib import Path
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44_100
# Loud enough to hear over typing, quiet enough not to startle at 2 a.m.
# Calibrated against the macOS "Tink" system sound.
AMPLITUDE = 0.22
# Raised-cosine attack/release. A tone that starts at full amplitude clicks:
# the discontinuity is broadband and reads as a defect, not a cue.
EDGE_S = 0.008


def glide(
    f0: float,
    f1: float,
    duration_s: float,
    *,
    sample_rate: int = SAMPLE_RATE,
    amplitude: float = AMPLITUDE,
) -> List[float]:
    """A sine sweeping f0 → f1, enveloped so it neither clicks nor thumps.

    The phase is *integrated* rather than computed per-sample from the
    instantaneous frequency (``sin(2π f(t) t)``), which would fold the
    frequency change into the argument twice and bend the pitch the wrong
    way. Accumulating ``2π f(t)/rate`` keeps the waveform continuous.
    """
    n = max(1, int(round(duration_s * sample_rate)))
    edge = min(int(EDGE_S * sample_rate), n // 2)
    out: List[float] = []
    phase = 0.0
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        freq = f0 + (f1 - f0) * t
        phase += 2.0 * math.pi * freq / sample_rate
        gain = 1.0
        if edge:
            if i < edge:
                gain = 0.5 * (1.0 - math.cos(math.pi * i / edge))
            elif i >= n - edge:
                gain = 0.5 * (1.0 - math.cos(math.pi * (n - 1 - i) / edge))
        out.append(amplitude * gain * math.sin(phase))
    return out


def silence(duration_s: float, *, sample_rate: int = SAMPLE_RATE) -> List[float]:
    return [0.0] * max(0, int(round(duration_s * sample_rate)))


def wav_bytes(samples: Sequence[float], *, sample_rate: int = SAMPLE_RATE) -> bytes:
    """16-bit mono PCM WAV, stdlib only."""
    frames = b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767.0)) for s in samples
    )
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buf.getvalue()


# The vocabulary. Rising = something opened, falling = something closed, and
# a low double-tap for "thrown away" — the direction carries the meaning even
# when the sound is barely conscious. Intervals are a perfect fifth (D5→A5)
# so the pair sounds deliberate rather than like two unrelated beeps.
def _start() -> List[float]:
    return glide(587.33, 880.00, 0.075)


def _stop() -> List[float]:
    return glide(880.00, 587.33, 0.075)


def _cancel() -> List[float]:
    return (
        glide(440.0, 415.30, 0.045, amplitude=AMPLITUDE * 0.85)
        + silence(0.035)
        + glide(415.30, 329.63, 0.060, amplitude=AMPLITUDE * 0.85)
    )


CUES = {"start": _start, "stop": _stop, "cancel": _cancel}


def cue_wav(name: str) -> bytes:
    """WAV bytes for a named cue. Raises KeyError on an unknown name."""
    return wav_bytes(CUES[name]())


def cache_dir() -> Path:
    from diapason.core.paths import get_cache_dir

    return get_cache_dir() / "cues"


class CuePlayer:
    """Plays the cues, or silently does nothing. Never raises.

    ``prime()`` does all the expensive work — synthesis, disk write, NSSound
    load — so that ``play()`` is a single message send on the hot path.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        directory: Optional[Path] = None,
    ) -> None:
        self.enabled = enabled
        self._dir = directory
        self._paths: Dict[str, Path] = {}
        self._sounds: Dict[str, object] = {}
        self._primed = False

    # -- setup --------------------------------------------------------------

    def _write_files(self) -> None:
        directory = self._dir if self._dir is not None else cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        for name in CUES:
            path = directory / f"{name}.wav"
            data = cue_wav(name)
            # Rewrite only on change: the cue definitions are code, so a tuned
            # frequency lands on the next start without a stale file surviving.
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
            self._paths[name] = path

    def prime(self) -> bool:
        """Synthesise, cache and preload. True when at least one cue is ready."""
        if not self.enabled or self._primed:
            return bool(self._paths)
        self._primed = True
        try:
            self._write_files()
        except Exception:  # noqa: BLE001 - a cue is never worth failing over
            logger.debug("could not write cue files", exc_info=True)
            return False
        try:
            from AppKit import NSSound  # type: ignore

            for name, path in self._paths.items():
                sound = NSSound.alloc().initWithContentsOfFile_byReference_(
                    str(path), True
                )
                if sound is not None:
                    self._sounds[name] = sound
        except Exception:  # noqa: BLE001 - afplay fallback below still works
            logger.debug("NSSound unavailable; falling back to afplay", exc_info=True)
        return bool(self._paths)

    # -- hot path -----------------------------------------------------------

    def play(self, name: str) -> bool:
        """Fire a cue. Returns True if something was actually played.

        Called from the key-tap callback thread, so it must not block: NSSound
        plays asynchronously, and the afplay fallback is spawned, never waited
        on.
        """
        if not self.enabled:
            return False
        if not self._primed:
            self.prime()
        sound = self._sounds.get(name)
        if sound is not None:
            try:
                # Restart from the top if the previous cue is still ringing —
                # rapid push-to-talk taps must not swallow their own feedback.
                if sound.isPlaying():
                    sound.stop()
                return bool(sound.play())
            except Exception:  # noqa: BLE001
                logger.debug("NSSound play failed", exc_info=True)
        path = self._paths.get(name)
        if path is None:
            return False
        try:
            subprocess.Popen(  # noqa: S603 - fixed binary, generated path
                ["/usr/bin/afplay", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:  # noqa: BLE001
            logger.debug("afplay fallback failed", exc_info=True)
            return False
