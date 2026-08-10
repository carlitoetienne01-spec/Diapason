"""Display bounds helpers (macOS CoreGraphics; fallbacks elsewhere)."""

from __future__ import annotations

import logging
import sys
from typing import List, Tuple

logger = logging.getLogger(__name__)

Rect = Tuple[int, int, int, int]  # left, top, right, bottom


def _cg_display_bounds() -> List[Rect]:
    import ctypes
    import ctypes.util

    path = ctypes.util.find_library("CoreGraphics") or (
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )
    cg = ctypes.CDLL(path)

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    class CGSize(ctypes.Structure):
        _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

    class CGRect(ctypes.Structure):
        _fields_ = [("origin", CGPoint), ("size", CGSize)]

    cg.CGGetActiveDisplayList.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    cg.CGGetActiveDisplayList.restype = ctypes.c_int32
    cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    cg.CGDisplayBounds.restype = CGRect

    max_displays = 16
    displays = (ctypes.c_uint32 * max_displays)()
    count = ctypes.c_uint32(0)
    err = cg.CGGetActiveDisplayList(max_displays, displays, ctypes.byref(count))
    if err != 0 or count.value == 0:
        return []

    raw: list[tuple[float, float, float, float]] = []
    for i in range(count.value):
        r = cg.CGDisplayBounds(displays[i])
        left = r.origin.x
        bottom = r.origin.y
        w = r.size.width
        h = r.size.height
        raw.append((left, bottom, w, h))

    max_top = max(b + h for _l, b, _w, h in raw)
    rects: List[Rect] = []
    for left, bottom, w, h in raw:
        top = max_top - (bottom + h)
        rects.append((int(left), int(top), int(left + w), int(top + h)))
    rects.sort(key=lambda t: (t[0], t[1]))
    return rects


def _win32_monitor_rects() -> List[Rect]:
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    collected: List[Rect] = []

    @ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        wintypes.LPARAM,
    )
    def _cb(_hm, _hdc, lprc, _lp):
        r = lprc.contents
        collected.append((int(r.left), int(r.top), int(r.right), int(r.bottom)))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, _cb, 0)
    collected.sort(key=lambda t: (t[0], t[1]))
    return collected


def sorted_monitor_rects() -> List[Rect]:
    try:
        if sys.platform == "darwin":
            rects = _cg_display_bounds()
            if rects:
                return rects
        if sys.platform == "win32":
            rects = _win32_monitor_rects()
            if rects:
                return rects
    except OSError as exc:
        logger.warning("Monitor probe failed: %s", exc)
    return [(0, 0, 1440, 900)]


def monitor_bounds(one_based_index: int) -> Rect:
    rects = sorted_monitor_rects()
    idx = one_based_index - 1
    if idx < 0:
        idx = 0
    if idx >= len(rects):
        logger.warning(
            "Monitor %d requested but only %d found; using last.",
            one_based_index,
            len(rects),
        )
        idx = len(rects) - 1
    return rects[idx]


def monitor_placement(
    one_based_index: int, *, windowed: tuple[int, int] | None = None
) -> tuple[int, int, int, int]:
    """Return AppleScript-style bounds (left, top, right, bottom)."""
    ml, mt, mr, mb = monitor_bounds(one_based_index)
    if windowed is None:
        return (ml, mt, mr, mb)
    ww, wh = windowed
    w = min(ww, max(320, mr - ml))
    h = min(wh, max(240, mb - mt))
    x = ml + max(0, (mr - ml - w) // 2)
    y = mt + max(0, (mb - mt - h) // 2)
    return (x, y, x + w, y + h)
