"""LocalTriggerChannel — file/socket trigger for clap and other local events."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from diapason.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from diapason.core.events import EventBus, EventType
from diapason.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


def default_trigger_path() -> Path:
    home = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".diapason"))
    return home / "triggers" / "local_trigger.jsonl"


@ChannelRegistry.register("local_trigger")
class LocalTriggerChannel(BaseChannel):
    """Watch a JSONL drop file for local events (e.g. double-clap welcome).

    Writers append one JSON object per line::

        {"event": "welcome_home", "content": "Run welcome-clap sequence"}

    The channel polls the file and dispatches :class:`ChannelMessage` to handlers.
    """

    channel_id = "local_trigger"
    # Fichier ou socket sur cette machine — aucun client HTTP, aucune URL
    # distante dans ce module. Vérifié.
    is_local = True

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        path: Path | str | None = None,
        poll_s: float = 0.35,
    ) -> None:
        self._bus = bus
        self._path = Path(path) if path else default_trigger_path()
        self._poll_s = poll_s
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset = 0

    def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._offset = self._path.stat().st_size
        self._status = ChannelStatus.CONNECTED
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="local-trigger", daemon=True
        )
        self._thread.start()
        logger.info("local_trigger watching %s", self._path)

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._status = ChannelStatus.DISCONNECTED

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        # Outbound: append an event others can observe
        self.emit(content, event=metadata.get("event", "outbound") if metadata else "outbound")
        return True

    def status(self) -> ChannelStatus:
        return self._status

    def list_channels(self) -> List[str]:
        return ["local_trigger"]

    def on_message(self, handler: ChannelHandler) -> None:
        self._handlers.append(handler)

    def emit(self, content: str, *, event: str = "welcome_home", **extra: Any) -> None:
        """Append a trigger event (used by clap listener / CLI)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"event": event, "content": content, **extra}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._path.is_file():
                    size = self._path.stat().st_size
                    if size < self._offset:
                        self._offset = 0
                    if size > self._offset:
                        with self._path.open("r", encoding="utf-8") as f:
                            f.seek(self._offset)
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                self._dispatch_line(line)
                            self._offset = f.tell()
            except OSError as exc:
                logger.warning("local_trigger poll error: %s", exc)
            time.sleep(self._poll_s)

    def _dispatch_line(self, line: str) -> None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            data = {"event": "raw", "content": line}
        content = str(data.get("content") or data.get("event") or line)
        msg = ChannelMessage(
            channel="local_trigger",
            sender="local",
            content=content,
            conversation_id=str(data.get("event") or "local"),
            metadata=data if isinstance(data, dict) else {},
        )
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_RECEIVED,
                {"channel": "local_trigger", "content": content},
            )
        for handler in list(self._handlers):
            try:
                handler(msg)
            except Exception:
                logger.exception("local_trigger handler failed")


__all__ = ["LocalTriggerChannel", "default_trigger_path"]
