"""Insert text into the frontmost app without destroying the clipboard.

The current paste path (``tools/desktop_tools.py``: ``pbcopy`` then Cmd+V via
osascript) overwrites whatever the user had copied and never puts it back. For
a dictation tool that fires dozens of times an hour, silently eating the
clipboard is a daily papercut.

This module saves the pasteboard, writes the dictated text, sends Cmd+V, then
restores the previous contents. The save/restore *logic* is separated from the
PyObjC calls so it can be unit-tested against a fake pasteboard; the real
NSPasteboard and CGEvent calls are thin wrappers at the bottom.
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional, Protocol

logger = logging.getLogger(__name__)

_CMD_V_KEYCODE = 9  # kVK_ANSI_V
_CMD_FLAG = 1 << 20  # kCGEventFlagMaskCommand


class PasteboardLike(Protocol):
    """The slice of NSPasteboard we depend on — lets tests inject a fake."""

    def types(self) -> Optional[List[str]]: ...
    def dataForType_(self, type_: str) -> Any: ...
    def clearContents(self) -> int: ...
    def setString_forType_(self, string: str, type_: str) -> bool: ...
    def setData_forType_(self, data: Any, type_: str) -> bool: ...


_TEXT_TYPE = "public.utf8-plain-text"


def snapshot(pb: PasteboardLike) -> List[tuple[str, Any]]:
    """Capture every representation currently on the pasteboard.

    All types are kept, not just text: the user may have copied an image or a
    file, and restoring only the plain-text flavour would still be data loss.
    """
    saved: List[tuple[str, Any]] = []
    for t in pb.types() or []:
        data = pb.dataForType_(t)
        if data is not None:
            saved.append((t, data))
    return saved


def restore(pb: PasteboardLike, saved: List[tuple[str, Any]]) -> None:
    """Put a previously captured snapshot back on the pasteboard."""
    pb.clearContents()
    for t, data in saved:
        pb.setData_forType_(data, t)


def _write_text(pb: PasteboardLike, text: str) -> None:
    pb.clearContents()
    pb.setString_forType_(text, _TEXT_TYPE)


# --------------------------------------------------------------------------
# Live implementation
# --------------------------------------------------------------------------


def _general_pasteboard() -> PasteboardLike:
    from AppKit import NSPasteboard  # type: ignore

    return NSPasteboard.generalPasteboard()


def _send_cmd_v() -> None:
    from Quartz import (  # type: ignore
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGHIDEventTap,
    )

    down = CGEventCreateKeyboardEvent(None, _CMD_V_KEYCODE, True)
    CGEventSetFlags(down, _CMD_FLAG)
    up = CGEventCreateKeyboardEvent(None, _CMD_V_KEYCODE, False)
    CGEventSetFlags(up, _CMD_FLAG)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


def paste_text(
    text: str,
    *,
    restore_delay_s: float = 0.15,
    pasteboard: Optional[PasteboardLike] = None,
    send_paste: Optional[Any] = None,
    sleep: Optional[Any] = None,
) -> bool:
    """Paste *text* into the frontmost app, then restore the clipboard.

    Returns True on success. The ``pasteboard`` / ``send_paste`` / ``sleep``
    parameters exist for tests; production uses the live defaults.

    The restore is delayed because Cmd+V is asynchronous — the receiving app
    reads the pasteboard on its own run loop, and clobbering it back too soon
    would paste stale data. This is the detail the naive pbcopy path never had.
    """
    if not text:
        return False
    pb = pasteboard if pasteboard is not None else _general_pasteboard()
    paste = send_paste if send_paste is not None else _send_cmd_v
    nap = sleep if sleep is not None else time.sleep

    saved = snapshot(pb)
    try:
        _write_text(pb, text)
        paste()
        nap(restore_delay_s)
        return True
    finally:
        # Restore even if the paste raised: losing the user's clipboard on an
        # error would be the same papercut we set out to remove.
        try:
            restore(pb, saved)
        except Exception:  # noqa: BLE001 - best-effort restore
            logger.warning("clipboard restore failed", exc_info=True)
