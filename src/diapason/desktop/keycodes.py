"""macOS key codes and modifier flags for the global dictation hotkey.

Pure data + classification, deliberately importable without PyObjC so the
push-to-talk state machine can be unit-tested headlessly. The live event tap
(``hotkey.py``) maps real CGEvents onto the vocabulary defined here.
"""

from __future__ import annotations

from typing import Optional

# CGKeyCode values for the modifier keys we can bind as a bare push-to-talk
# key. These are the physical keys; the left/right variants share a keycode
# distinction only in the flag bits, which we do not need — holding either
# Control triggers dictation.
KEYCODES = {
    "control": {59, 62},   # kVK_Control, kVK_RightControl
    "option": {58, 61},    # kVK_Option, kVK_RightOption
    "command": {55, 54},   # kVK_Command, kVK_RightCommand
    "shift": {56, 60},     # kVK_Shift, kVK_RightShift
    "fn": {63},            # kVK_Function
}

# CGEventFlags mask bits, so the tap can tell a *bare* modifier press (the key
# we bound, and nothing else) from a chord like Cmd+Control.
FLAG_MASKS = {
    "control": 1 << 18,   # kCGEventFlagMaskControl
    "option": 1 << 19,    # kCGEventFlagMaskAlternate
    "command": 1 << 20,   # kCGEventFlagMaskCommand
    "shift": 1 << 17,     # kCGEventFlagMaskShift
    "fn": 1 << 23,        # kCGEventFlagMaskSecondaryFn
}

# Control is the default. Fn is avoided as a default because macOS itself
# claims it (emoji picker, system dictation), which is exactly the conflict
# Diapason documented when it moved its own default off Fn.
DEFAULT_HOTKEY = "control"

SUPPORTED_HOTKEYS = ("control", "option", "command", "fn")


def normalize_hotkey(name: str) -> str:
    """Return a supported hotkey name, falling back to the default.

    Mirrors the forgiving parse Diapason applies to its ``hotkey`` setting: an
    unknown or empty value must not leave dictation unbound, it falls back to
    Control.
    """
    key = (name or "").strip().lower()
    return key if key in SUPPORTED_HOTKEYS else DEFAULT_HOTKEY


def keycode_matches(hotkey: str, keycode: int) -> bool:
    """True when *keycode* is one of the physical keys for *hotkey*."""
    return keycode in KEYCODES.get(normalize_hotkey(hotkey), set())


def is_bare_press(hotkey: str, flags: int) -> bool:
    """True when *flags* show the bound modifier down and no OTHER modifier.

    A push-to-talk key must fire on the key alone. If the user is holding
    Command as well (Cmd+Control), that is a chord meant for the app in front,
    not a dictation trigger, so we let it through untouched.
    """
    hotkey = normalize_hotkey(hotkey)
    own = FLAG_MASKS[hotkey]
    if not (flags & own):
        return False
    others = 0
    for name, mask in FLAG_MASKS.items():
        if name != hotkey:
            others |= mask
    return not (flags & others)


def classify_flags_change(
    hotkey: str, keycode: int, flags: int
) -> Optional[str]:
    """Interpret a flagsChanged event as ``"down"``, ``"up"`` or ``None``.

    macOS reports modifier presses as ``flagsChanged`` events carrying the new
    flag state, not as key-down/up. The bound key is *down* when its own flag
    bit is set on an event for its keycode, and *up* when the same keycode
    arrives with its bit cleared.
    """
    if not keycode_matches(hotkey, keycode):
        return None
    own = FLAG_MASKS[normalize_hotkey(hotkey)]
    return "down" if (flags & own) else "up"
