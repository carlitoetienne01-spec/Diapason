"""Continuous screen-share session (start/stop) for Live voice assistance.

While active, periodically captures the screen and updates a text summary
via the local vision model. Never streams video off-device by default.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DescribeFn = Callable[..., str]  # kwargs: question, monitor → description text


@dataclass
class ScreenShareState:
    active: bool = False
    started_at: float = 0.0
    stopped_at: float = 0.0
    monitor: int = 1
    interval_s: float = 5.0
    max_minutes: float = 30.0
    frames: int = 0
    latest_summary: str = ""
    latest_at: float = 0.0
    last_error: str = ""
    question: str = (
        "Briefly describe what is on the screen right now for an assistant "
        "helping the user manage their work. Focus on the main app, visible "
        "titles, and actionable text. 2–4 short sentences."
    )


class ScreenShareSession:
    """Process-wide screen share controller (one session at a time)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = ScreenShareState()
        self._describe: Optional[DescribeFn] = None

    @property
    def state(self) -> ScreenShareState:
        with self._lock:
            return replace(self._state)

    def is_active(self) -> bool:
        with self._lock:
            return self._state.active

    def set_describe_fn(self, fn: DescribeFn) -> None:
        self._describe = fn

    def start(
        self,
        *,
        monitor: int = 1,
        interval_s: float = 5.0,
        max_minutes: float = 30.0,
        question: str = "",
        describe_fn: Optional[DescribeFn] = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._state.active:
                return {
                    "ok": True,
                    "already": True,
                    "active": True,
                    "summary": self._state.latest_summary,
                    "message": "Screen share already active.",
                }
            if describe_fn is not None:
                self._describe = describe_fn
            if self._describe is None:
                return {
                    "ok": False,
                    "active": False,
                    "message": "No vision describe function configured.",
                }

            self._stop.clear()
            self._state = ScreenShareState(
                active=True,
                started_at=time.monotonic(),
                monitor=max(0, int(monitor)),
                interval_s=max(2.0, float(interval_s)),
                max_minutes=max(1.0, float(max_minutes)),
                question=(
                    question.strip()
                    or ScreenShareState().question
                ),
            )
            self._thread = threading.Thread(
                target=self._loop, name="screen-share", daemon=True
            )
            self._thread.start()

        # Immediate first glance (blocking once)
        summary = self._capture_once()
        with self._lock:
            msg = (
                "Screen share started. I can see your screen until you say stop. "
                + (f"Right now: {summary}" if summary else "")
            ).strip()
            return {
                "ok": True,
                "already": False,
                "active": True,
                "summary": summary,
                "message": msg,
            }

    def stop(self, *, reason: str = "user") -> dict[str, Any]:
        with self._lock:
            if not self._state.active:
                return {
                    "ok": True,
                    "active": False,
                    "message": "Screen share was not active.",
                }
            self._stop.set()
            self._state.active = False
            self._state.stopped_at = time.monotonic()
            frames = self._state.frames
            summary = self._state.latest_summary
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        return {
            "ok": True,
            "active": False,
            "reason": reason,
            "frames": frames,
            "summary": summary,
            "message": "Screen share stopped. I am no longer watching your screen.",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            s = self._state
            elapsed = (time.monotonic() - s.started_at) if s.active and s.started_at else 0.0
            return {
                "active": s.active,
                "monitor": s.monitor,
                "interval_s": s.interval_s,
                "frames": s.frames,
                "elapsed_s": round(elapsed, 1),
                "latest_summary": s.latest_summary,
                "latest_at": s.latest_at,
                "last_error": s.last_error,
            }

    def latest_summary(self) -> str:
        with self._lock:
            return self._state.latest_summary

    def _capture_once(self) -> str:
        fn = self._describe
        if fn is None:
            return ""
        with self._lock:
            monitor = self._state.monitor
            question = self._state.question
        try:
            text = (fn(question=question, monitor=monitor) or "").strip()
            with self._lock:
                if text:
                    self._state.latest_summary = text
                    self._state.latest_at = time.monotonic()
                    self._state.frames += 1
                    self._state.last_error = ""
                return text
        except Exception as exc:
            logger.debug("screen share capture failed: %s", exc, exc_info=True)
            with self._lock:
                self._state.last_error = str(exc)
            return ""

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if not self._state.active:
                    break
                interval = self._state.interval_s
                max_s = self._state.max_minutes * 60.0
                started = self._state.started_at
            if max_s > 0 and (time.monotonic() - started) >= max_s:
                logger.info("Screen share auto-stopped after max duration")
                self.stop(reason="max_duration")
                break
            # Wait first so start()'s immediate capture isn't doubled instantly
            if self._stop.wait(timeout=interval):
                break
            if self._stop.is_set():
                break
            self._capture_once()


_SESSION: Optional[ScreenShareSession] = None
_SESSION_LOCK = threading.Lock()


def get_screen_share() -> ScreenShareSession:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = ScreenShareSession()
        return _SESSION


def reset_screen_share_for_tests() -> None:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None and _SESSION.is_active():
            _SESSION.stop(reason="test_reset")
        _SESSION = ScreenShareSession()


__all__ = [
    "ScreenShareSession",
    "ScreenShareState",
    "get_screen_share",
    "reset_screen_share_for_tests",
]
