"""The dictation service — the parts wired into one running thing.

Composes the four pieces of the push-to-talk stack:

    hotkey (CGEventTap)  →  PTT state machine  →  mic capture  →
    transcribe (speech backend)  →  clean paste (clipboard preserved)

The *composition* — which action leads to capture/transcribe/paste — is a
pure method (``_run_action``) driven by injected callables, so the whole flow
is testable with fakes: no microphone, no tap, no transcription model. The
live wiring (``start``/``stop``) only attaches the real hotkey listener.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Callable, Optional

from openjarvis.desktop.mic_capture import MicCapture
from openjarvis.desktop.ptt import Action, PushToTalk

logger = logging.getLogger(__name__)

# A transcriber takes 16 kHz mono WAV bytes and returns text.
Transcribe = Callable[[bytes], str]
# A paster takes text and inserts it into the frontmost app.
Paste = Callable[[str], None]
# A capture factory returns a fresh capture object per session.
CaptureFactory = Callable[[], MicCapture]


def float_mono_to_wav(samples: "Any", sample_rate: int = 16_000) -> bytes:  # noqa: F821
    """Encode a float32 [-1, 1] mono array as 16-bit PCM WAV bytes (stdlib)."""
    import numpy as np

    arr = np.asarray(samples, dtype="float32").reshape(-1)
    clipped = np.clip(arr, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class DictationService:
    """Drive dictation from key events, independent of any window."""

    def __init__(
        self,
        *,
        transcribe: Transcribe,
        paste: Paste,
        hotkey: str = "control",
        capture_factory: CaptureFactory = MicCapture,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._transcribe = transcribe
        self._paste = paste
        self._hotkey = hotkey
        self._capture_factory = capture_factory
        self._ptt = PushToTalk()
        self._capture: Optional[MicCapture] = None
        self._listener = None
        if clock is None:
            import time

            clock = time.monotonic
        self._clock = clock

    # -- pure orchestration (tested) ----------------------------------------

    def _run_action(self, action: Action) -> Optional[str]:
        """Carry out one PTT action. Returns pasted text, if any."""
        if action in (Action.START, Action.START_HANDS_FREE):
            self._capture = self._capture_factory()
            self._capture.start()
            return None
        if action in (
            Action.STOP_AND_TRANSCRIBE,
            Action.STOP_HANDS_FREE_AND_TRANSCRIBE,
        ):
            return self._finish_and_paste()
        if action is Action.CANCEL:
            self._discard()
            return None
        return None

    def _finish_and_paste(self) -> Optional[str]:
        cap, self._capture = self._capture, None
        if cap is None:
            return None
        audio = cap.stop()
        if audio is None or len(audio) == 0:
            return None
        text = (self._transcribe(float_mono_to_wav(audio)) or "").strip()
        if not text:
            return None
        self._paste(text)
        return text

    def _discard(self) -> None:
        cap, self._capture = self._capture, None
        if cap is not None:
            try:
                cap.stop()
            except Exception:  # noqa: BLE001 - discarding, errors don't matter
                logger.debug("discard stop raised", exc_info=True)

    def on_down(self) -> None:
        for action in self._ptt.down(self._clock()):
            self._run_action(action)

    def on_up(self) -> None:
        for action in self._ptt.up(self._clock()):
            self._run_action(action)

    def cancel(self) -> None:
        for action in self._ptt.cancel():
            self._run_action(action)

    # -- live wiring --------------------------------------------------------

    def start(self) -> None:
        from openjarvis.desktop.hotkey import HotkeyListener

        self._listener = HotkeyListener(
            hotkey=self._hotkey, on_down=self.on_down, on_up=self.on_up
        )
        self._listener.start()
        logger.info("dictation service listening on hotkey %r", self._hotkey)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._discard()
