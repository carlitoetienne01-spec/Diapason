"""Frontmost application helpers (macOS)."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def frontmost_app_name() -> Optional[str]:
    """Return the frontmost app name, or None if unavailable."""
    if sys.platform != "darwin":
        return None
    script = (
        'tell application "System Events" to get name of first application '
        "process whose frontmost is true"
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode != 0:
            return None
        name = (r.stdout or "").strip()
        return name or None
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("frontmost app probe failed", exc_info=True)
        return None


def is_mail_frontmost() -> bool:
    name = (frontmost_app_name() or "").lower()
    return name in {"mail", "microsoft outlook", "outlook"}


def is_email_composer_context() -> bool:
    """True when the user is likely composing email (Mail/Outlook frontmost)."""
    return is_mail_frontmost()


__all__ = [
    "frontmost_app_name",
    "is_email_composer_context",
    "is_mail_frontmost",
]
