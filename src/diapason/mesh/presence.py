"""Which devices are actually reachable, right now.

The one rule this module exists to keep (spec §57): a device that is not
there must never be presented as there. So presence is DERIVED from the last
heartbeat at read time, never stored as a state someone remembered to set.
A stored "ONLINE" survives a crashed app, a closed laptop lid and a dead
battery; a timestamp cannot lie about those.

The ladder, from the last time we heard anything:

    ≤ 45 s   ONLINE      — a heartbeat is due every 15 s, so this tolerates
                           two missed beats before doubting the device
    ≤ 5 min  IDLE        — the app is alive but nobody is using it
    ≤ 30 min BACKGROUND  — plausibly suspended (mobile especially), a queued
                           command may still be delivered when it wakes
    beyond   OFFLINE     — assume nothing; commands requiring the device
                           online must fail loudly rather than hopefully
"""

from __future__ import annotations

import time
from typing import Any, Mapping

__all__ = [
    "HEARTBEAT_INTERVAL_MS",
    "ONLINE_WINDOW_MS",
    "presence_of",
    "is_reachable",
]

HEARTBEAT_INTERVAL_MS = 15_000
ONLINE_WINDOW_MS = 45_000
IDLE_WINDOW_MS = 5 * 60 * 1000
BACKGROUND_WINDOW_MS = 30 * 60 * 1000

STATE_ONLINE = "ONLINE"
STATE_IDLE = "IDLE"
STATE_BACKGROUND = "BACKGROUND"
STATE_OFFLINE = "OFFLINE"


def _now_ms() -> int:
    return int(time.time() * 1000)


def presence_of(device: Mapping[str, Any], *, now_ms: int | None = None) -> dict:
    """The device's presence, computed from its last heartbeat.

    A revoked device is OFFLINE whatever its timestamp says: it is not a
    device we are willing to reach, so reporting it as available would
    invite a command that must be refused anyway.
    """
    now = _now_ms() if now_ms is None else now_ms
    last_seen = device.get("lastSeenAtMs")
    revoked = device.get("trustLevel") == "REVOKED"

    if revoked or not last_seen:
        state = STATE_OFFLINE
        age = None
    else:
        age = max(0, now - int(last_seen))
        if age <= ONLINE_WINDOW_MS:
            state = STATE_ONLINE
        elif age <= IDLE_WINDOW_MS:
            state = STATE_IDLE
        elif age <= BACKGROUND_WINDOW_MS:
            state = STATE_BACKGROUND
        else:
            state = STATE_OFFLINE

    return {
        "deviceId": device.get("deviceId"),
        "state": state,
        "appState": device.get("appState") or None,
        "transport": device.get("transport") or None,
        "lastSeenAtMs": last_seen,
        "ageMs": age,
        # The client shows a fresher-looking dot than reality otherwise: tell
        # it when the next beat is expected so it can grey out on its own.
        "heartbeatIntervalMs": HEARTBEAT_INTERVAL_MS,
    }


def is_reachable(device: Mapping[str, Any], *, now_ms: int | None = None) -> bool:
    """True only when a command sent now has a real chance of arriving.

    BACKGROUND is deliberately excluded: a suspended phone may accept a
    queued notification, but promising it will OPEN a screen would be the
    exact lie §57 forbids. The command policy decides whether to queue.
    """
    return presence_of(device, now_ms=now_ms)["state"] in (STATE_ONLINE, STATE_IDLE)
