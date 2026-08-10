"""Microphone capture for push-to-talk, outside any WebView.

Diapason's dictation captured audio with ``getUserMedia`` *inside* the
WKWebView, so closing the window silenced the mic — the global hotkey would
fire and record nothing. Capturing here, in the Python process via
sounddevice, has no such coupling: the hotkey works with every window closed,
which is the whole point of a push-to-talk key.

The DSP helpers (RMS level, linear resample, mono downmix) are separated from
the live ``sounddevice`` stream so they can be unit-tested without a device.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000  # what every local STT backend wants


def rms_level(block: "Any") -> float:  # noqa: F821 - numpy at runtime
    """Root-mean-square of a float block, as 0.0–100.0 for a UI meter."""
    import numpy as np

    arr = np.asarray(block, dtype="float32").reshape(-1)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)) * 100.0)


def to_mono(block: "Any") -> "Any":  # noqa: F821
    """Average channels down to mono, leaving a 1-D array."""
    import numpy as np

    arr = np.asarray(block, dtype="float32")
    if arr.ndim == 2 and arr.shape[1] > 1:
        return arr.mean(axis=1)
    return arr.reshape(-1)


def resample_linear(block: "Any", src_rate: int, dst_rate: int) -> "Any":  # noqa: F821
    """Linear resample a mono block. Good enough for speech; no SciPy needed.

    The same linear interpolation Diapason's native recorder used to reach
    16 kHz — cheap, dependency-free, and inaudible on voice.
    """
    import numpy as np

    arr = np.asarray(block, dtype="float32").reshape(-1)
    if src_rate == dst_rate or arr.size == 0:
        return arr
    n_out = int(round(arr.size * dst_rate / src_rate))
    if n_out <= 0:
        return np.zeros(0, dtype="float32")
    src_idx = np.linspace(0.0, arr.size - 1, num=n_out, dtype="float32")
    left = np.floor(src_idx).astype("int64")
    right = np.minimum(left + 1, arr.size - 1)
    frac = src_idx - left
    return (arr[left] * (1.0 - frac) + arr[right] * frac).astype("float32")


class MicCapture:
    """Accumulate 16 kHz mono float audio while active; report a live level.

    ``start()`` opens a sounddevice input stream on a background thread;
    ``stop()`` returns the captured mono buffer at 16 kHz. ``level`` is the
    most recent RMS, for a waveform/meter. The buffering itself is plain and
    testable via ``_ingest``; only ``start``/``stop`` touch hardware.
    """

    def __init__(self, *, target_rate: int = TARGET_SAMPLE_RATE, level_cb=None):
        self._target_rate = target_rate
        self._level_cb = level_cb
        self._chunks: List["Any"] = []  # noqa: F821
        self._lock = threading.Lock()
        self._stream = None
        self._src_rate = target_rate
        self.level = 0.0

    def _ingest(self, block: "Any", src_rate: int) -> None:  # noqa: F821
        """Downmix → resample → append. The unit-testable core of capture."""
        mono = to_mono(block)
        self.level = rms_level(mono)
        if self._level_cb is not None:
            try:
                self._level_cb(self.level)
            except Exception:  # noqa: BLE001 - a UI callback must not kill audio
                logger.debug("level callback raised", exc_info=True)
        resampled = resample_linear(mono, src_rate, self._target_rate)
        with self._lock:
            self._chunks.append(resampled)

    def buffer(self) -> "Any":  # noqa: F821
        """Concatenate everything captured so far as one 16 kHz mono array."""
        import numpy as np

        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype="float32")
            return np.concatenate(self._chunks).astype("float32")

    # -- live device I/O -----------------------------------------------------

    def start(self, *, device: Optional[int] = None) -> None:
        import sounddevice as sd

        with self._lock:
            self._chunks = []
        info = (
            sd.query_devices(device, "input")
            if device is not None
            else sd.query_devices(kind="input")
        )
        self._src_rate = int(info.get("default_samplerate") or self._target_rate)

        def _cb(indata, _frames, _time, status) -> None:
            if status:
                logger.debug("mic status: %s", status)
            self._ingest(indata.copy(), self._src_rate)

        self._stream = sd.InputStream(
            samplerate=self._src_rate,
            channels=1,
            dtype="float32",
            callback=_cb,
            device=device,
        )
        self._stream.start()

    def stop(self) -> "Any":  # noqa: F821
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                logger.debug("stream close raised", exc_info=True)
        return self.buffer()
