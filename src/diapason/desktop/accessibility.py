"""Small, optional macOS Accessibility adapter.

PyObjC is optional at import time.  When AX is unavailable, callers can fall
back to the clipboard-preserving paste path without weakening permissions.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def accessibility_trusted(*, prompt: bool = False) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        from ApplicationServices import (  # type: ignore
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        return bool(
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt})
        )
    except (ImportError, AttributeError):
        return False


def _copied_value(result: Any) -> Any:
    """Normalize PyObjC's version-dependent AX copy return shape."""
    if isinstance(result, tuple):
        if len(result) >= 2 and result[0] == 0:
            return result[1]
        return None
    return result


def insert_text(text: str) -> bool:
    """Insert text at the focused UI element using AX selected-text."""
    if not text or not accessibility_trusted(prompt=False):
        return False
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
            AXUIElementSetAttributeValue,
            kAXFocusedUIElementAttribute,
            kAXSelectedTextAttribute,
        )

        system = AXUIElementCreateSystemWide()
        focused = _copied_value(
            AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute, None)
        )
        if focused is None:
            return False
        return (
            AXUIElementSetAttributeValue(focused, kAXSelectedTextAttribute, text) == 0
        )
    except (ImportError, AttributeError, TypeError, ValueError):
        logger.debug("AX text insertion unavailable", exc_info=True)
        return False


__all__ = ["accessibility_trusted", "insert_text"]
