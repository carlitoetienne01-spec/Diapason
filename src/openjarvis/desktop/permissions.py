"""macOS TCC permissions for dictation — the two that are easy to confuse.

A listen-only keyboard CGEventTap needs **Input Monitoring**
(``kTCCServiceListenEvent``), not Accessibility. ``AXIsProcessTrusted`` can
return True (Accessibility granted) while the tap is starved of events because
Input Monitoring was never granted — the exact "nothing happens, but it says
trusted" failure.

So dictation needs BOTH:

* **Input Monitoring** — to hear the push-to-talk key (the event tap).
* **Accessibility** — to inject Cmd+V when pasting the transcript.

Input Monitoring lives in IOKit's ``IOHIDCheckAccess`` / ``IOHIDRequestAccess``,
which PyObjC does not expose, so they are called via ctypes.
"""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

# kIOHIDRequestTypeListenEvent = 1 (observe); kIOHIDRequestTypePostEvent = 0.
_LISTEN_EVENT = 1
# IOHIDAccessType: 0 granted, 1 denied, 2 unknown.
_GRANTED = 0

_IOKIT_PATH = "/System/Library/Frameworks/IOKit.framework/IOKit"


def _iokit() -> "ctypes.CDLL | None":
    try:
        lib = ctypes.CDLL(_IOKIT_PATH)
        lib.IOHIDCheckAccess.restype = ctypes.c_int
        lib.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        lib.IOHIDRequestAccess.restype = ctypes.c_bool
        lib.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
        return lib
    except (OSError, AttributeError):  # not macOS, or symbols missing
        return None


def input_monitoring_ok() -> bool:
    """True when this process may observe keyboard events (Input Monitoring).

    Fails safe as True when the check itself is unavailable (non-macOS, or the
    symbol is missing) so a non-Darwin run is not blocked spuriously.
    """
    lib = _iokit()
    if lib is None:
        return True
    try:
        return lib.IOHIDCheckAccess(_LISTEN_EVENT) == _GRANTED
    except Exception:  # noqa: BLE001
        return True


def request_input_monitoring() -> bool:
    """Pop the macOS Input Monitoring prompt; return the resulting state.

    Adds this app to Privacy & Security › Input Monitoring. The grant needs a
    toggle and a terminal restart to take effect.
    """
    lib = _iokit()
    if lib is None:
        return True
    try:
        return bool(lib.IOHIDRequestAccess(_LISTEN_EVENT))
    except Exception:  # noqa: BLE001
        return input_monitoring_ok()


def accessibility_ok() -> bool:
    """True when this process may inject events (Accessibility) — for paste."""
    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore

        return bool(AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return True


def request_accessibility() -> bool:
    """Pop the macOS Accessibility prompt; return the resulting state."""
    try:
        from ApplicationServices import (  # type: ignore
            AXIsProcessTrustedWithOptions,
        )

        return bool(
            AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        )
    except Exception:  # noqa: BLE001
        return accessibility_ok()


def missing_for_dictation() -> list[str]:
    """Return the human names of permissions still needed, in order to grant."""
    missing = []
    if not input_monitoring_ok():
        missing.append("Input Monitoring")
    if not accessibility_ok():
        missing.append("Accessibility")
    return missing
