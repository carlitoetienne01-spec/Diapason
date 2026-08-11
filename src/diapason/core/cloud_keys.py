"""Read the desktop app's cloud API keys from the macOS Keychain.

The desktop app stores provider keys in the Keychain (service "Diapason
Cloud Keys") and injects them as environment variables into the server *it*
spawns. But on a machine where the server runs as a LaunchAgent — started at
login, before the app — the app finds a healthy server already on the port,
reuses it, and the injection never happens. The key the user pastes into
Settings then never reaches the process that needs it, and the voice bridge
reports "not configured" forever.

This module closes that gap from the other side: the server falls back to
reading the same Keychain entries when the environment variable is absent.
The environment still wins, so a deliberate override keeps working.

The value never touches a logger, and lookups go through ``security``, the
system CLI — no extra dependency, and the Keychain's own access control still
applies (macOS may ask the user once to allow access).
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Must match the Rust side (SECURE_KEY_SERVICE in the desktop app) or the
# lookup silently finds nothing.
KEYCHAIN_SERVICE = "Diapason Cloud Keys"

# Same shape the desktop app enforces when saving; anything else is refused
# before it reaches a subprocess argument.
_VALID_NAME = re.compile(r"^[A-Z0-9_]{1,128}$")

# A short cache so a burst of health checks does not spawn a subprocess each
# time, while a key saved in Settings is still picked up within seconds —
# no restart, which is the point of the fallback.
_CACHE_TTL_S = 3.0
_cache: Dict[str, Tuple[float, Optional[str]]] = {}


def _read_keychain(name: str) -> Optional[str]:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, validated arg
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                name,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("keychain lookup failed for %s", name, exc_info=True)
        return None
    if result.returncode != 0:
        # Absent entry, or access denied — both mean "no key here".
        return None
    value = result.stdout.strip()
    return value or None


def get_cloud_key(*names: str) -> str:
    """First value found for any of ``names``: environment, then Keychain.

    Returns "" when nothing is found anywhere, which callers already treat
    as "not configured". Never logs the value.
    """
    import os

    for name in names:
        value = os.environ.get(name)
        if value:
            return value

    now = time.monotonic()
    for name in names:
        if not name.endswith("_API_KEY") or not _VALID_NAME.match(name):
            continue
        cached = _cache.get(name)
        if cached is not None and now - cached[0] < _CACHE_TTL_S:
            value = cached[1]
        else:
            value = _read_keychain(name)
            _cache[name] = (now, value)
        if value:
            return value
    return ""
