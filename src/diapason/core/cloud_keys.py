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


def _keychain_has(name: str) -> bool:
    """Whether the Keychain holds an entry for ``name`` — without reading it.

    No ``-w``: ``security`` prints the item's attributes, not its secret.
    26/09/2026: the status route (``GET /v1/cloud/keys``) read every secret
    just to say "present", once per key and per palette opening. The items
    are written by Diapason.app, so each read by ``security`` on behalf of
    the server may raise a macOS access prompt on the Mac for keys the
    server never uses (DEDUCED, not observed: the real Keychain was not
    touched). Asking for attributes only does not need the secret.
    """
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, validated arg
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                name,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("keychain presence check failed for %s", name, exc_info=True)
        return False
    return result.returncode == 0


_presence_cache: Dict[str, Tuple[float, bool]] = {}

# Presence changes only when the desktop app saves or removes a key; thirty
# seconds keeps a burst of Settings widgets to one subprocess per key, and a
# key saved on the Mac still shows within half a minute.
_PRESENCE_TTL_S = 30.0


def cloud_key_present(name: str) -> bool:
    """Whether ``name`` is set: environment, then Keychain attributes only."""
    import os

    if os.environ.get(name):
        return True
    if not name.endswith("_API_KEY") or not _VALID_NAME.match(name):
        return False
    now = time.monotonic()
    cached = _presence_cache.get(name)
    if cached is not None and now - cached[0] < _PRESENCE_TTL_S:
        return cached[1]
    present = _keychain_has(name)
    _presence_cache[name] = (now, present)
    return present


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
