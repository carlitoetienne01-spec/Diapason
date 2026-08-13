"""Cached macOS application index used by low-latency launch actions."""

from __future__ import annotations

import threading
import time
from pathlib import Path


class MacAppIndex:
    """Resolve app names without rescanning three directories per command."""

    def __init__(self, ttl_s: float = 300.0) -> None:
        self.ttl_s = max(1.0, float(ttl_s))
        self._items: tuple[str, ...] = ()
        self._updated = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _scan() -> tuple[str, ...]:
        names: set[str] = set()
        for root in (
            Path("/Applications"),
            Path("/System/Applications"),
            Path.home() / "Applications",
        ):
            if not root.is_dir():
                continue
            try:
                names.update(p.stem for p in root.iterdir() if p.suffix == ".app")
            except OSError:
                continue
        return tuple(sorted(names, key=str.casefold))

    def refresh(self) -> tuple[str, ...]:
        with self._lock:
            self._items = self._scan()
            self._updated = time.monotonic()
            return self._items

    def applications(self) -> tuple[str, ...]:
        if self._items and time.monotonic() - self._updated < self.ttl_s:
            return self._items
        return self.refresh()

    def resolve(self, name: str) -> str | None:
        raw = (name or "").strip()
        if raw.lower().endswith(".app"):
            raw = raw[:-4]
        if not raw:
            return None
        needle = raw.casefold()
        compact = needle.replace(" ", "")
        exact: list[str] = []
        partial: list[str] = []
        for candidate in self.applications():
            low = candidate.casefold()
            candidate_compact = low.replace(" ", "")
            if low == needle or candidate_compact == compact:
                exact.append(candidate)
            elif needle in low or compact in candidate_compact:
                partial.append(candidate)
        if exact:
            return exact[0]
        if partial:
            return min(partial, key=len)
        # Launch Services may know apps outside the indexed roots.
        return raw


APP_INDEX = MacAppIndex()

__all__ = ["APP_INDEX", "MacAppIndex"]
