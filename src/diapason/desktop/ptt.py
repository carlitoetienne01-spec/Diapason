"""Push-to-talk state machine — hold to dictate, double-tap for hands-free.

Pure logic: it takes key-down / key-up events with a timestamp and emits a
list of *actions* for a host to carry out (start capture, stop and transcribe,
cancel...). No microphone, no clock of its own, no threads — which is what
makes the whole dictation flow unit-testable without hardware.

Behaviour mirrors Diapason's, which is the reference product:

* Hold the key, speak, release → transcribe what was said (normal PTT).
* Two quick taps → hands-free: capture keeps running after release; the next
  tap stops it and transcribes. The second tap of the double also cancels the
  tiny first session so it never produces a stray transcription.
* A tap while a normal press is somehow still held is ignored (key repeat).
* ``cancel()`` throws away the in-flight audio without transcribing.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List

# Diapason's window: a second press between 5 ms and 1000 ms after the first is
# a double-tap. Below 5 ms is switch bounce; above 1 s is two separate taps.
DOUBLE_TAP_MIN_S = 0.005
DOUBLE_TAP_MAX_S = 1.0


class State(enum.Enum):
    IDLE = "idle"
    PTT_HELD = "ptt_held"       # key down, normal press-and-hold
    HANDS_FREE = "hands_free"   # continuous, survives release


class Action(enum.Enum):
    START = "start"                       # begin capturing
    STOP_AND_TRANSCRIBE = "stop_xcribe"   # end capture, transcribe, paste
    START_HANDS_FREE = "start_hands_free"
    STOP_HANDS_FREE_AND_TRANSCRIBE = "stop_hands_free_xcribe"
    CANCEL = "cancel"                     # discard audio, no transcription


@dataclass
class PushToTalk:
    """Feed it ``down(t)`` / ``up(t)``; act on the returned actions."""

    state: State = State.IDLE
    _last_down_t: float | None = field(default=None, repr=False)

    def down(self, t: float) -> List[Action]:
        # A tap while hands-free is running is the deliberate "stop" gesture.
        if self.state is State.HANDS_FREE:
            self.state = State.IDLE
            self._last_down_t = t
            return [Action.STOP_HANDS_FREE_AND_TRANSCRIBE]

        # Key repeat / spurious re-press while already holding: ignore.
        if self.state is State.PTT_HELD:
            return []

        # IDLE: is this the second tap of a double?
        gap = None if self._last_down_t is None else t - self._last_down_t
        self._last_down_t = t
        if gap is not None and DOUBLE_TAP_MIN_S <= gap <= DOUBLE_TAP_MAX_S:
            self.state = State.HANDS_FREE
            # Cancel the tiny first session, then begin continuous capture.
            return [Action.CANCEL, Action.START_HANDS_FREE]

        self.state = State.PTT_HELD
        return [Action.START]

    def up(self, t: float) -> List[Action]:
        # Release ends a normal press; hands-free ignores it (that is the
        # whole point — you can let go and keep talking).
        if self.state is State.PTT_HELD:
            self.state = State.IDLE
            return [Action.STOP_AND_TRANSCRIBE]
        return []

    def cancel(self) -> List[Action]:
        """Abort whatever is in flight (e.g. Esc, or an app-level stop)."""
        if self.state in (State.PTT_HELD, State.HANDS_FREE):
            self.state = State.IDLE
            return [Action.CANCEL]
        return []

    @property
    def is_capturing(self) -> bool:
        return self.state in (State.PTT_HELD, State.HANDS_FREE)
