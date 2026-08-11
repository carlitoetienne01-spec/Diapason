"""The floating dictation indicator — proof that the key was heard.

A menu-bar glyph changing from 🎙 to 🔴 is technically feedback, but it is
20 pixels away from where you are looking and it does not move. When you hold
a key and speak into a machine that gives no answer, the question is never
"which icon is showing" — it is *"is this thing listening to me right now?"*.
So the indicator sits above the Dock, in the middle of the screen, and its
bars move with your voice: it answers the real question, because a bar that
responds to sound proves the microphone is genuinely open, not merely that a
code path was entered.

Two constraints shape everything here:

* **It must never steal focus.** Dictation ends by sending Cmd+V to the
  frontmost app; a panel that activates would make *itself* frontmost and the
  text would land in the void. Hence a non-activating ``NSPanel`` that ignores
  mouse events entirely and is ordered front "regardless".
* **It must never touch AppKit off the main thread.** Levels and state
  changes arrive on the audio and key-tap threads. Rather than marshal each
  one, those threads only assign to plain attributes; a main-thread timer
  reads them and does all the drawing. One direction, no locks, no dispatch.

The geometry — how tall each bar is for a given level — is pure and tested.
Only :class:`DictationOverlay` touches a window server.
"""

from __future__ import annotations

import logging
import math
from typing import List

logger = logging.getLogger(__name__)

BARS = 7
# A bar never falls to zero: a flat row reads as "broken", not as "quiet".
MIN_HEIGHT = 0.12
# rms_level is a 0–100 scale on which ordinary speech sits near 1.0 and
# silence under 0.05, so the useful signal lives in the bottom 4%. A square
# root over a full-scale of 4.0 spreads that range across the whole bar:
# level 0.05 → 11%, 1.0 → 50%, 4.0+ → 100%.
FULL_SCALE = 4.0
# Taller in the middle — a flat row of equal bars looks like a progress bar,
# a crowned one reads as a voice.
SHAPE = (0.55, 0.75, 0.92, 1.0, 0.92, 0.75, 0.55)

# Sized so the bars sit in a capsule with padding roughly equal to its corner
# radius — wider and the indicator reads as a mostly-empty pill.
PANEL_WIDTH = 132.0
PANEL_HEIGHT = 44.0
# Clear of the Dock at its default size, without floating in mid-screen.
BOTTOM_MARGIN = 120.0
FPS = 30.0


def normalized_level(level: float) -> float:
    """Map an RMS level (0–100 scale) onto 0–1 with a usable curve."""
    if level <= 0.0:
        return 0.0
    return min(1.0, math.sqrt(level / FULL_SCALE))


def bar_heights(
    level: float, *, state: str = "recording", phase: float = 0.0, bars: int = BARS
) -> List[float]:
    """Height of each bar, 0–1, for a level and animation phase.

    ``phase`` advances one full cycle per second; it is what keeps the bars
    alive while the level is steady. Unknown states render as idle rather
    than raising — an indicator is never worth crashing dictation over.
    """
    if state == "transcribing":
        # No microphone is open, so there is no level to show. A travelling
        # wave says "working" without pretending to be a meter.
        return [
            0.22 + 0.5 * (0.5 + 0.5 * math.sin(phase * 2 * math.pi * 1.4 - i * 0.9))
            for i in range(bars)
        ]
    if state != "recording":
        return [MIN_HEIGHT] * bars

    norm = normalized_level(level)
    out: List[float] = []
    for i in range(bars):
        shape = SHAPE[i % len(SHAPE)]
        # Per-bar phase offset so they ripple instead of pumping in unison.
        wobble = 0.78 + 0.22 * math.sin(phase * 2 * math.pi + i * 2.1)
        height = MIN_HEIGHT + (1.0 - MIN_HEIGHT) * norm * shape * wobble
        out.append(max(MIN_HEIGHT, min(1.0, height)))
    return out


def state_for_status(message: str) -> str:
    """Map a DictationService status line onto an overlay state.

    The service speaks in human sentences ("captured 2.3s (level 1.4)"); the
    overlay has four faces. Keeping the mapping here means the status strings
    stay free to change wording without breaking the UI.
    """
    if message.startswith("recording"):
        return "recording"
    if message.startswith(("transcribing", "captured", "pasting")):
        return "transcribing"
    if message.startswith("pasted"):
        return "done"
    if message.startswith(("cancelled", "ERROR", "no audio", "empty", "skipped")):
        return "hide"
    return "idle"


class DictationOverlay:
    """The live panel. Import-safe: AppKit is only touched in ``start()``.

    Call :meth:`set_state` and :meth:`set_level` from any thread.
    """

    def __init__(self) -> None:
        # Written from the tap/audio threads, read from the main thread. Plain
        # attribute assignment is atomic under the GIL, and a frame drawn from
        # a half-updated pair is indistinguishable from the frame before it.
        self.state = "idle"
        self.level = 0.0
        self._phase = 0.0
        self._alpha = 0.0
        self._hide_at = 0.0
        self._window = None
        self._view = None
        self._timer = None

    # -- thread-safe inputs -------------------------------------------------

    def set_state(self, state: str) -> None:
        if state == "hide":
            self.state = "idle"
            return
        self.state = state

    def set_level(self, level: float) -> None:
        self.level = level

    def on_status(self, message: str) -> None:
        """Adapter for ``DictationService(on_status=…)``."""
        self.set_state(state_for_status(message))

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> bool:  # pragma: no cover - needs a window server
        """Create the panel and begin the animation timer. False if no GUI."""
        try:
            self._build()
            self._start_timer()
            return True
        except Exception:  # noqa: BLE001 - headless or no window server
            logger.debug("overlay unavailable", exc_info=True)
            self._window = None
            return False

    def stop(self) -> None:  # pragma: no cover - needs a window server
        try:
            if self._timer is not None:
                self._timer.invalidate()
                self._timer = None
            if self._window is not None:
                self._window.orderOut_(None)
                self._window = None
        except Exception:  # noqa: BLE001
            logger.debug("overlay teardown failed", exc_info=True)

    # -- AppKit -------------------------------------------------------------

    def _build(self) -> None:  # pragma: no cover - needs a window server
        from AppKit import (  # type: ignore
            NSApplication,
            NSBackingStoreBuffered,
            NSColor,
            NSPanel,
            NSScreen,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskBorderless,
            NSWindowStyleMaskNonactivatingPanel,
        )
        from Foundation import NSMakeRect  # type: ignore

        # A window cannot exist before the application object does. This is
        # idempotent and is also what rumps calls, so the overlay composes
        # with the menu bar instead of fighting it for the run loop.
        NSApplication.sharedApplication()

        view = _make_view_class()(self)

        screen = NSScreen.mainScreen()
        frame = screen.frame()
        x = frame.origin.x + (frame.size.width - PANEL_WIDTH) / 2.0
        y = frame.origin.y + BOTTOM_MARGIN

        window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, PANEL_WIDTH, PANEL_HEIGHT),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(True)
        # Above ordinary windows but below menus/alerts. 25 is
        # NSStatusWindowLevel; naming it numerically avoids a constant that
        # moved between PyObjC releases.
        window.setLevel_(25)
        # The panel is decoration, not a target: clicks pass through to the
        # app underneath, which is also what keeps focus where it belongs.
        window.setIgnoresMouseEvents_(True)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setHidesOnDeactivate_(False)
        window.setAlphaValue_(0.0)
        window.setContentView_(view)
        # orderFrontRegardless, never makeKeyAndOrderFront: the latter would
        # activate us and Cmd+V would paste into this panel's app instead of
        # the one the user was typing in.
        window.orderFrontRegardless()

        self._window = window
        self._view = view

    def _start_timer(self) -> None:  # pragma: no cover - needs a run loop
        from Foundation import NSTimer  # type: ignore

        # A single steady timer rather than start/stop churn: when idle and
        # fully faded out the callback returns after two attribute reads, so
        # the cost of leaving it running is far below the cost of getting
        # timer lifecycle wrong on a service that runs for days.
        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            1.0 / FPS, True, lambda _t: self._tick()
        )

    def _tick(self) -> None:  # pragma: no cover - needs a run loop
        import time

        try:
            state = self.state
            visible = state in ("recording", "transcribing", "done")

            if state == "done":
                # Hold the confirmation briefly, then fade. Without the hold
                # the success frame is gone before the eye registers it.
                if self._hide_at == 0.0:
                    self._hide_at = time.monotonic() + 0.45
                elif time.monotonic() >= self._hide_at:
                    self.state = "idle"
                    self._hide_at = 0.0
                    visible = False
            else:
                self._hide_at = 0.0

            target = 1.0 if visible else 0.0
            # Exponential approach: fast enough to feel instant on show,
            # gentle enough on hide that it does not read as a flicker.
            self._alpha += (target - self._alpha) * (0.45 if visible else 0.22)
            if abs(self._alpha - target) < 0.01:
                self._alpha = target

            if self._window is not None:
                self._window.setAlphaValue_(self._alpha)
            if self._alpha <= 0.0:
                return

            self._phase += 1.0 / FPS
            if self._view is not None:
                self._view.setNeedsDisplay_(True)
        except Exception:  # noqa: BLE001 - a dropped frame must not kill the loop
            logger.debug("overlay tick failed", exc_info=True)

    # -- drawing model (read by the view) -----------------------------------

    def frame_heights(self) -> List[float]:
        return bar_heights(self.level, state=self.state, phase=self._phase)

    def tint(self):  # pragma: no cover - needs AppKit
        from AppKit import NSColor  # type: ignore

        if self.state == "recording":
            return NSColor.systemRedColor()
        if self.state == "transcribing":
            return NSColor.systemOrangeColor()
        if self.state == "done":
            return NSColor.systemGreenColor()
        return NSColor.whiteColor()


_VIEW_CLASS = None


def _make_view_class():  # pragma: no cover - needs AppKit
    """Define the NSView subclass lazily.

    PyObjC registers a subclass with the Objective-C runtime at *class
    definition* time, and a name may only be registered once per process. So
    the class is built on first use (keeping this module importable without
    AppKit) and then cached.
    """
    global _VIEW_CLASS
    if _VIEW_CLASS is not None:
        return _VIEW_CLASS

    import objc  # type: ignore
    from AppKit import NSBezierPath, NSColor, NSView  # type: ignore
    from Foundation import NSMakeRect  # type: ignore

    class _OverlayView(NSView):
        def initWithModel_(self, model):
            self = objc.super(_OverlayView, self).initWithFrame_(
                NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT)
            )
            if self is None:
                return None
            self._model = model
            return self

        def isOpaque(self):
            return False

        def drawRect_(self, _rect):
            model = self._model
            bounds = self.bounds()

            # Capsule background. Deliberately near-black at high opacity
            # rather than a vibrancy view: it must be legible over a white
            # document and a dark editor alike, and it must not cost a
            # backdrop blur 30 times a second on a background service.
            radius = bounds.size.height / 2.0
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, radius, radius
            )
            NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.88).set()
            path.fill()
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.12).set()
            path.setLineWidth_(1.0)
            path.stroke()

            model.tint().set()

            if model.state == "done":
                self._drawCheck_(bounds)
                return

            heights = model.frame_heights()
            bar_w = 6.0
            gap = 7.0
            total = len(heights) * bar_w + (len(heights) - 1) * gap
            x = (bounds.size.width - total) / 2.0
            max_h = bounds.size.height - 16.0
            cy = bounds.size.height / 2.0

            for h in heights:
                height = max(bar_w, max_h * h)
                rect = NSMakeRect(x, cy - height / 2.0, bar_w, height)
                bar = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    rect, bar_w / 2.0, bar_w / 2.0
                )
                bar.fill()
                x += bar_w + gap

        def _drawCheck_(self, bounds):
            """A tick, not a row of flat bars.

            "Delivered" is a different kind of statement from "here is your
            level" — reusing the meter for it would say the microphone is
            still open, which is exactly the thing the user is checking.
            """
            cx = bounds.size.width / 2.0
            cy = bounds.size.height / 2.0
            s = 7.0
            check = NSBezierPath.bezierPath()
            check.setLineWidth_(3.0)
            check.setLineCapStyle_(1)  # NSLineCapStyleRound
            check.setLineJoinStyle_(1)  # NSLineJoinStyleRound
            check.moveToPoint_((cx - s * 1.4, cy + s * 0.1))
            check.lineToPoint_((cx - s * 0.35, cy - s * 0.85))
            check.lineToPoint_((cx + s * 1.4, cy + s * 0.9))
            check.stroke()

    def _factory(model):
        return _OverlayView.alloc().initWithModel_(model)

    _VIEW_CLASS = _factory
    return _VIEW_CLASS
