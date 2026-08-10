"""Global push-to-talk hotkey via a CGEventTap.

``tauri-plugin-global-shortcut`` cannot listen for a *bare* held modifier —
it only accepts a full accelerator (Cmd+Shift+X). Diapason solved this with a
compiled Objective-C++ CGEventTap; here the same tap is driven from Python
through PyObjC, so it needs no separate native module and works whether or not
the Tauri GUI is running.

The event *classification* lives in ``keycodes.py`` and is fully tested. This
module is the thin live layer: it creates the tap, pumps a run loop on a
background thread, and calls ``on_down`` / ``on_up`` when the bound key
transitions. Creating the tap requires Accessibility permission
(AXIsProcessTrusted); without it macOS returns a null tap, which we surface as
a clear error rather than silent dead keys.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from openjarvis.desktop.keycodes import classify_flags_change, normalize_hotkey

logger = logging.getLogger(__name__)


class AccessibilityError(RuntimeError):
    """Raised when the event tap cannot be created (permission not granted)."""


class HotkeyListener:
    """Fire ``on_down``/``on_up`` when the bound modifier is pressed/released."""

    def __init__(
        self,
        *,
        hotkey: str = "control",
        on_down: Callable[[], None],
        on_up: Callable[[], None],
    ) -> None:
        self.hotkey = normalize_hotkey(hotkey)
        self._on_down = on_down
        self._on_up = on_up
        self._thread: Optional[threading.Thread] = None
        self._runloop = None
        self._down = False
        # PyObjC does NOT keep the Python callback / tap / source alive just
        # because the C layer holds them. If they are only locals in start(),
        # the garbage collector reclaims them and the tap goes silent — the
        # exact "nothing happens when I press the key" failure. Hold them.
        self._tap = None
        self._source = None
        self._callback = None

    def _handle(self, keycode: int, flags: int) -> None:
        """Dispatch one flagsChanged event. Debounced to real transitions."""
        edge = classify_flags_change(self.hotkey, keycode, flags)
        if edge == "down" and not self._down:
            self._down = True
            self._safe(self._on_down)
        elif edge == "up" and self._down:
            self._down = False
            self._safe(self._on_up)

    @staticmethod
    def _safe(cb: Callable[[], None]) -> None:
        try:
            cb()
        except Exception:  # noqa: BLE001 - a handler must not kill the tap
            logger.exception("hotkey handler raised")

    # -- live tap ------------------------------------------------------------

    def start(self) -> None:
        """Create the tap and pump its run loop on a daemon thread."""
        import Quartz  # type: ignore

        # A listen-only keyboard tap is starved of events without Accessibility
        # (or Input Monitoring). The tap can still be *created*, so checking
        # trust up front gives a real error instead of silent dead keys.
        try:
            from ApplicationServices import (  # type: ignore
                AXIsProcessTrusted,
            )

            trusted = bool(AXIsProcessTrusted())
        except Exception:  # noqa: BLE001 - if we can't check, don't block
            trusted = True
        if not trusted:
            raise AccessibilityError(
                "This process is not trusted for Accessibility, so the key tap "
                "would receive no events. Grant it in System Settings › Privacy "
                "& Security › Accessibility (add your terminal app), then retry."
            )

        def _tap_callback(proxy, type_, event, refcon):
            # A tap disabled by timeout/user-input must be re-enabled or it
            # stays dead for the rest of the session.
            if type_ in (
                Quartz.kCGEventTapDisabledByTimeout,
                Quartz.kCGEventTapDisabledByUserInput,
            ):
                if self._tap is not None:
                    Quartz.CGEventTapEnable(self._tap, True)
                return event
            keycode = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode
            )
            flags = Quartz.CGEventGetFlags(event)
            self._handle(int(keycode), int(flags))
            return event  # never swallow — we only observe

        self._callback = _tap_callback
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
            _tap_callback,
            None,
        )
        if self._tap is None:
            raise AccessibilityError(
                "Could not create the keyboard event tap. Grant Accessibility "
                "to your terminal app in System Settings › Privacy & Security › "
                "Accessibility, then retry."
            )

        self._source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)

        def _run() -> None:
            self._runloop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(
                self._runloop, self._source, Quartz.kCFRunLoopCommonModes
            )
            Quartz.CGEventTapEnable(self._tap, True)
            Quartz.CFRunLoopRun()

        self._thread = threading.Thread(target=_run, daemon=True, name="hotkey-tap")
        self._thread.start()

    def stop(self) -> None:
        import Quartz  # type: ignore

        if self._runloop is not None:
            Quartz.CFRunLoopStop(self._runloop)
            self._runloop = None
