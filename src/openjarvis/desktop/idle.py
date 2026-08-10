"""System idle time (macOS HID idle seconds)."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def idle_seconds() -> Optional[float]:
    """Seconds since last user input, or None if unavailable."""
    if sys.platform != "darwin":
        return None
    # CGEventSourceSecondsSinceLastEventType via Python/objc if present;
    # fallback: ioreg HIDIdleTime (nanoseconds).
    try:
        r = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            if "HIDIdleTime" in line:
                # "HIDIdleTime" = 12345678900
                parts = line.split("=")
                if len(parts) < 2:
                    continue
                raw = parts[-1].strip().rstrip(";")
                ns = int(raw)
                return ns / 1_000_000_000.0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        logger.debug("idle_seconds failed", exc_info=True)
    return None


__all__ = ["idle_seconds"]
