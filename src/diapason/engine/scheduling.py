"""Admission to Ollama: interactive work precedes pending housekeeping.

This coordinates this process only. An inference already sent to Ollama is
never pretended to be preemptible, nor are other programs' requests covered.
"""

from __future__ import annotations

import asyncio
import threading
import time
import weakref
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

# 19/09/2026: extraction started as soon as the answer ended, ahead of the
# next question. Leave two seconds for a follow-up; this delays memory only.
QUIET_SECONDS = 2.0
_condition = threading.Condition()
_turns = 0
_last_turn = 0.0


@dataclass(frozen=True)
class BackgroundWork:
    use_active_model: bool = False
    stop: threading.Event | None = None


_background: ContextVar[BackgroundWork | None] = ContextVar(
    "inference_background", default=None
)


@contextmanager
def background_work(*, use_active_model=False, stop=None):
    previous = _background.get()
    token = _background.set(
        BackgroundWork(use_active_model, stop or (previous.stop if previous else None))
    )
    try:
        yield
    finally:
        _background.reset(token)


@contextmanager
def interactive_turn():
    """Protect the whole chat, including gaps between tools and continuations."""
    global _turns, _last_turn
    with _condition:
        _turns += 1
    try:
        yield
    finally:
        with _condition:
            _turns -= 1
            _last_turn = time.monotonic()
            _condition.notify_all()


class InferenceQueueTimeout(RuntimeError):
    """The local admission queue timed out, not the Ollama connection."""


class BackgroundStopped(RuntimeError):
    """The memory service stopped before its request reached Ollama."""


@dataclass(eq=False)
class _Ticket:
    work: BackgroundWork | None
    started: float
    admitted: bool = False


@dataclass
class InferenceLease:
    model: str
    wait_ms: float


class InferenceScheduler:
    def __init__(self, *, quiet_seconds: float = QUIET_SECONDS):
        self.quiet_seconds = quiet_seconds
        self._foreground = 0
        self._waiting = 0
        self._background_active = False
        self._pending: deque[_Ticket] = deque()
        self._last_foreground = 0.0
        self._model = ""

    def remember_model(self, model: str):
        # Only a successful foreground HTTP response establishes residency.
        if _background.get() is None:
            with _condition:
                self._model = model

    def _register(self):
        ticket = _Ticket(_background.get(), time.monotonic())
        with _condition:
            if ticket.work is None:
                self._waiting += 1
            else:
                self._pending.append(ticket)
        return ticket

    def _admit(self, ticket, model, timeout):
        """Called under the condition, atomically with registration/removal."""
        now = time.monotonic()
        work = ticket.work
        if work and work.stop is not None and work.stop.is_set():
            raise BackgroundStopped("Memory extraction stopped before inference")
        if (
            timeout is not None
            and (work is None or work.stop is None)
            and now - ticket.started >= timeout
        ):
            raise InferenceQueueTimeout(
                "Le moteur est occupé par une génération déjà en cours. "
                "Le délai d’attente de Diapason est dépassé."
            )
        if self._background_active:
            return None
        if work is None:
            # Preserve Ollama's configured parallelism for interactive callers.
            # Only housekeeping is exclusive, never sent ahead of queued chats.
            self._waiting -= 1
            self._foreground += 1
        else:
            if (
                self._foreground
                or self._waiting
                or _turns
                or self._pending[0] is not ticket
                or now - max(self._last_foreground, _last_turn) < self.quiet_seconds
            ):
                return None
            self._pending.popleft()
            self._background_active = True
            if work.use_active_model and self._model:
                model = self._model
        ticket.admitted = True
        return InferenceLease(model, (now - ticket.started) * 1000)

    def _remove(self, ticket):
        with _condition:
            if ticket.admitted:
                if ticket.work is None:
                    self._foreground -= 1
                    self._last_foreground = time.monotonic()
                else:
                    self._background_active = False
            elif ticket.work is None:
                self._waiting -= 1
            else:
                self._pending.remove(ticket)
            _condition.notify_all()

    @contextmanager
    def slot(self, model: str, *, timeout: float | None = None):
        ticket = self._register()
        try:
            with _condition:
                while (lease := self._admit(ticket, model, timeout)) is None:
                    # Check service shutdown within 50 ms without a new thread.
                    _condition.wait(0.05)
            yield lease
        finally:
            self._remove(ticket)

    @asynccontextmanager
    async def async_slot(self, model: str, *, timeout: float | None = None):
        ticket = self._register()
        try:
            while True:
                with _condition:
                    lease = self._admit(ticket, model, timeout)
                if lease is not None:
                    break
                # Only waiting requests poll. No executor thread can outlive a
                # cancelled coroutine and secretly claim the slot afterwards.
                await asyncio.sleep(0.01)
            yield lease
        finally:
            self._remove(ticket)


_schedulers: weakref.WeakValueDictionary[str, InferenceScheduler] = (
    weakref.WeakValueDictionary()
)


def scheduler_for(host: str) -> InferenceScheduler:
    url = urlsplit(host)
    hostname = url.hostname or ""
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        hostname = "localhost"
    port = url.port or (443 if url.scheme == "https" else 80)
    key = urlunsplit((url.scheme, f"{hostname}:{port}", url.path.rstrip("/"), "", ""))
    with _condition:
        scheduler = _schedulers.get(key)
        if scheduler is None:
            scheduler = InferenceScheduler()
            _schedulers[key] = scheduler
        return scheduler
