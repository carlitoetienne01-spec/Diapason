"""Frontmost application helpers (macOS)."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)


def frontmost_app_name() -> Optional[str]:
    """Return the frontmost app name, or None if unavailable."""
    if sys.platform != "darwin":
        return None
    # Native Launch Services lookup is typically sub-millisecond and avoids
    # spawning osascript for every verification poll.
    try:
        from AppKit import NSWorkspace  # type: ignore

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        name = app.localizedName() if app is not None else None
        if name:
            return str(name)
    except (ImportError, AttributeError):
        pass
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


def wait_until_frontmost(app_name: str, *, timeout_s: float = 2.0) -> bool:
    """Wait briefly for an app activation and report the observed result."""
    wanted = (app_name or "").casefold().replace(" ", "")
    if not wanted:
        return False
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        active = (frontmost_app_name() or "").casefold().replace(" ", "")
        if active and (active == wanted or active in wanted or wanted in active):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.04)


def is_email_composer_context() -> bool:
    """True when the user is likely composing email (Mail/Outlook frontmost)."""
    return is_mail_frontmost()


__all__ = [
    "frontmost_app_name",
    "is_email_composer_context",
    "is_mail_frontmost",
    "wait_until_frontmost",
]
