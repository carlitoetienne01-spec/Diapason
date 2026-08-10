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
        # Field observation (Carlito's MacBook mic): normal speech lands at
        # level ~1.0 on the 0–100 RMS scale, while true silence sits well
        # under 0.05. The earlier floor of 0.5 left only a 2× margin to real
        # speech — a soft-spoken word could be discarded as silence. 0.15
        # keeps ~7× margin to speech while still rejecting an untouched mic.
        silence_rms: float = 0.15,
        on_status: Callable[[str], None] | None = None,
        history: bool = True,
        model_name: str = "",
    ) -> None:
        self._history = history
        self._model_name = model_name
        self._transcribe = transcribe
        self._paste = paste
        self._hotkey = hotkey
        self._capture_factory = capture_factory
        # Status callback: every stage of a session reports here. Without it
        # the pipeline is a black box — a mic without permission, a silent
        # buffer, an empty transcript and a failed paste all look identical
        # to the user: "nothing happened".
        self._on_status = on_status
        # Below this RMS (on the 0–100 scale) the buffer is treated as silence
        # and never sent to the transcriber. Skipping silence avoids a model
        # invocation — and, more importantly, the "you. thanks for watching"
        # hallucinations Whisper emits on empty audio.
        self._silence_rms = silence_rms
        self._ptt = PushToTalk()
        self._capture: Optional[MicCapture] = None
        self._listener = None
        if clock is None:
            import time

            clock = time.monotonic
        self._clock = clock

    # -- pure orchestration (tested) ----------------------------------------

    def _status(self, message: str) -> None:
        if self._on_status is not None:
            try:
                self._on_status(message)
            except Exception:  # noqa: BLE001 - status must never break audio
                logger.debug("status callback raised", exc_info=True)

    def _run_action(self, action: Action) -> Optional[str]:
        """Carry out one PTT action. Returns pasted text, if any.

        Every failure is REPORTED, not swallowed: these run on the tap
        callback thread, where an uncaught exception would only reach a
        logger nobody is watching.
        """
        try:
            if action in (Action.START, Action.START_HANDS_FREE):
                self._capture = self._capture_factory()
                self._capture.start()
                self._status(
                    "recording (hands-free)…"
                    if action is Action.START_HANDS_FREE
                    else "recording…"
                )
                return None
            if action in (
                Action.STOP_AND_TRANSCRIBE,
                Action.STOP_HANDS_FREE_AND_TRANSCRIBE,
            ):
                return self._finish_and_paste()
            if action is Action.CANCEL:
                self._discard()
                self._status("cancelled — audio discarded")
                return None
            return None
        except Exception as exc:  # noqa: BLE001 - surface, then continue
            logger.exception("dictation action %s failed", action)
            self._status(f"ERROR during {action.value}: {exc}")
            self._capture = None
            return None

    def _finish_and_paste(self) -> Optional[str]:
        cap, self._capture = self._capture, None
        if cap is None:
            return None
        audio = cap.stop()
        if audio is None or len(audio) == 0:
            self._status("no audio captured — check Microphone permission")
            return None
        from openjarvis.desktop.mic_capture import rms_level

        seconds = len(audio) / 16_000.0
        level = rms_level(audio)
        self._status(f"captured {seconds:.1f}s (level {level:.1f})")
        if level < self._silence_rms:
            self._status(
                "skipped: audio below silence floor — if you were speaking, "
                "the mic is muted or Microphone permission is missing"
            )
            return None
        self._status("transcribing…")
        text = (self._transcribe(float_mono_to_wav(audio)) or "").strip()
        if not text:
            self._status("empty transcript — nothing to paste")
            return None
        self._status(f"pasting {len(text)} chars…")
        self._paste(text)
        self._status("pasted ✓")
        self._record(text, seconds)
        return text

    def _record(self, text: str, seconds: float) -> None:
        """Save to the local history. Never lets a bookkeeping error surface.

        Recorded AFTER a successful paste, so the history reflects what was
        actually delivered rather than every attempt.
        """
        if not self._history:
            return
        try:
            import time

            from openjarvis.desktop.dictation_history import (
                DictationEntry,
                append_entry,
            )

            app = ""
            try:
                from openjarvis.desktop.frontmost import frontmost_app_name

                app = frontmost_app_name() or ""
            except Exception:  # noqa: BLE001 - the app name is a nicety
                pass

            append_entry(
                DictationEntry(
                    text=text,
                    timestamp=time.time(),
                    duration_s=round(seconds, 2),
                    app=app,
                    model=self._model_name,
                )
            )
        except Exception:  # noqa: BLE001 - history must never break dictation
            logger.debug("could not record dictation history", exc_info=True)

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
