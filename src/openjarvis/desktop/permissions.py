"""macOS TCC permissions for dictation — three, each easy to confuse.

Dictation needs all three, granted independently PER PROCESS (the background
LaunchAgent's Python binary does not inherit the terminal's grants):

* **Input Monitoring** — to hear the push-to-talk key (the event tap). A
  listen-only keyboard CGEventTap is gated by this, NOT Accessibility.
  ``AXIsProcessTrusted`` can return True while the tap is starved because
  Input Monitoring was never granted — the "says trusted, does nothing"
  failure.
* **Microphone** — to capture audio. macOS hands an unauthorized app SILENCE,
  not an error, so a starved mic looks like "you said nothing".
* **Accessibility** — to inject Cmd+V when pasting the transcript.

Input Monitoring lives in IOKit's ``IOHIDCheckAccess`` / ``IOHIDRequestAccess``
(called via ctypes; PyObjC does not expose them); Microphone in AVFoundation;
Accessibility in ApplicationServices.
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


_AV_AUDIO = "soun"  # AVMediaTypeAudio fourcc
_AV_AUTHORIZED = 3   # AVAuthorizationStatusAuthorized


def microphone_ok() -> bool:
    """True when this process may capture audio (Microphone).

    The third TCC permission dictation needs, and the one that bites the
    background agent hardest: macOS hands a non-authorized app SILENCE rather
    than an error, so a starved mic looks exactly like "you said nothing".
    """
    try:
        from AVFoundation import AVCaptureDevice  # type: ignore

        status = AVCaptureDevice.authorizationStatusForMediaType_(_AV_AUDIO)
        return status == _AV_AUTHORIZED
    except Exception:  # noqa: BLE001 - can't check → don't block
        return True


def request_microphone() -> None:
    """Trigger the macOS Microphone prompt (fires when status is undetermined)."""
    try:
        from AVFoundation import AVCaptureDevice  # type: ignore

        AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            _AV_AUDIO, lambda _granted: None
        )
    except Exception:  # noqa: BLE001
        pass


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


_PANE = "x-apple.systempreferences:com.apple.preference.security"
_PANES = {
    "Input Monitoring": f"{_PANE}?Privacy_ListenEvent",
    "Accessibility": f"{_PANE}?Privacy_Accessibility",
    "Microphone": f"{_PANE}?Privacy_Microphone",
}


def open_pane(name: str) -> None:
    """Open the given Privacy & Security pane in System Settings."""
    url = _PANES.get(name)
    if not url:
        return
    try:
        import subprocess

        subprocess.run(["open", url], capture_output=True, check=False)
    except Exception:  # noqa: BLE001
        pass


def missing_for_dictation() -> list[str]:
    """Return the human names of permissions still needed, in order to grant.

    All three: Input Monitoring (hear the key), Microphone (capture audio),
    Accessibility (inject the paste). Any one missing breaks dictation, and
    each is granted independently per process.
    """
    missing = []
    if not input_monitoring_ok():
        missing.append("Input Monitoring")
    if not microphone_ok():
        missing.append("Microphone")
    if not accessibility_ok():
        missing.append("Accessibility")
    return missing
