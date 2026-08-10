"""Quiet-hours gate for heartbeat / routine delivery."""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional


def _parse_hhmm(value: str) -> Optional[time]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parts = raw.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return time(hour=h % 24, minute=m % 60)
    except (TypeError, ValueError):
        return None


def in_quiet_hours(
    *,
    enabled: bool = True,
    start: str = "22:00",
    end: str = "07:00",
    now: Optional[datetime] = None,
) -> bool:
    """True if *now* falls inside quiet hours (supports overnight wrap)."""
    if not enabled:
        return False
    t0 = _parse_hhmm(start)
    t1 = _parse_hhmm(end)
    if t0 is None or t1 is None:
        return False
    current = (now or datetime.now()).time().replace(second=0, microsecond=0)
    if t0 == t1:
        return False
    if t0 < t1:
        # e.g. 09:00–17:00
        return t0 <= current < t1
    # Overnight wrap e.g. 22:00–07:00
    return current >= t0 or current < t1


__all__ = ["in_quiet_hours"]
